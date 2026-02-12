"""
Message Router
Decides what an incoming WhatsApp message is:
- A new parts request from a technician
- A supplier response to an RFQ
- Something else

In PRODUCTION, routing is simple: look up the phone number.
  - Phone belongs to a user (technician/buyer) → parts request
  - Phone belongs to a supplier with open RFQs → supplier response

In SANDBOX TESTING, everyone uses the same phone number, so we
also use keyword detection and context (are there open RFQs?).
"""

from database import SessionLocal, User, Supplier, RFQ
from anthropic import Anthropic
from dotenv import load_dotenv
import os
import json

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# Keywords that strongly suggest a parts request (not a quote)
REQUEST_KEYWORDS = [
    "need", "request", "order", "looking for", "require",
    "can you find", "get me", "i need", "we need", "parts for",
    "please arrange", "source", "procure",
]


def route_message(from_number: str, message_body: str) -> dict:
    """
    Determine what an incoming message is and how to handle it.

    Returns:
        {
            "type": "parts_request" | "supplier_response" | "status_inquiry" | "unknown",
            "user_id": str or None,       # If it's from a known user
            "supplier_id": str or None,    # If it's from a known supplier
            "company_id": str or None,
            "has_open_rfq": bool,          # Whether this sender has an open RFQ
        }
    """
    db = SessionLocal()
    clean_number = from_number.replace("whatsapp:", "").strip()

    # Look up the sender in both tables
    user = db.query(User).filter(User.phone == clean_number).first()
    supplier = db.query(Supplier).filter(Supplier.phone == clean_number).first()

    # Check if there are open RFQs for this phone number (as a supplier)
    open_rfq = None
    if supplier:
        open_rfq = db.query(RFQ).filter(
            RFQ.supplier_id == supplier.id,
            RFQ.status == "sent",
        ).order_by(RFQ.sent_at.desc()).first()

    has_open_rfq = open_rfq is not None

    db.close()

    # --- ROUTING DECISION ---

    body_lower = message_body.lower().strip()

    # Check 1: Does the message start with a request keyword?
    is_request_by_keyword = any(body_lower.startswith(kw) for kw in REQUEST_KEYWORDS)

    # Check 2: Does the message look like a status inquiry?
    is_status_inquiry = any(phrase in body_lower for phrase in [
        "status", "update on", "where is", "what happened", "any update",
        "how is my", "tracking",
    ])

    # SCENARIO A: Clear parts request (keyword match)
    if is_request_by_keyword:
        return {
            "type": "parts_request",
            "user_id": user.id if user else None,
            "supplier_id": None,
            "company_id": user.company_id if user else (supplier.company_id if supplier else None),
            "has_open_rfq": has_open_rfq,
        }

    # SCENARIO B: Status inquiry
    if is_status_inquiry:
        return {
            "type": "status_inquiry",
            "user_id": user.id if user else None,
            "supplier_id": supplier.id if supplier else None,
            "company_id": user.company_id if user else None,
            "has_open_rfq": has_open_rfq,
        }

    # SCENARIO C: There's an open RFQ waiting → this is probably a supplier response
    if has_open_rfq:
        return {
            "type": "supplier_response",
            "user_id": user.id if user else None,
            "supplier_id": supplier.id if supplier else None,
            "company_id": supplier.company_id if supplier else None,
            "has_open_rfq": True,
        }

    # SCENARIO D: No open RFQ, known user → probably a parts request
    if user:
        return {
            "type": "parts_request",
            "user_id": user.id,
            "supplier_id": None,
            "company_id": user.company_id,
            "has_open_rfq": False,
        }

    # SCENARIO E: No open RFQ, not a known user → use AI to classify
    msg_type = ai_classify_intent(message_body)
    return {
        "type": msg_type,
        "user_id": None,
        "supplier_id": supplier.id if supplier else None,
        "company_id": None,
        "has_open_rfq": False,
    }


def ai_classify_intent(message_body: str) -> str:
    """
    Use Claude to classify whether a message is a parts request or something else.
    Only called when keyword + database lookups are ambiguous.
    """
    prompt = f"""A WhatsApp message was received by a procurement system for an auto workshop.
Classify this message as exactly one of:
- "parts_request" — someone is asking for a part to be sourced/ordered
- "supplier_response" — someone is replying with a price, availability, or quote
- "unknown" — can't determine

Message: "{message_body}"

Respond with just the classification word, nothing else."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip().lower().strip('"')
    except Exception:
        return "unknown"


# --- STANDALONE TEST ---

if __name__ == "__main__":
    test_messages = [
        ("need torque converter for patrol 2019 urgent", "Should be: parts_request"),
        ("looking for brake pads toyota hilux 2020", "Should be: parts_request"),
        ("2800 available today", "Should be: supplier_response (if open RFQ)"),
        ("Yes in stock. QAR 1500", "Should be: supplier_response (if open RFQ)"),
        ("what's the status on my order?", "Should be: status_inquiry"),
        ("hello", "Should be: unknown"),
    ]

    print("Testing message router...\n")
    print("NOTE: Without open RFQs in the DB, supplier responses may route differently.\n")

    for msg, expected in test_messages:
        result = route_message("whatsapp:+447XXXXXXXXX", msg)  # Use your number
        print(f"Message: \"{msg}\"")
        print(f"  Routed as: {result['type']}")
        print(f"  Expected:  {expected}")
        print()