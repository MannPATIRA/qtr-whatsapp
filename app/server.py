"""
The main FastAPI server.
This receives incoming WhatsApp messages via webhook from Twilio.
"""

from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
from datetime import datetime
import json
import os

load_dotenv()

app = FastAPI(title="Hexa WhatsApp Procurement")

# In-memory storage for now (we'll add a proper database in Step 3)
incoming_messages = []
outgoing_messages = []


@app.get("/")
async def root():
    """Health check — also useful to verify ngrok is working."""
    return {"status": "ok", "service": "Hexa WhatsApp Procurement", "time": str(datetime.now())}


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Twilio calls this URL every time someone sends a WhatsApp message
    to your sandbox number.

    Twilio sends the data as form-encoded POST data (NOT JSON).
    """
    form_data = await request.form()

    # Extract all the fields Twilio sends
    message = {
        "message_sid": form_data.get("MessageSid"),
        "from_number": form_data.get("From", "").replace("whatsapp:", ""),
        "to_number": form_data.get("To", "").replace("whatsapp:", ""),
        "body": form_data.get("Body", ""),
        "num_media": int(form_data.get("NumMedia", 0)),
        "profile_name": form_data.get("ProfileName", ""),
        "timestamp": datetime.now().isoformat(),
    }

    # Check for media (images, voice notes, documents)
    media_items = []
    for i in range(message["num_media"]):
        media_items.append({
            "url": form_data.get(f"MediaUrl{i}"),
            "content_type": form_data.get(f"MediaContentType{i}"),
        })
    message["media"] = media_items

    # Store it
    incoming_messages.append(message)

    # Print to console so you can see it in real-time
    print("\n" + "=" * 60)
    print(f"📨 INCOMING WHATSAPP MESSAGE")
    print(f"   From: {message['from_number']} ({message['profile_name']})")
    print(f"   Body: {message['body']}")
    if media_items:
        print(f"   Media: {len(media_items)} attachment(s)")
        for m in media_items:
            print(f"     - {m['content_type']}: {m['url']}")
    print(f"   Time: {message['timestamp']}")
    print(f"   SID:  {message['message_sid']}")
    print("=" * 60 + "\n")

    # Twilio expects a TwiML response (even if empty)
    # Returning empty TwiML means "don't auto-reply"
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml"
    )


@app.post("/webhook/whatsapp/status")
async def whatsapp_status(request: Request):
    """
    Twilio calls this when a message status changes
    (queued → sent → delivered → read → failed).
    """
    form_data = await request.form()

    status_update = {
        "message_sid": form_data.get("MessageSid"),
        "status": form_data.get("MessageStatus"),
        "to": form_data.get("To", "").replace("whatsapp:", ""),
        "error_code": form_data.get("ErrorCode"),
        "timestamp": datetime.now().isoformat(),
    }

    print(f"📋 Status update: {status_update['message_sid'][:20]}... → {status_update['status']}")

    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml"
    )


@app.get("/messages")
async def get_messages():
    """View all received messages (useful for debugging)."""
    return {
        "incoming": incoming_messages,
        "count": len(incoming_messages)
    }