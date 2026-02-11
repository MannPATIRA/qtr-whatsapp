"""
AI-powered parser for supplier WhatsApp responses.
Uses Claude to extract structured data from messy natural language.
"""

import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def parse_supplier_response(message_body: str, part_description: str,
                            vehicle_info: str = "", quantity: int = 1) -> dict:
    """
    Parse a supplier's WhatsApp reply into structured quote data.

    Examples of what suppliers send:
    - "Yes available. QAR 2,800. Can deliver today afternoon"
    - "Out of stock bro. Can order from Dubai, 5 days, around 2500"
    - "2800" (just a price, nothing else)
    - "Will check and get back to you"
    - "نعم متوفر ٢٨٠٠ ريال" (Arabic)
    """

    prompt = f"""You are parsing a supplier's WhatsApp reply to an auto parts inquiry.

The original inquiry was for:
- Part: {part_description}
- Vehicle: {vehicle_info}
- Quantity: {quantity}

The supplier replied with this message:
"{message_body}"

Extract the following. If a field cannot be determined, set it to null.
Respond with ONLY valid JSON. No markdown fences. No explanation.

{{
  "price": null or number (unit price as plain number, no currency symbol),
  "currency": "QAR" or "AED" or "USD" (default "QAR" if ambiguous),
  "availability": "in_stock" or "out_of_stock" or "can_order" or "checking" or "discontinued",
  "delivery_days": null or number (0 = same day, 1 = tomorrow, etc),
  "shipping_cost": null or number (only if mentioned separately),
  "condition": null or string (e.g. "genuine", "aftermarket", "OEM", or brand name),
  "notes": null or string (any other relevant info),
  "is_quote": true or false (true if they gave a price or availability, false if just acknowledging),
  "confidence": number 0 to 1 (how confident you are in this parse)
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text.strip()
        # Clean markdown fences if present
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)

        # Calculate total price
        if parsed.get("price") and parsed.get("shipping_cost"):
            parsed["total_price"] = parsed["price"] + parsed["shipping_cost"]
        else:
            parsed["total_price"] = parsed.get("price")

        return parsed

    except json.JSONDecodeError as e:
        print(f"Failed to parse AI response as JSON: {e}")
        return {
            "price": None, "currency": None, "availability": None,
            "delivery_days": None, "shipping_cost": None, "condition": None,
            "notes": message_body, "is_quote": False, "confidence": 0.0,
            "total_price": None
        }
    except Exception as e:
        print(f"AI parsing error: {e}")
        return {
            "price": None, "currency": None, "availability": None,
            "delivery_days": None, "shipping_cost": None, "condition": None,
            "notes": f"Parse error: {str(e)}", "is_quote": False, "confidence": 0.0,
            "total_price": None
        }


def classify_message(message_body: str) -> str:
    """
    Classify what type of message a supplier sent.
    Returns: "quote", "question", "acknowledgment", "unknown"
    """
    prompt = f"""A supplier replied to an auto parts inquiry with this message:
"{message_body}"

Classify this as exactly one of:
- "quote" (they gave a price, availability, or both)
- "question" (they're asking for clarification, e.g. "which model?", "4WD or 2WD?")
- "acknowledgment" (they're saying they'll check, e.g. "ok will check", "give me 10 minutes")
- "unknown" (can't tell)

Respond with just the single word."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip().lower().strip('"')
    except Exception:
        return "unknown"


# --- STANDALONE TEST ---

if __name__ == "__main__":
    print("Testing AI parser with sample supplier responses...\n")

    test_messages = [
        "Yes available. QAR 2,800. Can deliver today afternoon",
        "Out of stock bro. Can order from Dubai, 5 days, around 2500",
        "I have this. 2200 QAR plus 300 shipping. 3 days delivery. Original Jatco",
        "2800",
        "Will check and get back to you",
        "Which model? 4WD or 2WD?",
        "Discontinued. But we have aftermarket for 1800",
    ]

    for msg in test_messages:
        print(f"Message: \"{msg}\"")

        # Classify first
        classification = classify_message(msg)
        print(f"  Classification: {classification}")

        # Parse if it's a quote
        if classification in ["quote", "unknown"]:
            result = parse_supplier_response(msg, "Torque converter", "Nissan Patrol Y62 2019")
            print(f"  Price: {result.get('price')} {result.get('currency')}")
            print(f"  Availability: {result.get('availability')}")
            print(f"  Delivery: {result.get('delivery_days')} days")
            print(f"  Confidence: {result.get('confidence')}")
        print()