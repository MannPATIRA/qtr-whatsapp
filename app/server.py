"""
Main FastAPI server — now integrated with database, parser, and engine.
"""

from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from datetime import datetime
import json
import os

load_dotenv()

# Initialize database
from database import init_db, seed_demo_data, SessionLocal, PartsRequest, Supplier, Quote, RFQ, Company, User, PurchaseOrder
init_db()
company_id = seed_demo_data()  # Returns existing company ID if already seeded

import engine

app = FastAPI(title="Hexa WhatsApp Procurement")


# ============================================================
# WEBHOOKS (Twilio calls these)
# ============================================================

from router import route_message

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """Receive incoming WhatsApp messages from Twilio."""
    form_data = await request.form()

    from_number = form_data.get("From", "")
    body = form_data.get("Body", "")
    message_sid = form_data.get("MessageSid", "")
    profile_name = form_data.get("ProfileName", "")

    print(f"\n📨 Message from {from_number.replace('whatsapp:', '')} ({profile_name}): \"{body}\"")

    # Step 1: Route the message
    route = route_message(from_number, body)
    print(f"   Routed as: {route['type']}")

    # Step 2: Handle based on type
    if route["type"] == "parts_request":
        result = engine.handle_whatsapp_parts_request(
            from_number=from_number,
            message_body=body,
            message_sid=message_sid,
            user_id=route.get("user_id"),
            company_id=route.get("company_id"),
        )
        print(f"   Result: Parts request created → {result.get('supplier_count', 0)} RFQs sent")

    elif route["type"] == "supplier_response":
        result = engine.process_supplier_response(
            from_number=from_number,
            message_body=body,
            message_sid=message_sid,
        )
        print(f"   Result: {result.get('status')}")

    elif route["type"] == "status_inquiry":
        # For now, just acknowledge. You can build a proper status lookup later.
        from whatsapp import WhatsAppService
        wa = WhatsAppService()
        try:
            wa.send_message(
                from_number,
                "Let me check on that for you. Please check the dashboard for the latest status, "
                "or I'll get back to you shortly."
            )
        except Exception:
            pass
        result = {"status": "status_inquiry_acknowledged"}

    else:
        print(f"   ⚠️  Unknown message type. Logged but not processed.")
        result = {"status": "unknown"}

    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml"
    )


@app.post("/webhook/whatsapp/status")
async def whatsapp_status(request: Request):
    """Track message delivery status."""
    form_data = await request.form()
    status = form_data.get("MessageStatus", "")
    sid = form_data.get("MessageSid", "")[:20]
    print(f"📋 Status: {sid}... → {status}")

    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml"
    )


# ============================================================
# API ENDPOINTS (Dashboard calls these)
# ============================================================

@app.get("/")
async def root():
    return {"status": "ok", "service": "Hexa WhatsApp Procurement"}


@app.get("/api/suppliers")
async def list_suppliers():
    """List all suppliers."""
    db = SessionLocal()
    suppliers = db.query(Supplier).filter(Supplier.company_id == "company-cedars").all()
    result = [
        {
            "id": s.id,
            "name": s.name,
            "contact_name": s.contact_name,
            "phone": s.phone,
            "categories": s.categories,
            "location": s.location,
        }
        for s in suppliers
    ]
    db.close()
    return result


@app.post("/api/parts-request")
async def create_parts_request(request: Request):
    """Create a new parts request and send RFQs."""
    data = await request.json()

    result = engine.create_parts_request(
        company_id="company-cedars",
        requested_by=data.get("requested_by", "user-khalid"),
        part_description=data["part_description"],
        vehicle_info=data.get("vehicle_info", ""),
        quantity=data.get("quantity", 1),
        urgency=data.get("urgency", "normal"),
        deadline=data.get("deadline", ""),
        notes=data.get("notes", ""),
    )

    return result


@app.get("/api/parts-requests")
async def list_parts_requests():
    """List all parts requests."""
    db = SessionLocal()
    requests = db.query(PartsRequest).filter(
        PartsRequest.company_id == "company-cedars"
    ).order_by(PartsRequest.created_at.desc()).all()

    result = []
    for pr in requests:
        rfqs = db.query(RFQ).filter(RFQ.parts_request_id == pr.id).all()
        responded = sum(1 for r in rfqs if r.status == "responded")

        result.append({
            "id": pr.id,
            "part_description": pr.part_description,
            "vehicle_info": pr.vehicle_info,
            "quantity": pr.quantity,
            "urgency": pr.urgency,
            "status": pr.status,
            "deadline": pr.deadline,
            "suppliers_total": len(rfqs),
            "suppliers_responded": responded,
            "created_at": pr.created_at.isoformat(),
        })

    db.close()
    return result


@app.get("/api/parts-requests/{pr_id}/quotes")
async def get_quotes(pr_id: str):
    """Get quote comparison for a parts request."""
    return engine.get_quotes_for_request(pr_id)


@app.post("/api/parts-requests/{pr_id}/approve")
async def approve(pr_id: str, request: Request):
    """Approve a quote and create a PO."""
    data = await request.json()

    result = engine.approve_quote(
        parts_request_id=pr_id,
        quote_id=data["quote_id"],
        approved_by=data.get("approved_by", "user-raslan"),
    )

    return result


@app.get("/api/purchase-orders")
async def list_pos():
    """List all purchase orders."""
    db = SessionLocal()
    pos = db.query(PurchaseOrder).filter(
        PurchaseOrder.company_id == "company-cedars"
    ).order_by(PurchaseOrder.created_at.desc()).all()

    result = []
    for po in pos:
        supplier = db.query(Supplier).filter(Supplier.id == po.supplier_id).first()
        pr = db.query(PartsRequest).filter(PartsRequest.id == po.parts_request_id).first()

        result.append({
            "po_number": po.po_number,
            "supplier": supplier.name if supplier else "Unknown",
            "part": pr.part_description if pr else "Unknown",
            "amount": po.amount,
            "currency": po.currency,
            "status": po.status,
            "expected_delivery": po.expected_delivery,
            "created_at": po.created_at.isoformat(),
        })

    db.close()
    return result


# ============================================================
# WEB DASHBOARD (HTML)
# ============================================================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """The main web dashboard."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hexa — Procurement Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }
        .header { background: #1a1a2e; color: white; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 20px; font-weight: 600; }
        .header .company { font-size: 14px; opacity: 0.7; }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
        .card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .card h2 { font-size: 16px; margin-bottom: 12px; color: #1a1a2e; }
        .btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; }
        .btn-primary { background: #4361ee; color: white; }
        .btn-primary:hover { background: #3651d4; }
        .btn-success { background: #2ec4b6; color: white; }
        .btn-success:hover { background: #25a99d; }
        .btn-danger { background: #e63946; color: white; }
        .btn-sm { padding: 4px 10px; font-size: 12px; }
        input, select, textarea { padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; width: 100%; margin-bottom: 8px; }
        .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 8px; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
        .badge-sent { background: #fff3cd; color: #856404; }
        .badge-received { background: #d4edda; color: #155724; }
        .badge-ordered { background: #cce5ff; color: #004085; }
        .badge-draft { background: #e2e3e5; color: #383d41; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #eee; }
        th { font-weight: 600; color: #666; font-size: 12px; text-transform: uppercase; }
        tr:hover { background: #f8f9fa; }
        .quote-row { cursor: pointer; }
        .quote-row.best { background: #f0fdf4; }
        .price { font-weight: 700; font-size: 16px; }
        .raw-msg { font-size: 12px; color: #888; font-style: italic; margin-top: 4px; }
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 100; justify-content: center; align-items: center; }
        .modal-overlay.active { display: flex; }
        .modal { background: white; border-radius: 12px; padding: 24px; max-width: 500px; width: 90%; }
        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px; }
        .stat { text-align: center; }
        .stat .number { font-size: 28px; font-weight: 700; color: #4361ee; }
        .stat .label { font-size: 12px; color: #888; }
        #loading { text-align: center; padding: 40px; color: #888; }
        .tab-bar { display: flex; gap: 4px; margin-bottom: 16px; }
        .tab { padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; border: 1px solid #ddd; background: white; }
        .tab.active { background: #4361ee; color: white; border-color: #4361ee; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>⚡ Hexa Procurement</h1>
            <div class="company">Cedars Motors & Trading Co.</div>
        </div>
        <button class="btn btn-primary" onclick="showNewRequestForm()">+ New Parts Request</button>
    </div>

    <div class="container">
        <div class="stats" id="stats">
            <div class="stat"><div class="number" id="stat-active">-</div><div class="label">Active Requests</div></div>
            <div class="stat"><div class="number" id="stat-quotes">-</div><div class="label">Quotes Received</div></div>
            <div class="stat"><div class="number" id="stat-pos">-</div><div class="label">POs Issued</div></div>
        </div>

        <div class="tab-bar">
            <div class="tab active" onclick="switchTab('requests')">Parts Requests</div>
            <div class="tab" onclick="switchTab('orders')">Purchase Orders</div>
        </div>

        <div id="requests-tab">
            <div class="card">
                <h2>Parts Requests</h2>
                <div id="requests-list"><div id="loading">Loading...</div></div>
            </div>
        </div>

        <div id="orders-tab" style="display:none;">
            <div class="card">
                <h2>Purchase Orders</h2>
                <div id="orders-list"><div id="loading">Loading...</div></div>
            </div>
        </div>

        <div id="quotes-section" style="display:none;">
            <div class="card">
                <h2 id="quotes-title">Quotes</h2>
                <div id="quotes-list"></div>
            </div>
        </div>
    </div>

    <!-- New Request Modal -->
    <div class="modal-overlay" id="new-request-modal">
        <div class="modal">
            <h2 style="margin-bottom:16px;">New Parts Request</h2>
            <div class="form-row">
                <div><label>Part Description *</label><input id="req-part" placeholder="e.g. Torque converter"></div>
                <div><label>Vehicle</label><input id="req-vehicle" placeholder="e.g. Nissan Patrol Y62 2019"></div>
            </div>
            <div class="form-row">
                <div><label>Quantity</label><input id="req-qty" type="number" value="1"></div>
                <div><label>Urgency</label>
                    <select id="req-urgency">
                        <option value="normal">Normal</option>
                        <option value="urgent">Urgent</option>
                        <option value="emergency">Emergency</option>
                    </select>
                </div>
            </div>
            <label>Deadline</label><input id="req-deadline" placeholder="e.g. Thursday 13 Feb">
            <label>Notes</label><textarea id="req-notes" rows="2" placeholder="Any special requirements..."></textarea>
            <div style="display:flex;gap:8px;margin-top:12px;">
                <button class="btn btn-primary" onclick="submitRequest()">Send RFQs to Suppliers</button>
                <button class="btn" onclick="closeModal()">Cancel</button>
            </div>
            <div id="submit-status" style="margin-top:12px;font-size:13px;"></div>
        </div>
    </div>

    <script>
        const API = '';  // Same origin

        // --- DATA LOADING ---
        async function loadRequests() {
            const res = await fetch(API + '/api/parts-requests');
            const data = await res.json();

            document.getElementById('stat-active').textContent = data.filter(r => ['rfq_sent','quotes_received'].includes(r.status)).length;
            document.getElementById('stat-quotes').textContent = data.reduce((sum, r) => sum + r.suppliers_responded, 0);

            if (data.length === 0) {
                document.getElementById('requests-list').innerHTML = '<p style="color:#888;padding:20px;text-align:center;">No parts requests yet. Click "+ New Parts Request" to start.</p>';
                return;
            }

            let html = '<table><thead><tr><th>Part</th><th>Vehicle</th><th>Urgency</th><th>Status</th><th>Quotes</th><th>Created</th><th></th></tr></thead><tbody>';
            for (const r of data) {
                const badge = {draft:'badge-draft',rfq_sent:'badge-sent',quotes_received:'badge-received',ordered:'badge-ordered',delivered:'badge-ordered'}[r.status] || 'badge-draft';
                const ago = timeAgo(r.created_at);
                html += '<tr>' +
                    '<td><strong>' + r.part_description + '</strong></td>' +
                    '<td>' + (r.vehicle_info || '-') + '</td>' +
                    '<td>' + r.urgency + '</td>' +
                    '<td><span class="badge ' + badge + '">' + r.status.replace('_',' ') + '</span></td>' +
                    '<td>' + r.suppliers_responded + '/' + r.suppliers_total + '</td>' +
                    '<td>' + ago + '</td>' +
                    '<td><button class="btn btn-sm btn-primary" onclick="viewQuotes(\\'' + r.id + '\\')">View Quotes</button></td>' +
                    '</tr>';
            }
            html += '</tbody></table>';
            document.getElementById('requests-list').innerHTML = html;
        }

        async function loadOrders() {
            const res = await fetch(API + '/api/purchase-orders');
            const data = await res.json();

            document.getElementById('stat-pos').textContent = data.length;

            if (data.length === 0) {
                document.getElementById('orders-list').innerHTML = '<p style="color:#888;padding:20px;text-align:center;">No purchase orders yet.</p>';
                return;
            }

            let html = '<table><thead><tr><th>PO #</th><th>Part</th><th>Supplier</th><th>Amount</th><th>Delivery</th><th>Status</th></tr></thead><tbody>';
            for (const po of data) {
                html += '<tr>' +
                    '<td><strong>' + po.po_number + '</strong></td>' +
                    '<td>' + po.part + '</td>' +
                    '<td>' + po.supplier + '</td>' +
                    '<td class="price">' + po.amount + ' ' + po.currency + '</td>' +
                    '<td>' + po.expected_delivery + '</td>' +
                    '<td><span class="badge badge-ordered">' + po.status + '</span></td>' +
                    '</tr>';
            }
            html += '</tbody></table>';
            document.getElementById('orders-list').innerHTML = html;
        }

        async function viewQuotes(prId) {
            document.getElementById('quotes-section').style.display = 'block';
            document.getElementById('quotes-list').innerHTML = '<p>Loading quotes...</p>';

            const res = await fetch(API + '/api/parts-requests/' + prId + '/quotes');
            const data = await res.json();

            document.getElementById('quotes-title').textContent =
                'Quotes for: ' + data.parts_request.part_description + ' — ' + (data.parts_request.vehicle_info || '');

            if (data.quotes.length === 0) {
                document.getElementById('quotes-list').innerHTML = '<p style="color:#888;">No quotes received yet. Waiting for suppliers to respond...</p>';
                return;
            }

            let html = '<table><thead><tr><th>Supplier</th><th>Price</th><th>Availability</th><th>Delivery</th><th>Condition</th><th>Confidence</th><th>Raw Message</th><th></th></tr></thead><tbody>';

            const bestPrice = data.summary.best_price;

            for (const q of data.quotes) {
                const isBest = q.price === bestPrice;
                const rowClass = isBest ? 'quote-row best' : 'quote-row';

                html += '<tr class="' + rowClass + '">' +
                    '<td><strong>' + q.supplier_name + '</strong><br><span style="font-size:11px;color:#888;">' + (q.supplier_location || '') + '</span></td>' +
                    '<td class="price">' + (q.price ? q.price + ' ' + (q.currency || 'QAR') : 'N/A') +
                        (q.shipping_cost ? '<br><span style="font-size:11px;">+' + q.shipping_cost + ' shipping</span>' : '') +
                        (isBest ? '<br><span style="font-size:10px;color:#2ec4b6;">★ BEST PRICE</span>' : '') + '</td>' +
                    '<td>' + (q.availability || '-').replace('_', ' ') + '</td>' +
                    '<td>' + (q.delivery_days !== null && q.delivery_days !== undefined ? (q.delivery_days === 0 ? 'Same day' : q.delivery_days + ' days') : '-') + '</td>' +
                    '<td>' + (q.condition || '-') + '</td>' +
                    '<td>' + (q.confidence ? Math.round(q.confidence * 100) + '%' : '-') + '</td>' +
                    '<td><div class="raw-msg">"' + (q.raw_message || '-') + '"</div></td>' +
                    '<td>' + (q.price ? '<button class="btn btn-sm btn-success" onclick="approveQuote(\\'' + data.parts_request.id + '\\',\\'' + q.quote_id + '\\')">Approve</button>' : '') + '</td>' +
                    '</tr>';
            }

            html += '</tbody></table>';
            document.getElementById('quotes-list').innerHTML = html;

            // Scroll to quotes
            document.getElementById('quotes-section').scrollIntoView({behavior: 'smooth'});
        }

        // --- ACTIONS ---
        function showNewRequestForm() {
            document.getElementById('new-request-modal').classList.add('active');
            document.getElementById('submit-status').textContent = '';
        }
        function closeModal() {
            document.getElementById('new-request-modal').classList.remove('active');
        }

        async function submitRequest() {
            const part = document.getElementById('req-part').value.trim();
            if (!part) { alert('Part description is required'); return; }

            document.getElementById('submit-status').textContent = 'Sending RFQs...';

            const res = await fetch(API + '/api/parts-request', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    part_description: part,
                    vehicle_info: document.getElementById('req-vehicle').value.trim(),
                    quantity: parseInt(document.getElementById('req-qty').value) || 1,
                    urgency: document.getElementById('req-urgency').value,
                    deadline: document.getElementById('req-deadline').value.trim(),
                    notes: document.getElementById('req-notes').value.trim(),
                })
            });
            const data = await res.json();

            document.getElementById('submit-status').innerHTML =
                '✅ RFQs sent to <strong>' + data.supplier_count + '</strong> suppliers! Check your WhatsApp.';

            // Clear form
            document.getElementById('req-part').value = '';
            document.getElementById('req-vehicle').value = '';
            document.getElementById('req-qty').value = '1';
            document.getElementById('req-notes').value = '';

            setTimeout(() => { closeModal(); loadRequests(); }, 2000);
        }

        async function approveQuote(prId, quoteId) {
            if (!confirm('Approve this quote and create a Purchase Order?')) return;

            const res = await fetch(API + '/api/parts-requests/' + prId + '/approve', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ quote_id: quoteId, approved_by: 'user-raslan' })
            });
            const data = await res.json();

            alert('PO ' + data.po_number + ' created! Confirmation sent to ' + data.supplier + '.');

            loadRequests();
            loadOrders();
            document.getElementById('quotes-section').style.display = 'none';
        }

        function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('requests-tab').style.display = tab === 'requests' ? 'block' : 'none';
            document.getElementById('orders-tab').style.display = tab === 'orders' ? 'block' : 'none';
            if (tab === 'orders') loadOrders();
        }

        function timeAgo(isoStr) {
            const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff/60) + 'm ago';
            if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
            return Math.floor(diff/86400) + 'd ago';
        }

        // --- AUTO REFRESH ---
        loadRequests();
        loadOrders();
        setInterval(() => { loadRequests(); }, 10000);  // Refresh every 10 seconds
    </script>
</body>
</html>
"""