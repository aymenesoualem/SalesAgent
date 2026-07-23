import re


def normalize_phone_number(phone: str) -> str:
    """Normalize a phone number to a bare digit string with no international prefix,
    so numbers like '+33786775314' and '0033786775314' compare equal regardless of
    how the caller ID or the caller themselves formatted it."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00"):
        digits = digits[2:]
    return digits
