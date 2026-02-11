import os
import json
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

class WhatsAppService:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
        self.client = Client(self.account_sid, self.auth_token)

    def send_message(self, to_number: str, body: str) -> dict:
        """
        Send a free-form WhatsApp message.
        Only works if the recipient has messaged you within the last 24 hours
        (the 'customer service window'), OR if you're using the sandbox
        and the recipient has joined your sandbox.
        """
        # Make sure the number has the whatsapp: prefix
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

        message = self.client.messages.create(
            body=body,
            from_=self.from_number,
            to=to_number
        )

        return {
            "sid": message.sid,
            "status": message.status,
            "to": message.to,
            "body": body,
        }

    def send_rfq(self, to_number: str, company_name: str, part_description: str,
                 vehicle_info: str, quantity: int, deadline: str) -> dict:
        """
        Send an RFQ message to a supplier.

        NOTE: In the sandbox, we can only send free-form messages (within the
        24hr window) OR use Twilio's pre-approved templates. For testing,
        we'll use free-form messages. In production, you'd use a custom
        template with content_sid.
        """
        body = (
            f"Good morning. This is a parts inquiry from {company_name}.\n\n"
            f"Part: {part_description}\n"
            f"Vehicle: {vehicle_info}\n"
            f"Quantity: {quantity}\n"
            f"Needed by: {deadline}\n\n"
            f"Please reply with your price and availability. Thank you."
        )

        return self.send_message(to_number, body)

    def send_po_confirmation(self, to_number: str, company_name: str,
                              po_number: str, part_description: str,
                              price: str, currency: str, delivery_date: str) -> dict:
        """Send a PO confirmation to the winning supplier."""
        body = (
            f"Order confirmed from {company_name}.\n\n"
            f"PO: {po_number}\n"
            f"Part: {part_description}\n"
            f"Price: {price} {currency}\n"
            f"Delivery by: {delivery_date}\n\n"
            f"Please confirm receipt of this order. Thank you."
        )

        return self.send_message(to_number, body)

    def send_decline(self, to_number: str, part_description: str) -> dict:
        """Thank a supplier who didn't win the RFQ."""
        body = (
            f"Thank you for your quote on our recent inquiry ({part_description}). "
            f"We have placed this order with another supplier. "
            f"We appreciate your time and will be in touch with future inquiries."
        )

        return self.send_message(to_number, body)

    def send_delivery_followup(self, to_number: str, company_name: str,
                                po_number: str, part_description: str) -> dict:
        """Ask supplier about delivery status."""
        body = (
            f"Hi, this is a delivery reminder from {company_name}.\n\n"
            f"PO: {po_number} — {part_description}\n"
            f"Expected delivery: today\n\n"
            f"Could you confirm the delivery status? Thank you."
        )

        return self.send_message(to_number, body)