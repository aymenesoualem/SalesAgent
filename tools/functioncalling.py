import asyncio
import inspect
import os
from datetime import date

from tools.tools import hangup, log_lead_with_call_summary, find_car_by_model, get_cars_by_type, book_test_drive


def log_lead_with_call_summary_function(full_name, phone_number, lead_source, interest_score, call_summary):
    """
    Use this function whenever you finish a call with a potential buyer.
    Pass in the lead’s full name, phone number, the ID of the car they’re interested in,
     how they found us (e.g. "Website", "Referral"), a score from 1 to 5 indicating their interest level,
     and a brief summary of what they said during the call.
     This will save the lead and their call summary to the database for future follow-up. as lead with the car_id the in
    :param full_name:
    :param phone_number:
    :param lead_source:
    :param interest_score:
    :param call_summary:
    :return:
    """
    return log_lead_with_call_summary(full_name, phone_number, lead_source, interest_score, call_summary)
def find_car_by_model_function(model:str):
    """Use this function to retrieve a car by model name from the Database."""
    return find_car_by_model(model=model)

def find_cars_by_type_function(car_type:str):
    """Use this function to retrieve a list of car of a specific type from the Database."""
    return get_cars_by_type(car_type=car_type)
def book_test_drive_function(customer_name, phone, car_model: str, date_str: str, time_str: str):
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

        return book_test_drive(customer_name,phone,car_model,date_str,time_str)

async def hangup_function(websocket):
    """
    Gracefully closes the WebSocket connection with a slight delay.
    """
    await asyncio.sleep(2)  # Wait 1.5 seconds before closing
    await websocket.close(code=1000, reason="Call ended by assistant.")


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
    Optionally injects the websocket for special functions like hangup.
    """
    try:
        # Map function names to actual functions
        function_map = {
            "find_cars_by_type_function": find_cars_by_type_function,
            "hangup_function": hangup_function,
            "log_lead_with_call_summary_function": log_lead_with_call_summary_function,
            "find_car_by_model_function": find_car_by_model_function,
            "book_test_drive_function": book_test_drive_function,
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

        # Standard function call
        result = await func(**arguments) if inspect.iscoroutinefunction(func) else func(**arguments)
        print(f"Function {function_name} invoked successfully with result: {result}")
        return result

    except Exception as e:
        print(f"Error invoking function {function_name}: {e}")
        return None

inbound_caller_tools = [log_lead_with_call_summary_function,find_car_by_model_function,find_cars_by_type_function,hangup_function,book_test_drive_function]
inbound_caller_tool_schemas = [function_to_schema(tool) for tool in inbound_caller_tools]

