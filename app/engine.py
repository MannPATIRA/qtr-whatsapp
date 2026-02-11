"""
The core procurement engine.
Orchestrates the flow: Parts Request → RFQs → Quotes → Approval → PO
"""

from database import SessionLocal, PartsRequest, RFQ, Quote, Supplier, PurchaseOrder, MessageLog, Company
from whatsapp import WhatsAppService
from parser import parse_supplier_response, classify_message
from datetime import datetime
import random
import string


wa = WhatsAppService()


def create_parts_request(company_id: str, requested_by: str,
                         part_description: str, vehicle_info: str = "",
                         quantity: int = 1, urgency: str = "normal",
                         deadline: str = "", notes: str = "") -> dict:
    """
    Step 1: A technician creates a parts request.
    This automatically finds matching suppliers and sends RFQs.
    """
    db = SessionLocal()

    # Create the parts request
    pr = PartsRequest(
        company_id=company_id,
        requested_by=requested_by,
        part_description=part_description,
        vehicle_info=vehicle_info,
        quantity=quantity,
        urgency=urgency,
        deadline=deadline,
        notes=notes,
        status="draft",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    print(f"\n📋 Parts Request created: {pr.id[:8]}...")
    print(f"   Part: {part_description}")
    print(f"   Vehicle: {vehicle_info}")

    # Find matching suppliers
    # For now, simple category matching. In production, use the AI categoriser.
    suppliers = db.query(Supplier).filter(
        Supplier.company_id == company_id,
        Supplier.is_active == True
    ).all()

    # Get company name for the RFQ message
    company = db.query(Company).filter(Company.id == company_id).first()

    rfqs_sent = []
    for supplier in suppliers:
        # Send RFQ via WhatsApp
        try:
            result = wa.send_rfq(
                to_number=supplier.phone,
                company_name=company.name,
                part_description=part_description,
                vehicle_info=vehicle_info,
                quantity=quantity,
                deadline=deadline or "ASAP",
            )

            # Record the RFQ
            rfq = RFQ(
                parts_request_id=pr.id,
                supplier_id=supplier.id,
                message_sid=result["sid"],
                message_status="sent",
                sent_at=datetime.utcnow(),
                status="sent",
            )
            db.add(rfq)

            # Log the message
            log = MessageLog(
                company_id=company_id,
                direction="outbound",
                from_number=company.whatsapp_number,
                to_number=supplier.phone,
                body=result["body"],
                message_sid=result["sid"],
                linked_rfq_id=rfq.id,
                source="hexa_api",
            )
            db.add(log)

            rfqs_sent.append({
                "rfq_id": rfq.id,
                "supplier": supplier.name,
                "phone": supplier.phone,
                "message_sid": result["sid"],
            })

            print(f"   ✉️  RFQ sent to {supplier.name} ({supplier.phone})")

        except Exception as e:
            print(f"   ❌ Failed to send RFQ to {supplier.name}: {e}")

    # Update status
    pr.status = "rfq_sent"
    db.commit()

    # Capture values before closing session (ORM objects become detached after close)
    pr_id = pr.id
    db.close()

    return {
        "parts_request_id": pr_id,
        "status": "rfq_sent",
        "rfqs_sent": rfqs_sent,
        "supplier_count": len(rfqs_sent),
    }


def process_supplier_response(from_number: str, message_body: str, message_sid: str) -> dict:
    """
    Step 2: A supplier replied via WhatsApp.
    Find the matching RFQ, parse the response, store the quote.
    """
    db = SessionLocal()

    # Clean the phone number
    clean_number = from_number.replace("whatsapp:", "").strip()

    # Find the most recent open RFQ for this supplier's phone number
    rfq = db.query(RFQ).join(Supplier).filter(
        Supplier.phone == clean_number,
        RFQ.status == "sent",
    ).order_by(RFQ.sent_at.desc()).first()

    if not rfq:
        print(f"⚠️  No open RFQ found for {clean_number}. Logging as unmatched message.")
        log = MessageLog(
            direction="inbound",
            from_number=clean_number,
            body=message_body,
            message_sid=message_sid,
            source="supplier",
        )
        db.add(log)
        db.commit()
        db.close()
        return {"status": "no_matching_rfq", "from": clean_number}

    # Get the parts request details for context
    pr = db.query(PartsRequest).filter(PartsRequest.id == rfq.parts_request_id).first()
    supplier = db.query(Supplier).filter(Supplier.id == rfq.supplier_id).first()

    print(f"\n📨 Processing response from {supplier.name} for PR {pr.id[:8]}...")

    # Classify the message
    msg_type = classify_message(message_body)
    print(f"   Classification: {msg_type}")

    if msg_type == "question":
        # Supplier is asking a clarifying question — needs human review
        log = MessageLog(
            company_id=pr.company_id,
            direction="inbound",
            from_number=clean_number,
            body=message_body,
            message_sid=message_sid,
            linked_rfq_id=rfq.id,
            source="supplier",
        )
        db.add(log)
        db.commit()
        db.close()
        print(f"   ❓ Supplier asked a question — needs human review: \"{message_body}\"")
        return {"status": "question_needs_review", "message": message_body, "supplier": supplier.name}

    if msg_type == "acknowledgment":
        # Supplier acknowledged but hasn't quoted yet
        log = MessageLog(
            company_id=pr.company_id,
            direction="inbound",
            from_number=clean_number,
            body=message_body,
            message_sid=message_sid,
            linked_rfq_id=rfq.id,
            source="supplier",
        )
        db.add(log)
        db.commit()
        db.close()
        print(f"   ⏳ Supplier acknowledged — waiting for actual quote")
        return {"status": "acknowledged", "message": message_body, "supplier": supplier.name}

    # It's a quote — parse it
    parsed = parse_supplier_response(
        message_body=message_body,
        part_description=pr.part_description,
        vehicle_info=pr.vehicle_info or "",
        quantity=pr.quantity,
    )

    print(f"   💰 Parsed quote: {parsed.get('price')} {parsed.get('currency')}, "
          f"availability: {parsed.get('availability')}, "
          f"delivery: {parsed.get('delivery_days')} days, "
          f"confidence: {parsed.get('confidence')}")

    # Store the quote
    quote = Quote(
        rfq_id=rfq.id,
        supplier_id=supplier.id,
        price=parsed.get("price"),
        currency=parsed.get("currency", "QAR"),
        total_price=parsed.get("total_price"),
        shipping_cost=parsed.get("shipping_cost"),
        availability=parsed.get("availability"),
        delivery_days=parsed.get("delivery_days"),
        condition=parsed.get("condition"),
        notes=parsed.get("notes"),
        raw_message=message_body,
        ai_confidence=parsed.get("confidence", 0),
        needs_review=parsed.get("confidence", 0) < 0.7,
    )
    db.add(quote)

    # Update RFQ status
    rfq.status = "responded"
    rfq.response_received_at = datetime.utcnow()

    # Log the message
    log = MessageLog(
        company_id=pr.company_id,
        direction="inbound",
        from_number=clean_number,
        body=message_body,
        message_sid=message_sid,
        linked_rfq_id=rfq.id,
        source="supplier",
    )
    db.add(log)

    # Check if all RFQs for this parts request have been responded to
    all_rfqs = db.query(RFQ).filter(RFQ.parts_request_id == pr.id).all()
    responded = sum(1 for r in all_rfqs if r.status == "responded")
    total = len(all_rfqs)

    if responded == total:
        pr.status = "quotes_received"
        print(f"   ✅ All {total} suppliers have responded! Ready for review.")
    else:
        print(f"   📊 {responded}/{total} suppliers have responded.")

    db.commit()

    # Capture values before closing session
    supplier_name = supplier.name
    db.close()

    return {
        "status": "quote_stored",
        "supplier": supplier_name,
        "price": parsed.get("price"),
        "currency": parsed.get("currency"),
        "availability": parsed.get("availability"),
        "delivery_days": parsed.get("delivery_days"),
        "confidence": parsed.get("confidence"),
        "responded_count": responded,
        "total_suppliers": total,
    }


def get_quotes_for_request(parts_request_id: str) -> dict:
    """
    Get all quotes for a parts request, with comparison data.
    This is what the dashboard displays.
    """
    db = SessionLocal()

    pr = db.query(PartsRequest).filter(PartsRequest.id == parts_request_id).first()
    if not pr:
        db.close()
        return {"error": "Parts request not found"}

    rfqs = db.query(RFQ).filter(RFQ.parts_request_id == parts_request_id).all()

    quotes_data = []
    for rfq in rfqs:
        supplier = db.query(Supplier).filter(Supplier.id == rfq.supplier_id).first()
        quote = db.query(Quote).filter(Quote.rfq_id == rfq.id).first()

        quote_info = {
            "rfq_id": rfq.id,
            "supplier_id": supplier.id,
            "supplier_name": supplier.name,
            "supplier_location": supplier.location,
            "rfq_status": rfq.status,
            "sent_at": rfq.sent_at.isoformat() if rfq.sent_at else None,
        }

        if quote:
            response_time = None
            if rfq.sent_at and rfq.response_received_at:
                delta = rfq.response_received_at - rfq.sent_at
                response_time = int(delta.total_seconds() / 60)

            quote_info.update({
                "quote_id": quote.id,
                "price": quote.price,
                "currency": quote.currency,
                "total_price": quote.total_price,
                "shipping_cost": quote.shipping_cost,
                "availability": quote.availability,
                "delivery_days": quote.delivery_days,
                "condition": quote.condition,
                "notes": quote.notes,
                "raw_message": quote.raw_message,
                "confidence": quote.ai_confidence,
                "needs_review": quote.needs_review,
                "response_time_minutes": response_time,
            })

        quotes_data.append(quote_info)

    # Sort: quotes with prices first, then by price
    quotes_with_price = sorted(
        [q for q in quotes_data if q.get("price")],
        key=lambda x: x["price"]
    )
    quotes_without_price = [q for q in quotes_data if not q.get("price")]

    # Capture values before closing session
    pr_data = {
        "id": pr.id,
        "part_description": pr.part_description,
        "vehicle_info": pr.vehicle_info,
        "quantity": pr.quantity,
        "urgency": pr.urgency,
        "deadline": pr.deadline,
        "status": pr.status,
        "created_at": pr.created_at.isoformat(),
    }
    db.close()

    return {
        "parts_request": pr_data,
        "quotes": quotes_with_price + quotes_without_price,
        "summary": {
            "total_suppliers": len(quotes_data),
            "responded": len([q for q in quotes_data if q["rfq_status"] == "responded"]),
            "best_price": min([q["price"] for q in quotes_data if q.get("price")], default=None),
            "fastest_delivery": min([q["delivery_days"] for q in quotes_data if q.get("delivery_days") is not None], default=None),
        }
    }


def approve_quote(parts_request_id: str, quote_id: str, approved_by: str) -> dict:
    """
    Step 3: Approve a quote and generate a purchase order.
    Sends PO confirmation to winning supplier.
    Sends polite decline to other suppliers.
    """
    db = SessionLocal()

    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    pr = db.query(PartsRequest).filter(PartsRequest.id == parts_request_id).first()
    supplier = db.query(Supplier).filter(Supplier.id == quote.supplier_id).first()
    company = db.query(Company).filter(Company.id == pr.company_id).first()

    # Generate PO number
    random_suffix = ''.join(random.choices(string.digits, k=4))
    po_number = f"PO-{random_suffix}"

    # Create PO
    po = PurchaseOrder(
        po_number=po_number,
        company_id=company.id,
        parts_request_id=pr.id,
        quote_id=quote.id,
        supplier_id=supplier.id,
        approved_by=approved_by,
        amount=quote.total_price or quote.price,
        currency=quote.currency,
        status="confirmed",
        expected_delivery=f"{quote.delivery_days} days" if quote.delivery_days else "TBD",
    )
    db.add(po)

    # Mark quote as selected
    quote.is_selected = True

    # Update parts request status
    pr.status = "ordered"

    print(f"\n✅ PO {po_number} created!")
    print(f"   Supplier: {supplier.name}")
    print(f"   Amount: {quote.price} {quote.currency}")

    # Send PO confirmation to winning supplier
    try:
        result = wa.send_po_confirmation(
            to_number=supplier.phone,
            company_name=company.name,
            po_number=po_number,
            part_description=pr.part_description,
            price=str(quote.total_price or quote.price),
            currency=quote.currency,
            delivery_date=f"{quote.delivery_days} days" if quote.delivery_days else "ASAP",
        )
        print(f"   📤 PO confirmation sent to {supplier.name}")
    except Exception as e:
        print(f"   ❌ Failed to send PO confirmation: {e}")

    # Send polite decline to other suppliers who quoted
    other_quotes = db.query(Quote).join(RFQ).filter(
        RFQ.parts_request_id == parts_request_id,
        Quote.id != quote_id,
        Quote.price != None,  # Only decline those who actually quoted
    ).all()

    for other_quote in other_quotes:
        other_supplier = db.query(Supplier).filter(Supplier.id == other_quote.supplier_id).first()
        try:
            wa.send_decline(other_supplier.phone, pr.part_description)
            print(f"   📤 Decline sent to {other_supplier.name}")
        except Exception as e:
            print(f"   ❌ Failed to send decline to {other_supplier.name}: {e}")

    db.commit()

    # Capture values before closing session
    supplier_name = supplier.name
    amount = quote.total_price or quote.price
    currency = quote.currency
    db.close()

    return {
        "po_number": po_number,
        "supplier": supplier_name,
        "amount": amount,
        "currency": currency,
        "status": "confirmed",
    }