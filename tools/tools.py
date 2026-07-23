
from twilio.twiml.voice_response import VoiceResponse

from models.model import Product, Store, Order, SupportTicket, Customer
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Numeric, TIMESTAMP, func
from sqlalchemy.orm import relationship, sessionmaker
import sys
from datetime import date, datetime
import os

from dotenv import load_dotenv
from tavily import TavilyClient
from twilio.rest import Client
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.phone import normalize_phone_number

load_dotenv()

from google.oauth2 import service_account
from googleapiclient.discovery import build

def book_service_appointment(customer_name: str, phone: str, service_type: str, store_city: str, date_str: str, time_str: str):
    """
    Books an in-store service appointment (repair, resizing, engraving, cleaning) and sends an SMS confirmation.

    Args:
        customer_name (str): Name of the customer.
        phone (str): Phone number of the customer.
        service_type (str): Type of service requested (e.g. "Repair", "Resizing", "Engraving", "Cleaning").
        store_city (str): City of the store where the service will take place.
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
            'summary': f"{service_type} - {store_city} ({customer_name})",
            'description': f"Customer: {customer_name}, Phone: {phone}, Service: {service_type}, Store city: {store_city}",
            'start': {'dateTime': start_datetime, 'timeZone': 'Europe/Paris'},
            'end': {'dateTime': end_datetime, 'timeZone': 'Europe/Paris'},
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 60},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }

        event_result = service.events().insert(calendarId=calendar_id, body=event).execute()

        return f"Appointment booked! Event ID: {event_result['id']}"

    except Exception as e:
        return f"Failed to book appointment: {e}"


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


# The agent only handles the Histoire d'Or enseigne, not the rest of THOM Group.
HISTOIRE_DOR_BRAND = "Histoire d'Or"
HISTOIRE_DOR_WEBSITE = "histoiredor.com"


def find_product_by_name(name: str):
    """
    Search the local Histoire d'Or catalog for a product by name using partial match (case-insensitive).
    """
    session = get_session()
    try:
        products = session.query(Product).filter(
            Product.brand.ilike(HISTOIRE_DOR_BRAND),
            Product.name.ilike(f"%{name}%"),
        ).all()
        if not products:
            return f"No products found matching '{name}'."

        product_details = []
        for product in products:
            availability = "In Stock" if product.in_stock else "Out of Stock"
            product_details.append(
                f"ID: {product.id}, Brand: {product.brand}, Name: {product.name}, Category: {product.category}, "
                f"Material: {product.material}, Price: ${product.price}, Status: {availability}"
            )

        return "\n".join(product_details)
    finally:
        session.close()

def get_products_by_category(category: str):
    """
    Retrieve all Histoire d'Or products of a specific category (case-insensitive), e.g. Ring, Necklace, Bracelet, Earrings, Watch.
    """
    session = get_session()
    try:
        products = session.query(Product).filter(
            Product.brand.ilike(HISTOIRE_DOR_BRAND),
            Product.category.ilike(category),
        ).all()
        return [f"{p.brand} - {p.name}" for p in products]
    finally:
        session.close()


def search_product_on_histoire_dor_website(query: str):
    """
    Search histoiredor.com for real-time product information (description, pricing,
    availability) when the local catalog doesn't have what the caller is asking about.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Product search on the website is currently unavailable."

    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            include_domains=[HISTOIRE_DOR_WEBSITE],
            max_results=5,
        )
        results = response.get("results", [])
        if not results:
            return f"No product information found for '{query}' on {HISTOIRE_DOR_WEBSITE}."

        lines = []
        for r in results:
            title = (r.get("title") or "").strip()
            url = r.get("url") or ""
            content = (r.get("content") or "").strip()
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"{title} ({url}): {content}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error searching product on {HISTOIRE_DOR_WEBSITE}: {e}"


def check_order_status(order_number: str):
    """
    Look up an order by its order number and return its current status.
    """
    session = get_session()
    try:
        order = session.query(Order).filter(Order.order_number.ilike(order_number)).first()
        if not order:
            return f"No order found with number '{order_number}'."

        return (
            f"Order {order.order_number} for {order.customer_name}: {order.product_name} "
            f"(Ref: {order.product_reference}) - Status: {order.status}, "
            f"Estimated delivery: {order.estimated_delivery}"
        )
    finally:
        session.close()


def get_orders_by_phone(phone_number: str):
    """
    Look up all known orders placed under a phone number, matched regardless of
    formatting (e.g. '+33...' vs '0033...'). Used to give the agent order context
    up front for a known caller, instead of waiting for them to state an order number.
    """
    session = get_session()
    try:
        normalized = normalize_phone_number(phone_number)
        if not normalized:
            return []
        orders = session.query(Order).filter(Order.phone_number == normalized).all()
        return [
            {
                "order_number": o.order_number,
                "customer_name": o.customer_name,
                "product_reference": o.product_reference,
                "product_name": o.product_name,
                "status": o.status,
                "estimated_delivery": o.estimated_delivery.isoformat() if o.estimated_delivery else None,
            }
            for o in orders
        ]
    finally:
        session.close()


def find_store_by_city(city: str):
    """
    Retrieve Histoire d'Or store details (name, address, phone, opening hours) for a given city.
    """
    session = get_session()
    try:
        stores = session.query(Store).filter(
            Store.name.ilike(f"{HISTOIRE_DOR_BRAND}%"),
            Store.city.ilike(f"%{city}%"),
        ).all()
        if not stores:
            return f"No stores found in '{city}'."

        store_details = []
        for store in stores:
            store_details.append(
                f"{store.name} - {store.address}, Phone: {store.phone}, Hours: {store.opening_hours}"
            )

        return "\n".join(store_details)
    finally:
        session.close()


# Logging a support ticket with a call summary
def log_support_ticket(full_name, phone_number, issue_type, priority, summary):
    session = get_session()
    try:
        ticket = SupportTicket(
            name=full_name,
            phone_number=phone_number,
            issue_type=issue_type,
            priority=priority,
            summary=summary
        )
        session.add(ticket)
        session.commit()
        return f"Support ticket for {full_name} logged."
    except Exception as e:
        session.rollback()
        return f"Error: {e}"
    finally:
        session.close()

# Registering a new customer, or looking one up by phone number for an incoming call
def add_customer(full_name, phone_number):
    session = get_session()
    try:
        normalized = normalize_phone_number(phone_number)
        existing = session.query(Customer).filter(
            Customer.phone_number == normalized,
            Customer.full_name.ilike(full_name)
        ).first()
        if existing:
            return f"Customer {full_name} is already registered."

        customer = Customer(full_name=full_name, phone_number=normalized)
        session.add(customer)
        session.commit()
        return f"Customer {full_name} added."
    except Exception as e:
        session.rollback()
        return f"Error: {e}"
    finally:
        session.close()


def get_customer_by_phone(phone_number: str):
    """
    Look up known customers registered under a phone number, matched regardless of
    formatting (e.g. '+33...' vs '0033...'). A phone number can be shared by more
    than one known customer (e.g. a household line), so this returns a list.
    """
    session = get_session()
    try:
        normalized = normalize_phone_number(phone_number)
        if not normalized:
            return []
        customers = session.query(Customer).filter(Customer.phone_number == normalized).all()
        return [{"full_name": c.full_name, "phone_number": c.phone_number} for c in customers]
    finally:
        session.close()


def hangup():
    response = VoiceResponse()
    response.hangup()
    return response
def get_session():
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://agent:sales@localhost:5432/ThomGroupSupport_db")
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return Session()

if __name__ == '__main__':
    # Test: Search product by name
    print("\nTesting find_product_by_name:")
    products_named = find_product_by_name("Ring")
    print(products_named)

    # Test: Search products by category
    print("\nTesting get_products_by_category:")
    products_of_category = get_products_by_category("Ring")
    for product in products_of_category:
        print(product)
