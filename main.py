import os
from datetime import date
from typing import Optional, List
import psycopg2
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.params import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, joinedload
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
from agents.agent import  handle_call
from models.model import Lead
from tools.functioncalling import inbound_caller_tool_schemas

load_dotenv()
PORT = int(os.getenv("PORT", 5050))

SHOW_TIMING_MATH = False
app = FastAPI()
class Booking(BaseModel):
    id: str
    customer_name: str
    room_number: str
    check_in_date: date
    check_out_date: date
    phone_number: str
    feedback: str

    class Config:
        from_attributes = True



app = FastAPI()

# Database configuration
DATABASE_URL = "postgresql://agent:sales@localhost:5432/CarDealership_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
class LeadSchema(BaseModel):
    id: int
    name: str
    phone_number: str
    lead_source: Optional[str]
    interest_score: int
    call_summary: Optional[str]

    class Config:
        from_attributes = True


@app.get("/leads", response_model=List[dict])
def get_leads():
    try:
        # Establish database connection
        connection = get_db_connection()
        cursor = connection.cursor()

        # SQL query to get lead details
        query = """
        SELECT 
            id,
            name,
            phone_number,
            lead_source,
            interest_score,
            call_summary
        FROM leads
        order by interest_score desc;
        """

        # Execute query
        cursor.execute(query)
        result = cursor.fetchall()

        # Format the result
        leads = []
        for row in result:
            leads.append({
                "id": row[0],
                "name": row[1],
                "phone_number": row[2],
                "lead_source": row[3],
                "interest_score": row[4],
                "call_summary": row[5]
            })

        cursor.close()
        connection.close()

        if not leads:
            raise HTTPException(status_code=404, detail="No leads found!")

        return JSONResponse(content=leads)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching leads: {e}")

# Dependency to get the DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


from fastapi.logger import logger


from typing import List

# Database connection function using psycopg2
def get_db_connection():
    try:
        connection = psycopg2.connect(DATABASE_URL)
        return connection
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {e}")


@app.get("/",response_class=JSONResponse)
async def index_page():
    return {"message":"Server is running"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    # Get the caller's phone number from the "From" parameter
    # Read the form data from the incoming request
    form = await request.form()

    # Extract caller's phone number (From) and other parameters
    from_number = form.get("From")  # Caller’s phone number
    to_number = form.get("To")  # Twilio phone number
    call_sid = form.get("CallSid")  # Unique identifier for the call

    # Log the caller's phone number for debugging purposes
    print(f"Call received from: {from_number}")
    print(f"Call SID: {call_sid}")
    print(f"Twilio number: {to_number}")
    response = VoiceResponse()
    # <Say> punctuation to improve text-to-speech flow
    response.say("Hello since there is no available in the dealership right now, we're connecting to our AI agent Andy.")
    response.pause(length=1)
    response.say("Andy is on the phone!")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream/{from_number}')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream/{customer_number}")
async def handle_media_stream(websocket: WebSocket,customer_number: str):
    system_message = """
    You are a professional and engaging AI assistant working as a sales agent for AutoLux, a car dealership. Your mission is to guide callers through their car buying journey by answering their questions, offering recommendations, helping them book test drives, and recording potential leads for follow-up.

    ### Car Sales Services
    - Respond to customer inquiries about specific cars or types of vehicles.
    - Offer detailed availability and pricing information based on user input.
    - Help customers explore their options by suggesting models that fit their needs.
    - Offer to **book a test drive** if the customer seems interested in a vehicle.
    - End each call by capturing qualified leads into the system if the user shows any interest.
    - Make sure to take the customer's full name.

    ### Tools and Usage

    You have access to the following tools to support your tasks:

    1. **`find_car_by_model_function`**
       - Use this if the caller mentions a specific car by model name (e.g., “Do you have a C Class?”).

    2. **`find_cars_by_type_function`**
       - Use this when the caller is looking for a general category like SUV, sedan, electric, hybrid, or luxury cars.

    3. **`log_lead_with_call_summary_function`**
       - Always use this at the **end of a call** if the caller showed any interest in a car, 
       and after you have provided enough detail.
       - Collect and pass:
         - Full name
         - Phone number which is """ + customer_number + """ (No need to ask the customer for this)
         - Lead source (e.g., "Website", "Referral", "Instagram Ad")
         - Interest score from 1 (low) to 5 (high)
         - A concise summary of what was discussed
       - This ensures the lead is saved into the CRM system for follow-up.

    4. **`book_test_drive_function`**
       - Use this if the customer wants to try a car in person.
       - Ask for:
         - Customer’s full name
         - Desired car model
         - Preferred date and time for the test drive
       - The system will confirm the booking and send the customer a confirmation SMS.

    5. **`hangup_function`**
       - Use this once the conversation is over and there is nothing else to assist the caller with.

    ### Caller Interaction
    - Greet the caller politely and professionally.
    - If not already known, ask for their full name and how they heard about AutoLux.
    - If they express interest in a vehicle, remember to:
      - Confirm the vehicle’s availability using the proper tool.
      - Offer to book a test drive using `book_test_drive_function`.
      - Close by logging their details with `log_lead_with_call_summary_function`.

    ### Tone and Approach
    - Stay friendly, focused, and informative.
    - Avoid technical jargon unless the caller asks for it.
    - Guide the customer like a knowledgeable dealership assistant, with the goal of helping them find a vehicle, book a test drive, and log them as a potential lead.

    When the conversation ends, always call `hangup_function`.
    """

    initial_message = """Greet the caller to the car dealership that's called LuxAuto, say hey I'm Andy then greet the saying 
    that since the other salesmen are full you're taking his call """


    await handle_call(websocket,system_message,initial_message,inbound_caller_tool_schemas)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
