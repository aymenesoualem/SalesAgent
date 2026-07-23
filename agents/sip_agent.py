"""
Direct SIP connectivity for the voice agent, via a hosted Janus Gateway (SIP plugin)
provided by the SIP trunk operator (Manivox), instead of Twilio.

Flow: this process registers as a SIP client to Manivox's Janus instance over the
Janus WebSocket API. Inbound calls to the registered SDA arrive as a WebRTC offer
(JSEP) from Janus; we answer it with aiortc, then bridge the call's audio to/from
the Azure AI Foundry Realtime API exactly like agents/agent.py does for Twilio.

Exercised against real inbound and outbound calls. Verified: registration, inbound
answer, outbound dialing, bidirectional audio, VAD-based interruption handling.
Console logging is intentionally minimal (transcripts + errors only); a live
call-activity feed is published via agents/call_events.py for the Streamlit
console (sip_interface.py).
"""

import asyncio
import base64
import fractions
import json
import os
import re
import ssl
import uuid

import websockets
from av import AudioFrame, AudioResampler
from aiortc import (
    RTCConfiguration,
    RTCIceCandidate,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
    MediaStreamTrack,
)
from aiortc.mediastreams import MediaStreamError
from aiortc.sdp import candidate_from_sdp

from agents.agent import _build_realtime_url, AZURE_OPENAI_API_KEY, VOICE, build_turn_detection_config, send_initial_conversation_item
from agents.call_events import log_event
from tools.functioncalling import invoke_function
from tools.tools import get_customer_by_phone, get_orders_by_phone
from utils import create_digishare_ticket

JANUS_WS_URL = os.getenv("SIP_JANUS_WS_URL", "wss://185.101.180.254:8989/")
SIP_SERVER = os.getenv("SIP_SERVER")
SIP_LOGIN = os.getenv("SIP_LOGIN")
SIP_PASSWORD = os.getenv("SIP_PASSWORD")
SIP_SDA = os.getenv("SIP_SDA")
SIP_DOMAIN = os.getenv("SIP_DOMAIN", "sbc.manivox.com")
TURN_HOST = os.getenv("SIP_TURN_HOST", "webrtc01.manifone.com")
TURN_USERNAME = os.getenv("SIP_TURN_USERNAME", "manivox")
TURN_CREDENTIAL = os.getenv("SIP_TURN_CREDENTIAL", "12348888")

SIP_URI = f"sip:{SIP_LOGIN}@{SIP_DOMAIN}"
SIP_PROXY = f"sip:{SIP_SERVER}"

AZURE_AUDIO_RATE = 24000  # required by Azure Realtime API's pcm16 format
AUDIO_PTIME = 0.02  # 20ms per frame, matches WebRTC convention


def _tx_id() -> str:
    return uuid.uuid4().hex[:8]


def _extract_caller_id(result: dict) -> str:
    """Extract the caller's number from a Janus SIP 'incomingcall' event.

    `username`/`displayname` are SIP URIs (e.g. 'sip:33612345678@sbc.manivox.com') or
    a quoted name wrapping one ('"Sylvie Garrido" <sip:33612345678@sbc.manivox.com>').
    Naively stripping non-digit characters from the raw string (as normalize_phone_number
    does downstream) would also swallow digits from the domain — a problem when the
    domain is an IP address — so pull out just the URI's user part first. This is what
    build_system_message uses to look up the caller in the customers/orders tables, so
    getting it wrong means the agent never recognizes a known caller on inbound calls.
    """
    for field in ("username", "displayname"):
        value = result.get(field)
        if not value:
            continue
        match = re.search(r"sip:([^@;>\s]+)@", value)
        if match:
            return match.group(1)
    print(result)
    return result.get("displayname") or result.get("username") or "Unknown caller"


def _log_caller_data(caller: str) -> None:
    """Print what the system knows about an inbound caller as soon as the call comes
    in — same customers/orders lookup build_system_message uses, surfaced to the
    console so a plain `python sipmain.py` run (no Streamlit dashboard) shows it too,
    not just the in-memory event feed."""
    caller = "00" + caller
    customers = get_customer_by_phone(caller)
    if not customers:
        print(f"[SIP] Incoming call from {caller} — unknown caller, not in the system.")
    else:
        names = ", ".join(c["full_name"] for c in customers)
        print(f"[SIP] Incoming call from {caller} — known customer(s): {names}")

    orders = get_orders_by_phone(caller)
    if not orders:
        print(f"[SIP]   No orders on file for {caller}.")
    else:
        for o in orders:
            print(
                f"[SIP]   Order {o['order_number']} ({o['customer_name']}): "
                f"{o['product_name']} (Réf: {o['product_reference']}) — Statut: {o['status']}"
            )


class AzureOutboundAudioTrack(MediaStreamTrack):
    """A synthetic WebRTC audio track fed by PCM16/24kHz audio coming from Azure."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer = b""
        self._timestamp = 0
        self._start = None

    def push(self, pcm16_bytes: bytes) -> None:
        self._queue.put_nowait(pcm16_bytes)

    def clear(self) -> None:
        """Drop any buffered/queued audio so playback stops immediately — used when
        the caller interrupts the agent (input_audio_buffer.speech_started)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._buffer = b""

    async def recv(self) -> AudioFrame:
        samples = int(AUDIO_PTIME * AZURE_AUDIO_RATE)
        chunk_size = samples * 2  # 16-bit samples

        while len(self._buffer) < chunk_size:
            try:
                self._buffer += await asyncio.wait_for(self._queue.get(), timeout=AUDIO_PTIME)
            except asyncio.TimeoutError:
                self._buffer += b"\x00" * (chunk_size - len(self._buffer))

        chunk, self._buffer = self._buffer[:chunk_size], self._buffer[chunk_size:]

        loop = asyncio.get_event_loop()
        if self._start is None:
            self._start = loop.time()
        else:
            self._timestamp += samples
            wait = self._start + (self._timestamp / AZURE_AUDIO_RATE) - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)

        frame = AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(chunk)
        frame.pts = self._timestamp
        frame.sample_rate = AZURE_AUDIO_RATE
        frame.time_base = fractions.Fraction(1, AZURE_AUDIO_RATE)
        return frame


class _Call:
    def __init__(self, janus: "JanusSipClient", system_message: str, initial_message: str, tool_schemas, caller: str):
        self.janus = janus
        self.system_message = system_message
        self.initial_message = initial_message
        self.tool_schemas = tool_schemas
        self.caller = caller
        self.pending_whatsapp_form = None

        self.pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[
            RTCIceServer(urls=f"stun:{TURN_HOST}"),
            RTCIceServer(urls=f"turn:{TURN_HOST}", username=TURN_USERNAME, credential=TURN_CREDENTIAL),
        ]))
        self.outbound_track = AzureOutboundAudioTrack()
        self.pc.addTrack(self.outbound_track)

        self._azure_ws = None
        self._tasks: list[asyncio.Task] = []
        self._teardown_started = False
        self._answered = False
        self._remote_sdp_set = False
        self._current_response_item_id = None
        self._current_response_started_at = None
        self.ended = asyncio.Event()

        @self.pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                self._tasks.append(asyncio.create_task(self._pump_caller_audio(track)))

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if self.pc.connectionState in ("failed", "closed"):
                await self.teardown()

    async def close(self, code=1000, reason="") -> None:
        """Gives invoke_function's hangup_function something with an async .close() to call."""
        await self.teardown()

    async def add_remote_candidate(self, candidate: dict) -> None:
        try:
            ice_candidate = candidate_from_sdp(candidate["candidate"].split("candidate:", 1)[-1])
            ice_candidate.sdpMid = candidate.get("sdpMid")
            ice_candidate.sdpMLineIndex = candidate.get("sdpMLineIndex")
            await self.pc.addIceCandidate(ice_candidate)
        except Exception as e:
            print(f"[ERROR] Failed to add remote ICE candidate: {e}")

    async def answer(self, jsep: dict) -> None:
        """Inbound call: answer the SDP offer Janus sends us."""
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=jsep["sdp"], type=jsep["type"]))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        # aiortc waits for full ICE gathering before setLocalDescription returns,
        # so pc.localDescription.sdp already contains all local candidates here.
        await self.janus.send_accept(self.pc.localDescription.sdp)
        self._answered = True
        self._tasks.append(asyncio.create_task(self._run_azure_bridge()))

    async def place(self, destination: str) -> None:
        """Outbound call: offer our SDP and ask Janus to dial `destination`."""
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        uri = destination if destination.startswith("sip:") else f"sip:{destination}@{SIP_SERVER}"
        await self.janus.send_call(uri, self.pc.localDescription.sdp)

    async def set_remote_sdp(self, jsep: dict) -> None:
        """Outbound call: apply the callee-side SDP whenever Janus sends it (this can
        arrive on 'progress'/early-media, before the callee has actually answered)."""
        if self._remote_sdp_set:
            return
        self._remote_sdp_set = True
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=jsep["sdp"], type=jsep["type"]))

    async def start_conversation(self) -> None:
        """Outbound call: start the Azure Realtime bridge. Only call this once the call
        is truly answered ('accepted') — starting it on ringback/early media makes the
        agent talk (and its own VAD react) before anyone is actually on the line, which
        looks like the agent talking to itself."""
        if self._answered:
            return
        self._answered = True
        self._tasks.append(asyncio.create_task(self._run_azure_bridge()))

    async def _pump_caller_audio(self, track) -> None:
        resampler = AudioResampler(format="s16", layout="mono", rate=AZURE_AUDIO_RATE)
        try:
            while True:
                frame = await track.recv()
                for resampled in resampler.resample(frame):
                    pcm_bytes = resampled.to_ndarray().astype("<i2").tobytes()
                    if self._azure_ws is not None:
                        await self._azure_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm_bytes).decode("utf-8"),
                        }))
        except MediaStreamError:
            pass
        except Exception as e:
            print(f"[ERROR] Pumping caller audio: {e}")

    async def _run_azure_bridge(self) -> None:
        ssl_context = ssl.create_default_context()
        try:
            async with websockets.connect(
                    _build_realtime_url(),
                    ssl=ssl_context,
                    extra_headers={"api-key": AZURE_OPENAI_API_KEY},
            ) as azure_ws:
                self._azure_ws = azure_ws
                session_update = {
                    "type": "session.update",
                    "session": {
                        "turn_detection": build_turn_detection_config(),
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "input_audio_transcription": {"model": "whisper-1"},
                        "voice": VOICE,
                        "instructions": self.system_message,
                        "modalities": ["text", "audio"],
                        "temperature": 0.8,
                        "tools": self.tool_schemas,
                    },
                }
                await azure_ws.send(json.dumps(session_update))
                await send_initial_conversation_item(azure_ws, self.initial_message)

                async for message in azure_ws:
                    response = json.loads(message)
                    event_type = response.get("type")

                    if event_type == "error":
                        print(f"[ERROR] Azure Realtime: {response.get('error')}")
                        log_event("error", str(response.get("error")), call_id=self.caller)

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = response.get("transcript", "").strip()
                        print(f"[Caller] {transcript}")
                        log_event("transcript_caller", transcript, call_id=self.caller)

                    elif event_type == "conversation.item.input_audio_transcription.failed":
                        print(f"[ERROR] Caller audio transcription failed: {response.get('error')}")
                        log_event("error", f"Transcription failed: {response.get('error')}", call_id=self.caller)

                    if event_type == "response.audio.delta" and "delta" in response:
                        item_id = response.get("item_id")
                        if item_id and item_id != self._current_response_item_id:
                            self._current_response_item_id = item_id
                            self._current_response_started_at = asyncio.get_event_loop().time()
                        self.outbound_track.push(base64.b64decode(response["delta"]))

                    elif event_type == "input_audio_buffer.speech_started":
                        # Caller started talking (or interrupting) — stop playback of
                        # whatever's still queued immediately, and tell Azure how much
                        # of the current response the caller actually heard before
                        # being cut off, so it doesn't think it finished saying it.
                        self.outbound_track.clear()
                        if self._current_response_item_id is not None:
                            elapsed_ms = 0
                            if self._current_response_started_at is not None:
                                elapsed_ms = max(0, int((asyncio.get_event_loop().time() - self._current_response_started_at) * 1000))
                            await azure_ws.send(json.dumps({
                                "type": "conversation.item.truncate",
                                "item_id": self._current_response_item_id,
                                "content_index": 0,
                                "audio_end_ms": elapsed_ms,
                            }))
                            self._current_response_item_id = None
                            self._current_response_started_at = None

                    elif event_type == "response.done":
                        resp = response["response"]
                        if resp.get("status") == "completed":
                            # This response played out in full (only one response is ever
                            # in flight at a time here) — nothing left to truncate for it,
                            # so stop tracking it. Otherwise a much later interruption would
                            # compute a bogus, overshot audio_end_ms against an item that
                            # already finished, and Azure would reject the truncate.
                            self._current_response_item_id = None
                            self._current_response_started_at = None

                        output = resp.get("output", [])
                        for item in output:
                            if item.get("type") == "message":
                                for content in item.get("content", []):
                                    transcript = content.get("transcript")
                                    if transcript:
                                        transcript = transcript.strip()
                                        print(f"[Conseiller] {transcript}")
                                        log_event("transcript_agent", transcript, call_id=self.caller)
                            elif item.get("type") == "function_call":
                                function_name = item.get("name")
                                arguments = json.loads(item.get("arguments", "{}"))
                                call_id = item.get("call_id")
                                result = await invoke_function(function_name, arguments, self)
                                log_event("tool_call", f"{function_name}({arguments}) → {result}", call_id=self.caller)
                                await azure_ws.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": json.dumps(result),
                                    },
                                }))
                                await azure_ws.send(json.dumps({"type": "response.create"}))
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            print(f"[ERROR] Azure Realtime bridge: {e}")
        finally:
            await self.teardown()

    async def teardown(self) -> None:
        if self._teardown_started:
            return
        self._teardown_started = True

        for task in self._tasks:
            task.cancel()
        if self._azure_ws is not None:
            await self._azure_ws.close()
        await self.pc.close()
        try:
            await self.janus.send_hangup()
        except Exception:
            pass

        if self.pending_whatsapp_form:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    create_digishare_ticket,
                    self.pending_whatsapp_form["phone_number"],
                    self.pending_whatsapp_form["customer_name"],
                )
                log_event("status", "WhatsApp satisfaction survey ticket created", call_id=self.caller)
            except Exception as e:
                print(f"[ERROR] Failed to create WhatsApp survey ticket: {e}")
                log_event("error", f"Failed to create WhatsApp survey ticket: {e}", call_id=self.caller)

        self.janus.clear_active_call(self)
        self.ended.set()


class JanusSipClient:
    """Minimal Janus WebSocket client for the SIP plugin, ported from the reference
    React hook (register / incomingcall / accept / hangup / trickle ICE)."""

    def __init__(self, system_message_builder, initial_message: str, tool_schemas):
        """system_message_builder(caller: str) -> str, so the prompt can embed the
        caller's number/identity the same way the Twilio path does."""
        self.system_message_builder = system_message_builder
        self.initial_message = initial_message
        self.tool_schemas = tool_schemas

        self._ws = None
        self._session_id = None
        self._handle_id = None
        self._pending: dict[str, asyncio.Future] = {}
        self._keepalive_task = None
        self._recv_task = None
        self._active_call: _Call | None = None

    async def connect_and_register(self) -> None:
        self._ws = await websockets.connect(JANUS_WS_URL, subprotocols=["janus-protocol"])
        self._recv_task = asyncio.create_task(self._recv_loop())

        session_resp = await self._request({"janus": "create"})
        self._session_id = session_resp["data"]["id"]

        attach_resp = await self._request({
            "janus": "attach",
            "plugin": "janus.plugin.sip",
            "session_id": self._session_id,
        })
        self._handle_id = attach_resp["data"]["id"]

        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        await self._send({
            "janus": "message",
            "session_id": self._session_id,
            "handle_id": self._handle_id,
            "transaction": _tx_id(),
            "body": {
                "request": "register",
                "username": SIP_URI,
                "secret": SIP_PASSWORD,
                "proxy": SIP_PROXY,
            },
        })

    @property
    def current_call(self) -> "_Call | None":
        return self._active_call

    async def close(self) -> None:
        if self._active_call is not None:
            await self._active_call.teardown()
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws is not None:
            await self._ws.close()

    def clear_active_call(self, call: "_Call") -> None:
        if self._active_call is call:
            self._active_call = None

    async def place_call(self, destination: str, system_message: str, initial_message: str, tool_schemas) -> "_Call":
        """Places an outbound call to `destination` (a bare number or a full sip: URI)."""
        if self._active_call is not None:
            raise RuntimeError("Already on a call")
        log_event("status", f"Placing outbound call to {destination}", call_id=destination)
        call = _Call(self, system_message, initial_message, tool_schemas, destination)
        self._active_call = call
        await call.place(destination)
        return call

    async def send_call(self, uri: str, sdp_offer: str) -> None:
        await self._send({
            "janus": "message",
            "session_id": self._session_id,
            "handle_id": self._handle_id,
            "transaction": _tx_id(),
            "body": {"request": "call", "uri": uri, "headers": {}},
            "jsep": {"type": "offer", "sdp": sdp_offer},
        })

    async def send_accept(self, sdp_answer: str) -> None:
        await self._send({
            "janus": "message",
            "session_id": self._session_id,
            "handle_id": self._handle_id,
            "transaction": _tx_id(),
            "body": {"request": "accept"},
            "jsep": {"type": "answer", "sdp": sdp_answer},
        })

    async def send_hangup(self) -> None:
        await self._send({
            "janus": "message",
            "session_id": self._session_id,
            "handle_id": self._handle_id,
            "transaction": _tx_id(),
            "body": {"request": "hangup"},
        })

    async def _send(self, msg: dict) -> None:
        await self._ws.send(json.dumps(msg))

    async def _request(self, msg: dict, timeout: float = 10) -> dict:
        tx = _tx_id()
        msg["transaction"] = tx
        fut = asyncio.get_event_loop().create_future()
        self._pending[tx] = fut
        await self._send(msg)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(tx, None)

    async def _keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(25)
            try:
                await self._send({
                    "janus": "keepalive",
                    "session_id": self._session_id,
                    "transaction": _tx_id(),
                })
            except websockets.ConnectionClosed:
                break

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                await self._handle_event(json.loads(raw))
        except websockets.ConnectionClosed as e:
            print(f"[ERROR] Janus WebSocket closed: {e}")

    async def _handle_event(self, msg: dict) -> None:
        janus_type = msg.get("janus")
        tx = msg.get("transaction")

        if tx and tx in self._pending:
            fut = self._pending[tx]
            if janus_type == "success" and not fut.done():
                fut.set_result(msg)
                return
            if janus_type == "error" and not fut.done():
                fut.set_exception(RuntimeError(msg.get("error", {}).get("reason", "Janus error")))
                return

        if janus_type == "trickle":
            candidate = msg.get("candidate")
            if self._active_call and candidate and not candidate.get("completed"):
                await self._active_call.add_remote_candidate(candidate)
            return

        if janus_type != "event":
            return

        plugindata = msg.get("plugindata", {}).get("data", {})
        result = plugindata.get("result")
        if not result:
            return

        event = result.get("event")
        jsep = msg.get("jsep")

        if event == "registered":
            log_event("status", "Registered with SIP trunk")
        elif event == "registration_failed":
            print(f"[ERROR] SIP registration failed: {result.get('reason')}")
            log_event("error", f"SIP registration failed: {result.get('reason')}")
        elif event == "incomingcall":
            caller = _extract_caller_id(result)
            if self._active_call is not None:
                await self.send_hangup()
                return
            _log_caller_data(caller)
            log_event("status", f"Incoming call from {caller}", call_id=caller)
            call = _Call(self, self.system_message_builder(caller), self.initial_message, self.tool_schemas, caller)
            self._active_call = call
            await call.answer(jsep)
        elif event == "progress":
            if jsep and self._active_call is not None:
                await self._active_call.set_remote_sdp(jsep)
        elif event == "accepted":
            if self._active_call is not None:
                if jsep:
                    await self._active_call.set_remote_sdp(jsep)
                log_event("status", "Call answered", call_id=self._active_call.caller)
                await self._active_call.start_conversation()
        elif event in ("hangup", "missed", "declined"):
            if self._active_call is not None:
                log_event("status", f"Call ended ({event})", call_id=self._active_call.caller)
                await self._active_call.teardown()


async def start_sip_agent(system_message_builder, initial_message: str, tool_schemas) -> JanusSipClient:
    """Registers this app to the SIP trunk and starts handling inbound calls.

    system_message_builder: a callable taking the caller's number/display name
    and returning the full system prompt (see main.build_system_message). The
    caller identity ("displayname" or "username" from Janus's incomingcall
    event) isn't guaranteed to be a clean E.164 phone number depending on how
    Manivox populates SIP headers — verify against a real call.
    """
    client = JanusSipClient(system_message_builder, initial_message, tool_schemas)
    await client.connect_and_register()
    return client
