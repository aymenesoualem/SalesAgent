import streamlit as st
import requests

API_URL = "http://localhost:5050/support-tickets"  # Update this if your FastAPI server is hosted elsewhere

st.set_page_config(page_title="Histoire d'Or Support Tickets", layout="wide")

st.title("📞 Histoire d'Or Support Tickets")

try:
    response = requests.get(API_URL)
    response.raise_for_status()
    tickets = response.json()

    if tickets:
        st.success(f"Fetched {len(tickets)} ticket(s) from the database.")
        st.dataframe(tickets, use_container_width=True)
    else:
        st.info("No support tickets found.")
except requests.exceptions.RequestException as e:
    st.error(f"Failed to fetch support tickets: {e}")
