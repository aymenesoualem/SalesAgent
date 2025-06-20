import streamlit as st
import requests

API_URL = "http://localhost:5050/leads"  # Update this if your FastAPI server is hosted elsewhere

st.set_page_config(page_title="AutoLux Leads", layout="wide")

st.title("📞 AutoLux Sales Leads")

try:
    response = requests.get(API_URL)
    response.raise_for_status()
    leads = response.json()

    if leads:
        st.success(f"Fetched {len(leads)} lead(s) from the database.")
        st.dataframe(leads, use_container_width=True)
    else:
        st.info("No leads found.")
except requests.exceptions.RequestException as e:
    st.error(f"Failed to fetch leads: {e}")
