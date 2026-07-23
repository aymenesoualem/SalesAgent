import asyncio
import os
import signal

from dotenv import load_dotenv

load_dotenv()

from agents.sip_agent import start_sip_agent
from main import build_system_message, INITIAL_MESSAGE
from tools.functioncalling import inbound_support_tool_schemas

async def run():
    if not os.getenv("SIP_SERVER") or not os.getenv("SIP_LOGIN") or not os.getenv("SIP_PASSWORD"):
        raise SystemExit("SIP_SERVER, SIP_LOGIN and SIP_PASSWORD must be set (see .env.example).")
    
    
    client = await start_sip_agent(build_system_message, INITIAL_MESSAGE, inbound_support_tool_schemas)
    print("[SIP] Agent registered and waiting for calls. Press Ctrl+C to stop.")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        print("[SIP] Shutting down.")
        await client.close()
        

        


if __name__ == "__main__":
    asyncio.run(run())
