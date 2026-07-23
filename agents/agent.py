import ssl
import os
import json
import base64
import asyncio
import websockets
from urllib.parse import urlparse
from fastapi.websockets import WebSocketDisconnect
from fastapi import WebSocket
from tools.functioncalling import invoke_function
from utils import create_digishare_ticket

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")
active_websocket = set()


def _build_realtime_url() -> str:
    """Build the Azure AI Foundry (Azure OpenAI) Realtime API WebSocket URL."""
    host = urlparse(AZURE_OPENAI_ENDPOINT).netloc or AZURE_OPENAI_ENDPOINT
    return (
        f"wss://{host}/openai/realtime"
        f"?api-version={AZURE_OPENAI_API_VERSION}"
        f"&deployment={AZURE_OPENAI_DEPLOYMENT_NAME}"
    )



# Realtime voice options: alloy, ash, ballad, coral, echo, sage, shimmer, verse, marin, cedar.
# marin/cedar are the newest, most natural-sounding voices for the gpt-realtime model family.
VOICE = os.getenv("AZURE_REALTIME_VOICE", "marin")


def build_turn_detection_config() -> dict | None:
    """Builds the session's `turn_detection` config, i.e. how the model decides the
    caller has finished a turn and it should respond.

    AZURE_REALTIME_TURN_DETECTION selects the mode:
    - "server_vad" (default): silence-based. Fires after AZURE_REALTIME_VAD_SILENCE_MS
      of silence. Fast and predictable, but a shorter silence_duration_ms can cut
      callers off mid-pause, while a longer one adds latency to every turn.
    - "semantic_vad": model-based. Uses the words said so far to judge whether the
      caller actually finished their thought (vs. trailing off with "euh..."),
      rather than a fixed silence timer — generally better for natural conversation,
      at the cost of slightly less predictable latency. Tuned via
      AZURE_REALTIME_VAD_EAGERNESS (low/medium/high/auto).
    - "none": disables VAD entirely (manual/push-to-talk turn handling) — not used
      by this app's always-listening phone agent.
    """
    mode = os.getenv("AZURE_REALTIME_TURN_DETECTION", "server_vad")

    if mode == "none":
        return None

    if mode == "semantic_vad":
        return {
            "type": "semantic_vad",
            "eagerness": os.getenv("AZURE_REALTIME_VAD_EAGERNESS", "auto"),
            "create_response": True,
            "interrupt_response": True,
        }

    return {
        "type": "server_vad",
        "threshold": float(os.getenv("AZURE_REALTIME_VAD_THRESHOLD", "0.5")),
        "prefix_padding_ms": int(os.getenv("AZURE_REALTIME_VAD_PREFIX_PADDING_MS", "300")),
        "silence_duration_ms": int(os.getenv("AZURE_REALTIME_VAD_SILENCE_MS", "500")),
        "create_response": True,
        "interrupt_response": True,
    }
LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created','function_call_arguments.done'
]
SHOW_TIMING_MATH = False

async def send_initial_conversation_item(openai_ws,initial_message):
    """Send initial conversation item if AI talks first."""
    initial_conversation_item = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": initial_message
                }
            ]
        }
    }
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))

async def initialize_session(openai_ws,system_message,initial_message,tool_schemas= None):
    """Control initial session with Azure AI Foundry Realtime API."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": build_turn_detection_config(),
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": system_message,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
            "tools":tool_schemas
        }
}



    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

    # Uncomment the next line to have the AI speak first
    await send_initial_conversation_item(openai_ws, initial_message)
async def handle_call(websocket: WebSocket,system_message,initial_message,tool_schemas= None):
    """Handle WebSocket connections between Twilio and Azure AI Foundry (Azure OpenAI Realtime API)."""
    print("Client connected")
    await websocket.accept()
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with websockets.connect(
            _build_realtime_url(),
            ssl=ssl_context,
            extra_headers={
                "api-key": AZURE_OPENAI_API_KEY
            }
    ) as openai_ws:
        await initialize_session(openai_ws,system_message=system_message,initial_message=initial_message,tool_schemas=tool_schemas)
        global active_websocket
        active_websocket.add(websocket)
        active_websocket.add(openai_ws)
        # Connection specific state
        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None


        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the Azure AI Foundry Realtime API."""
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)

                    if data['event'] == 'media' and openai_ws.open:
                        latest_media_timestamp = int(data['media']['timestamp'])
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
            except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the Azure AI Foundry Realtime API, send audio back to Twilio."""
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)

                    if response.get('type') == 'response.done':
                        # Safely extract the transcript if output is available
                        output = response['response'].get('output', [])
                        if output:
                            for item in output:
                                if item.get('type') == 'function_call':
                                    function_name = item.get('name')
                                    arguments = json.loads(item.get('arguments', "{}"))
                                    call_id = item.get('call_id')

                                    print(f"Detected function call: {function_name} with arguments: {arguments}")
                                    result = await invoke_function(function_name, arguments,websocket)
                                    # Send function_call_output to Azure AI Foundry
                                    await openai_ws.send(json.dumps({
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "function_call_output",
                                            "call_id": call_id,
                                            "output": json.dumps(result)
                                        }
                                    }))
                                    await openai_ws.send(json.dumps({"type": "response.create"}))



                        else:
                            print("No output in response.done")

                    if response.get('type') == 'response.audio.delta' and 'delta' in response:
                        audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                        audio_delta = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": audio_payload
                            }
                        }
                        await websocket.send_json(audio_delta)

                        if response_start_timestamp_twilio is None:
                            response_start_timestamp_twilio = latest_media_timestamp
                            if SHOW_TIMING_MATH:
                                print(f"Setting start timestamp for new response: {response_start_timestamp_twilio}ms")

                        # Update last_assistant_item safely
                        if response.get('item_id'):
                            last_assistant_item = response['item_id']

                        await send_mark(websocket, stream_sid)

                    # Trigger an interruption. Your use case might work better using `input_audio_buffer.speech_stopped`, or combining the two.
                    if response.get('type') == 'input_audio_buffer.speech_started':
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(f"Interrupting response with id: {last_assistant_item}")
                            await handle_speech_started_event()


            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        async def handle_speech_started_event():
            """Handle interruption when the caller's speech starts."""
            nonlocal response_start_timestamp_twilio, last_assistant_item
            print("Handling speech started event.")
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                if SHOW_TIMING_MATH:
                    print(
                        f"Calculating elapsed time for truncation: {latest_media_timestamp} - {response_start_timestamp_twilio} = {elapsed_time}ms")

                if last_assistant_item:
                    if SHOW_TIMING_MATH:
                        print(f"Truncating item with ID: {last_assistant_item}, Truncated at: {elapsed_time}ms")

                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed_time
                    }
                    await openai_ws.send(json.dumps(truncate_event))

                await websocket.send_json({
                    "event": "clear",
                    "streamSid": stream_sid
                })

                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
            if stream_sid:
                mark_event = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"}
                }
                await connection.send_json(mark_event)
                mark_queue.append('responsePart')

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

        pending_whatsapp_form = getattr(websocket, "pending_whatsapp_form", None)
        if pending_whatsapp_form:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    create_digishare_ticket,
                    pending_whatsapp_form["phone_number"],
                    pending_whatsapp_form["customer_name"],
                )
            except Exception as e:
                print(f"Failed to create WhatsApp survey ticket: {e}")