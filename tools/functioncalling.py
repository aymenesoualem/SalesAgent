import asyncio
import inspect
import os
from datetime import date

from tools.tools import (
    hangup,
    log_support_ticket,
    find_product_by_name,
    get_products_by_category,
    check_order_status,
    find_store_by_city,
    book_service_appointment,
    add_customer,
    search_product_on_histoire_dor_website,
)



def log_support_ticket_function(full_name, phone_number, issue_type, priority, summary):
    """
    Use this function whenever a caller's issue could not be fully resolved on the call, or needs follow-up.
    Pass in the customer's full name, phone number, the type of issue (e.g. "Order Issue", "Product Question",
    "Repair", "Complaint", "Other"), a priority score from 1 (low) to 5 (high) indicating urgency,
    and a brief summary of what was discussed.
    This will save the ticket to the support system for follow-up.
    :param full_name:
    :param phone_number:
    :param issue_type:
    :param priority:
    :param summary:
    :return:
    """
    return log_support_ticket(full_name, phone_number, issue_type, priority, summary)
def find_product_by_name_function(name:str):
    """Use this function to look up a product by name from the catalog."""
    return find_product_by_name(name=name)

def find_products_by_category_function(category:str):
    """Use this function to retrieve a list of products of a specific category (e.g. Ring, Necklace, Bracelet, Earrings, Watch) from the catalog."""
    return get_products_by_category(category=category)

def check_order_status_function(order_number: str):
    """Use this function to check the status of a customer's order by its order number."""
    return check_order_status(order_number=order_number)

def find_store_by_city_function(city: str):
    """Use this function to find store locations, addresses, phone numbers, and opening hours in a given city."""
    return find_store_by_city(city=city)

def search_product_on_histoire_dor_website_function(query: str):
    """
    Use this function to search histoiredor.com for up-to-date product information
    (description, pricing, availability) when the local catalog doesn't have what the
    caller is asking about, or when they want details beyond what the catalog holds.
    """
    return search_product_on_histoire_dor_website(query)

def add_customer_function(full_name: str, phone_number: str):
    """
    Use this function to register a new customer (full name + phone number) the first
    time you learn who is calling from a number that isn't already known in the system,
    so they're recognized automatically on future calls.
    """
    return add_customer(full_name, phone_number)

def book_service_appointment_function(customer_name, phone, service_type: str, store_city: str, date_str: str, time_str: str):
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

        return book_service_appointment(customer_name, phone, service_type, store_city, date_str, time_str)

async def hangup_function(websocket):
    """
    Gracefully closes the WebSocket connection with a slight delay.
    """
    await asyncio.sleep(2)  # Wait 1.5 seconds before closing
    await websocket.close(code=1000, reason="Call ended by assistant.")


def send_whatsapp_form_function(call_context, send_whatsapp_form: bool, phone_number: str, customer_name: str):
    """
    Use this once the caller has clearly answered yes or no to receiving a short customer
    satisfaction survey by WhatsApp after the call. Ask for and confirm their WhatsApp phone
    number yourself before calling this - don't assume the caller ID is correct or complete.
    :param send_whatsapp_form: True if the caller agreed to receive the survey, False if they declined.
    :param phone_number: The caller's confirmed WhatsApp phone number.
    :param customer_name: The caller's full name.
    """
    call_context.pending_whatsapp_form = {
        "phone_number": phone_number,
        "customer_name": customer_name,
    } if send_whatsapp_form else None
    return "Survey queued for delivery after the call." if send_whatsapp_form else "Survey declined."


def function_to_schema(func) -> dict:
    """
    Converts a Python function's signature into a JSON schema format.

    Args:
        func: The Python function to convert into a JSON schema.

    Returns:
        dict: A JSON schema describing the function.
    """
    # Map Python types to JSON Schema types
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
        type(None): "null",
        date: "string",  # Represent date as a string in ISO 8601 format
    }

    try:
        signature = inspect.signature(func)
    except ValueError:
        raise ValueError(f"Failed to get signature for function {func.__name__}.")

    # Extract parameter properties
    properties = {}
    required = []
    for param in signature.parameters.values():
        annotation = param.annotation
        param_type = type_map.get(annotation, "string")  # Default to "string" if unknown
        properties[param.name] = {"type": param_type}

        # Add a format for date type
        if annotation == date:
            properties[param.name]["format"] = "date"

        # Add to required list if no default value is provided
        if param.default is inspect.Parameter.empty:
            required.append(param.name)

    return {
        "type": "function",
        "name": func.__name__,
        "description": (func.__doc__ or "").strip(),
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }

async def invoke_function(function_name, arguments, websocket=None):
    """
    Dynamically invokes a function by name with the given arguments.
    Optionally injects the websocket (call context) for special functions like
    hangup_function and send_whatsapp_form_function.
    """
    try:
        # Map function names to actual functions
        function_map = {
            "find_products_by_category_function": find_products_by_category_function,
            "hangup_function": hangup_function,
            "log_support_ticket_function": log_support_ticket_function,
            "find_product_by_name_function": find_product_by_name_function,
            "check_order_status_function": check_order_status_function,
            "find_store_by_city_function": find_store_by_city_function,
            "book_service_appointment_function": book_service_appointment_function,
            "add_customer_function": add_customer_function,
            "search_product_on_histoire_dor_website_function": search_product_on_histoire_dor_website_function,
            "send_whatsapp_form_function": send_whatsapp_form_function,
        }

        if function_name not in function_map:
            print(f"Function {function_name} is not recognized.")
            return None

        func = function_map[function_name]

        # Special case for hangup: inject websocket directly
        if function_name == "hangup_function":
            if websocket:
                await func(websocket)
            else:
                print("WebSocket required for hangup_function.")
            return None

        # Special case: inject the call context, ignore whatever the model passed for it
        if function_name == "send_whatsapp_form_function":
            arguments.pop("call_context", None)
            if not websocket:
                print("Call context required for send_whatsapp_form_function.")
                return None
            return func(websocket, **arguments)

        # Standard function call
        result = await func(**arguments) if inspect.iscoroutinefunction(func) else func(**arguments)
        print(f"Function {function_name} invoked successfully with result: {result}")
        return result

    except Exception as e:
        print(f"Error invoking function {function_name}: {e}")
        return None

inbound_support_tools = [
    log_support_ticket_function,
    find_product_by_name_function,
    find_products_by_category_function,
    check_order_status_function,
    find_store_by_city_function,
    book_service_appointment_function,
    add_customer_function,
    search_product_on_histoire_dor_website_function,
    send_whatsapp_form_function,
    hangup_function,
]
inbound_support_tool_schemas = [function_to_schema(tool) for tool in inbound_support_tools]
