import argparse
import asyncio
import os
import signal

from dotenv import load_dotenv

load_dotenv()

from agents.sip_agent import start_sip_agent
from main import build_system_message, build_outbound_initial_message, OUTBOUND_INITIAL_MESSAGE
from tools.functioncalling import inbound_support_tool_schemas


async def run(destination: str) -> None:
    if not os.getenv("SIP_SERVER") or not os.getenv("SIP_LOGIN") or not os.getenv("SIP_PASSWORD"):
        raise SystemExit("SIP_SERVER, SIP_LOGIN and SIP_PASSWORD must be set (see .env.example).")

    client = await start_sip_agent(build_system_message, OUTBOUND_INITIAL_MESSAGE, inbound_support_tool_schemas)
    print(f"[SIP] Registered. Placing outbound call to {destination}...")

    call = await client.place_call(
        destination,
        build_system_message(destination),
        build_outbound_initial_message(destination),
        inbound_support_tool_schemas,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(call.teardown()))

    try:
        await call.ended.wait()
        print("[SIP] Call ended.")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Place an outbound call through the SIP trunk, handled by the AI agent.")
    parser.add_argument("phone_number", help="Destination number to call, e.g. +212612345678 or a bare SIP user part")
    args = parser.parse_args()

    asyncio.run(run(args.phone_number))
