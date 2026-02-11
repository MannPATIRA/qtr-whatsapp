"""
TEST 1: Send a WhatsApp message from code to your phone.

BEFORE RUNNING THIS:
1. Open WhatsApp on your phone
2. Send "join <your-sandbox-code>" to +1 (415) 523-8886
   (You got this code from the Twilio Console → Messaging → Try it out → Send a WhatsApp message)
3. Wait for the "You're connected" reply
4. THEN run this script
"""

import sys
from whatsapp import WhatsAppService

# Replace this with YOUR phone number (the one you joined the sandbox with)
MY_PHONE = "+447449367127"  # <-- CHANGE THIS to your real number, e.g. "+97477671777"

if MY_PHONE == "+447XXXXXXXXX":
    print("ERROR: You need to edit test_send.py and replace MY_PHONE with your actual phone number!")
    print("Use E.164 format: +<country_code><number>, e.g. +97455001234")
    sys.exit(1)

wa = WhatsAppService()

print("Sending test message...")
result = wa.send_message(MY_PHONE, "Hello from Hexa! If you see this, Step 1 is working.")

print(f"\nResult:")
print(f"  Message SID: {result['sid']}")
print(f"  Status: {result['status']}")
print(f"  To: {result['to']}")
print(f"\nCheck your WhatsApp — you should receive a message within a few seconds!")