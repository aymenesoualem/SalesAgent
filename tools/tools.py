
from twilio.twiml.voice_response import VoiceResponse

from models.model import Lead, Car
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Numeric, Boolean, TIMESTAMP, func
from sqlalchemy.orm import relationship, sessionmaker
import sys
from datetime import date, datetime
import os

from dotenv import load_dotenv
from tavily import TavilyClient
from twilio.rest import Client
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from google.oauth2 import service_account
from googleapiclient.discovery import build

def book_test_drive(customer_name: str, phone: str, car_model: str, date_str: str, time_str: str):
    """
    Books a test drive for a customer and sends an SMS confirmation.

    Args:
        customer_name (str): Name of the customer.
        phone (str): Phone number of the customer.
        car_model (str): Car model for the test drive.
        date_str (str): Date in format YYYY-MM-DD.
        time_str (str): Time in format HH:MM (24-hour).

    Returns:
        str: Confirmation message or error.
    """

    try:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_PATH, scopes=SCOPES
        )
        # Create calendar API service
        service = build('calendar', 'v3', credentials=credentials)
        calendar_id = '66950f8e74c760d598371446fb2531d37ba1937b2b0c38184d67923963adb81c@group.calendar.google.com'  # or use a static ID

        # Build datetime object for event
        start_datetime = f"{date_str}T{time_str}:00"
        end_datetime = f"{date_str}T{time_str[:-2]}{int(time_str[-2:]) + 30:02d}:00"  # 30-min slot

        event = {
            'summary': f"Test Drive - {car_model} ({customer_name})",
            'description': f"Customer: {customer_name}, Phone: {phone}, Car: {car_model}",
            'start': {'dateTime': start_datetime, 'timeZone': 'Africa/Casablanca'},
            'end': {'dateTime': end_datetime, 'timeZone': 'Africa/Casablanca'},
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 60},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }

        event_result = service.events().insert(calendarId=calendar_id, body=event).execute()

        # Send SMS confirmation

        return f"Test drive booked! Event ID: {event_result['id']}"

    except Exception as e:
        return f"Failed to book test drive: {e}"


def send_sms(to: str, body: str):
    """Send an SMS using Twilio."""
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    from_number = os.getenv('TWILIO_FROM_NUMBER')
    # Initialize Twilio client
    client = Client(account_sid, auth_token)

    # Send SMS
    message = client.messages.create(
        body=body,  # SMS body/content
        from_=from_number,  # Your Twilio phone number
        to=to  # Recipient phone number
    )

    # Print message SID (optional for tracking)
    print(f"Message SID: {message.sid}")

    return message.sid  # Return the SID of the sent message for reference

# if __name__ == '__main__':
#     send_sms("+212679675314","Hi")
#     result = web_scraper_for_recommendation("Nice things to do in casa")
#     print (result)


def find_car_by_model(model: str):
    """
    Search for a car by name using partial match (case-insensitive).
    """
    session = get_session()
    try:
        cars = session.query(Car).filter(Car.model.ilike(f"%{model}%")).all()
        if not cars:
            return f"No cars found matching '{model}'."

        car_details = []
        for car in cars:
            availability = "Available" if car.available else "Not Available"
            car_details.append(
                f"ID: {car.id}, Make: {car.make}, Model: {car.model}, Year: {car.year}, "
                f"Type: {car.type}, Price: ${car.price}, Status: {availability}"
            )

        return "\n".join(car_details)
    finally:
        session.close()
def get_cars_by_type(car_type: str):
    """
    Retrieve all cars of a specific type (case-insensitive).
    """
    session = get_session()
    try:
        cars = session.query(Car).filter(Car.type.ilike(car_type)).all()
        return [car.model for car in cars]
    finally:
        session.close()

# Logging a lead with a call summary
def log_lead_with_call_summary(full_name, phone_number, lead_source, interest_score, call_summary):
    session = get_session()
    try:
        lead = Lead(
            name=full_name,
            phone_number=phone_number,
            lead_source=lead_source,
            interest_score=interest_score,
            call_summary=call_summary
        )
        session.add(lead)
        session.commit()
        return f"Lead for {full_name} logged."
    except Exception as e:
        session.rollback()
        return f"Error: {e}"
    finally:
        session.close()

def hangup():
    response = VoiceResponse()
    response.hangup()
    return response
def get_session():
    DATABASE_URL = "postgresql://agent:sales@localhost:5432/CarDealership_db"
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return Session()

if __name__ == '__main__':
    # Test: Log a lead

    # Test: Search car by name
    print("\nTesting find_car_by_name:")
    cars_named = find_car_by_model("Toyota", get_session)
    for car in cars_named:
        print(car)

    # Test: Search car by type
    print("\nTesting get_cars_by_type:")
    cars_of_type = get_cars_by_type("Sedan", get_session)
    for car in cars_of_type:
        print(car)



