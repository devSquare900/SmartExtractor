import re
from datetime import datetime

DAY_FIRST_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y",
    "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y",
]
MONTH_FIRST_FORMATS = [
    "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y",
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y",
]
UNAMBIGUOUS_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%d %B %Y", "%d %b %Y", "%d-%b-%Y", "%d-%B-%Y", "%d %b, %Y", "%d %B, %Y",
    "%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y",
]

CURRENCY_TOKENS = {
    "PKR": "PKR", "RS": "PKR", "RS.": "PKR", "USD": "USD", "US$": "USD", "$": "USD",
    "EUR": "EUR", "€": "EUR", "GBP": "GBP", "£": "GBP", "AED": "AED", "SAR": "SAR", "INR": "INR", "₹": "INR",
}


def normalize_date(text: str, date_order: str = "DMY"):
    """Returns the date as YYYY-MM-DD, or None if it cannot be parsed."""
    if not text:
        return None
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:")

    ordered = DAY_FIRST_FORMATS if date_order.upper() == "DMY" else MONTH_FIRST_FORMATS
    for fmt in UNAMBIGUOUS_FORMATS + ordered:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_amount(text: str):
    """Returns (amount as '1234.50', currency code or None). Amount is None if no number is found."""
    if not text:
        return None, None

    currency = None
    upper = text.upper()
    for token, code in CURRENCY_TOKENS.items():
        if re.search(r"(?<![A-Z])" + re.escape(token) + r"(?![A-Z])", upper):
            currency = code
            break

    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text.replace(" ", ""))
    if not match:
        return None, currency
    number = match.group(0).replace(",", "")
    try:
        return f"{float(number):.2f}", currency
    except ValueError:
        return None, currency


def apply_normalization(field: dict, field_type: str, date_order: str = "DMY") -> dict:
    """Adds 'normalized' (and 'currency' for amounts) to a field dict in place."""
    if not field:
        return field
    field.pop("normalized", None)
    field.pop("currency", None)
    value = field.get("value") or ""
    if field_type == "date":
        normalized = normalize_date(value, date_order)
        if normalized:
            field["normalized"] = normalized
    elif field_type == "amount":
        amount, currency = normalize_amount(value)
        if amount:
            field["normalized"] = amount
        if currency:
            field["currency"] = currency
    return field
