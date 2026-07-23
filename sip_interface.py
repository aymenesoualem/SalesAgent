import asyncio
import threading
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agents.call_events import get_events, clear_events
from agents.sip_agent import start_sip_agent, SIP_SDA
from main import build_system_message, INITIAL_MESSAGE, OUTBOUND_INITIAL_MESSAGE, build_outbound_initial_message
from tools.functioncalling import inbound_support_tool_schemas
from models.model import get_session, SupportTicket, Product, Store, Order, Customer

st.set_page_config(page_title="Histoire d'Or SIP Agent", layout="wide")
st.title("📞 Histoire d'Or — SIP Agent Console")
st.caption(
    "One SIP registration handles both directions: once started, it answers inbound "
    "calls automatically and can place outbound calls on demand. Single-operator tool — "
    "opening this in two browser tabs would register the same SIP account twice."
)


# --- Background asyncio loop, persisted across Streamlit reruns for this session ---
def _loop_runner(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _ensure_background_loop() -> asyncio.AbstractEventLoop:
    if "bg_loop" not in st.session_state:
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=_loop_runner, args=(loop,), daemon=True)
        thread.start()
        st.session_state.bg_loop = loop
        st.session_state.bg_thread = thread
    return st.session_state.bg_loop


def _run_coro(coro, timeout: float = 15):
    loop = _ensure_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


if "sip_client" not in st.session_state:
    st.session_state.sip_client = None
if "sip_error" not in st.session_state:
    st.session_state.sip_error = None

# --- Controls ---
col_agent, col_call = st.columns(2)

with col_agent:
    st.subheader("Agent")
    if st.session_state.sip_client is None:
        if st.button("▶️ Start agent (register + answer inbound calls)", type="primary"):
            st.session_state.sip_error = None
            try:
                client = _run_coro(start_sip_agent(build_system_message, INITIAL_MESSAGE, inbound_support_tool_schemas))
                st.session_state.sip_client = client
            except Exception as e:
                st.session_state.sip_error = f"Failed to start: {e}"
            st.rerun()
    else:
        sda_label = SIP_SDA or "(no SDA configured)"
        st.success(f"Registered — answering inbound calls on {sda_label}")
        if st.button("⏹️ Stop agent"):
            try:
                _run_coro(st.session_state.sip_client.close())
            except Exception as e:
                st.session_state.sip_error = f"Error while stopping: {e}"
            st.session_state.sip_client = None
            st.rerun()

    if st.session_state.sip_error:
        st.error(st.session_state.sip_error)

with col_call:
    st.subheader("Place an outbound call")
    agent_running = st.session_state.sip_client is not None
    phone_number = st.text_input("Destination number", placeholder="+212612345678", disabled=not agent_running)
    if not agent_running:
        st.caption("Start the agent first.")
    if st.button("📞 Call", disabled=not agent_running or not phone_number):
        try:
            _run_coro(st.session_state.sip_client.place_call(
                phone_number,
                build_system_message(phone_number),
                build_outbound_initial_message(phone_number),
                inbound_support_tool_schemas,
            ))
            st.success(f"Calling {phone_number}...")
        except Exception as e:
            st.error(f"Failed to place call: {e}")

st.divider()


# --- Live call status + transcript / tool-call log, auto-refreshing ---
@st.fragment(run_every=1)
def _render_live_panel():
    client = st.session_state.sip_client
    if client is not None:
        current_call = client.current_call
        if current_call is not None:
            hangup_col, status_col = st.columns([1, 4])
            with status_col:
                st.info(f"📞 In call with **{current_call.caller}**")
            with hangup_col:
                if st.button("Hang up", key="hangup_button"):
                    _run_coro(current_call.teardown())
                    st.rerun()

    st.subheader("Live call log")
    events = get_events()
    if not events:
        st.caption("No call activity yet.")
        return
    icons = {
        "transcript_caller": "🗣️",
        "transcript_agent": "🤖",
        "tool_call": "🔧",
        "status": "ℹ️",
        "error": "⚠️",
    }
    labels = {
        "transcript_caller": "Caller",
        "transcript_agent": "Conseiller",
        "tool_call": "Tool",
        "status": "Status",
        "error": "Error",
    }
    for event in reversed(events[-200:]):
        ts = datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S")
        icon = icons.get(event.kind, "•")
        label = labels.get(event.kind, event.kind)
        st.markdown(f"`{ts}` {icon} **{label}:** {event.text}")


_render_live_panel()

if st.button("Clear log"):
    clear_events()
    st.rerun()

st.divider()

# --- Database ---
st.subheader("Support tickets")
try:
    session = get_session()
    try:
        tickets = session.query(SupportTicket).order_by(SupportTicket.id.desc()).limit(50).all()
    finally:
        session.close()

    if tickets:
        st.dataframe(
            [{
                "id": t.id,
                "name": t.name,
                "phone": t.phone_number,
                "issue_type": t.issue_type,
                "priority": t.priority,
                "summary": t.summary,
            } for t in tickets],
            use_container_width=True,
        )
    else:
        st.info("No support tickets yet.")
except Exception as e:
    st.error(f"Database connection error: {e}")

with st.expander("Products"):
    try:
        session = get_session()
        try:
            products = session.query(Product).all()
        finally:
            session.close()
        st.dataframe(
            [{
                "id": p.id, "brand": p.brand, "name": p.name, "category": p.category,
                "material": p.material, "price": float(p.price), "in_stock": p.in_stock,
            } for p in products],
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"Database connection error: {e}")

with st.expander("Stores"):
    try:
        session = get_session()
        try:
            stores = session.query(Store).all()
        finally:
            session.close()
        st.dataframe(
            [{
                "id": s.id, "name": s.name, "city": s.city,
                "address": s.address, "phone": s.phone, "opening_hours": s.opening_hours,
            } for s in stores],
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"Database connection error: {e}")

with st.expander("Customers"):
    try:
        session = get_session()
        try:
            customers = session.query(Customer).order_by(Customer.id.desc()).limit(50).all()
        finally:
            session.close()
        st.dataframe(
            [{
                "id": c.id, "full_name": c.full_name, "phone_number": c.phone_number,
                "created_at": c.created_at,
            } for c in customers],
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"Database connection error: {e}")

with st.expander("Orders"):
    try:
        session = get_session()
        try:
            orders = session.query(Order).order_by(Order.id.desc()).limit(50).all()
        finally:
            session.close()
        st.dataframe(
            [{
                "id": o.id, "order_number": o.order_number, "customer_name": o.customer_name,
                "phone": o.phone_number, "product_reference": o.product_reference,
                "product_name": o.product_name,
                "status": o.status, "estimated_delivery": o.estimated_delivery,
            } for o in orders],
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"Database connection error: {e}")
