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


def parse_parts_request(message_body: str) -> dict:
    """
    Parse a natural language WhatsApp message into a structured parts request.

    Examples of what technicians send:
    - "need torque converter for nissan patrol y62 2019 urgent by thursday"
    - "brake pads hilux 2020 x4"
    - "looking for alternator for mercedes c200 2017, not urgent"
    - "المحول تبع نيسان باترول ٢٠١٩ ضروري" (Arabic)
    """

    prompt = f"""A technician at an auto workshop sent this WhatsApp message to request a part:
"{message_body}"

Extract the following into JSON. If a field can't be determined, use the default shown.
Respond with ONLY valid JSON. No markdown fences. No explanation.

{{
  "part_description": "<the part they need — be specific>",
  "vehicle_info": "<make, model, year if mentioned, else empty string>",
  "quantity": <number, default 1>,
  "urgency": "<normal or urgent or emergency — based on words like 'urgent', 'asap', 'emergency', 'rush'>",
  "deadline": "<when they need it, as stated, e.g. 'Thursday', 'tomorrow', 'end of week'. empty string if not mentioned>",
  "notes": "<any other relevant details they mentioned, empty string if none>",
  "confidence": <0 to 1, how confident you are this is a valid parts request>
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        return parsed

    except Exception as e:
        print(f"Failed to parse parts request: {e}")
        return {
            "part_description": message_body,  # Fall back to using raw message
            "vehicle_info": "",
            "quantity": 1,
            "urgency": "normal",
            "deadline": "",
            "notes": "Auto-parsed from WhatsApp — may need review",
            "confidence": 0.3,
        }

# --- STANDALONE TEST ---

if __name__ == "__main__":
    print("=" * 60)
    print("Testing SUPPLIER RESPONSE parser...")
    print("=" * 60 + "\n")

    test_messages = [
        "Yes available. QAR 2,800. Can deliver today afternoon",
        "Out of stock bro. Can order from Dubai, 5 days, around 2500",
        "2800",
        "Will check and get back to you",
        "Which model? 4WD or 2WD?",
    ]

    for msg in test_messages:
        print(f"Message: \"{msg}\"")
        classification = classify_message(msg)
        print(f"  Classification: {classification}")
        if classification in ["quote", "unknown"]:
            result = parse_supplier_response(msg, "Torque converter", "Nissan Patrol Y62 2019")
            print(f"  Price: {result.get('price')} {result.get('currency')}")
            print(f"  Availability: {result.get('availability')}")
        print()

    print("\n" + "=" * 60)
    print("Testing PARTS REQUEST parser...")
    print("=" * 60 + "\n")

    request_messages = [
        "need torque converter for nissan patrol y62 2019 urgent by thursday",
        "looking for brake pads toyota hilux 2020 x4",
        "alternator mercedes c200 2017",
        "need oil filter and air filter for land cruiser 2021 not urgent",
        "URGENT transmission fluid pump for audi q7 2018 need it today",
    ]

    for msg in request_messages:
        print(f"Message: \"{msg}\"")
        result = parse_parts_request(msg)
        print(f"  Part: {result.get('part_description')}")
        print(f"  Vehicle: {result.get('vehicle_info')}")
        print(f"  Quantity: {result.get('quantity')}")
        print(f"  Urgency: {result.get('urgency')}")
        print(f"  Deadline: {result.get('deadline')}")
        print(f"  Confidence: {result.get('confidence')}")
        print()