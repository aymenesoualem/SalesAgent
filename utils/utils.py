import requests
import os
def get_digishare_token(client_id, client_secret):
    res = requests.post(
        "https://api.digishare.ma/v1/oauth/token",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret
        }
    )
    res.raise_for_status()
    return res.json()

def create_digishare_ticket(phone_number,customer_name):
    token = os.getenv("DIGISHARE_ACCESS_TOKEN")
    res = requests.post("https://api.digishare.ma/v1/tickets",
            headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            },
            json={
            "type_ticket_id": "az6934k94m5vrxqj",
            "create_third_data":True,
            "source_id": "null",
            "information": {
                "external_id": "55",
                "third": {
                    "name": customer_name,
                    "phone": phone_number
                }
            },
            "subject": "survey histoire d'or 1",
            "creation_mode": "automatically",
            "priority_id": 3,
            "ticket_status_id": "780ew4kx3kdyjpa5",
            "channel_id": "web",
            "tags": []
            }
        )
    return res