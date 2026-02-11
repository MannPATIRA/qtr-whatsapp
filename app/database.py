"""
Database models and setup.
Using SQLite for development. Swap the DATABASE_URL for PostgreSQL in production.
"""

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import uuid

DATABASE_URL = "sqlite:///./hexa.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


# --- MODELS ---

class Company(Base):
    __tablename__ = "companies"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    whatsapp_number = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    suppliers = relationship("Supplier", back_populates="company")
    users = relationship("User", back_populates="company")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    company_id = Column(String, ForeignKey("companies.id"))
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "technician", "buyer", "approver"
    phone = Column(String)
    approval_limit = Column(Float, default=0)  # 0 = no limit (approver)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="users")


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(String, primary_key=True, default=generate_uuid)
    company_id = Column(String, ForeignKey("companies.id"))
    name = Column(String, nullable=False)
    contact_name = Column(String)
    phone = Column(String, nullable=False)
    categories = Column(JSON, default=list)  # ["transmission", "engine", ...]
    location = Column(String)
    is_active = Column(Boolean, default=True)
    avg_response_minutes = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="suppliers")
    quotes = relationship("Quote", back_populates="supplier")


class PartsRequest(Base):
    __tablename__ = "parts_requests"

    id = Column(String, primary_key=True, default=generate_uuid)
    company_id = Column(String, ForeignKey("companies.id"))
    requested_by = Column(String, ForeignKey("users.id"))
    part_description = Column(String, nullable=False)
    vehicle_info = Column(String)
    quantity = Column(Integer, default=1)
    urgency = Column(String, default="normal")  # normal, urgent, emergency
    deadline = Column(String)
    notes = Column(String)
    status = Column(String, default="draft")
    # Statuses: draft → rfq_sent → quotes_received → approved → ordered → delivered → cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    rfqs = relationship("RFQ", back_populates="parts_request")


class RFQ(Base):
    __tablename__ = "rfqs"

    id = Column(String, primary_key=True, default=generate_uuid)
    parts_request_id = Column(String, ForeignKey("parts_requests.id"))
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    message_sid = Column(String)  # Twilio message SID
    message_status = Column(String, default="sent")
    sent_at = Column(DateTime, default=datetime.utcnow)
    response_received_at = Column(DateTime)
    status = Column(String, default="sent")  # sent, responded, no_response

    parts_request = relationship("PartsRequest", back_populates="rfqs")
    quote = relationship("Quote", back_populates="rfq", uselist=False)


class Quote(Base):
    __tablename__ = "quotes"

    id = Column(String, primary_key=True, default=generate_uuid)
    rfq_id = Column(String, ForeignKey("rfqs.id"))
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    price = Column(Float)
    currency = Column(String, default="QAR")
    total_price = Column(Float)
    shipping_cost = Column(Float)
    availability = Column(String)  # in_stock, out_of_stock, can_order, checking
    delivery_days = Column(Integer)
    condition = Column(String)  # genuine, aftermarket, brand name
    notes = Column(String)
    raw_message = Column(Text)  # The original WhatsApp message
    ai_confidence = Column(Float)
    needs_review = Column(Boolean, default=False)
    is_selected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    rfq = relationship("RFQ", back_populates="quote")
    supplier = relationship("Supplier", back_populates="quotes")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(String, primary_key=True, default=generate_uuid)
    po_number = Column(String, unique=True, nullable=False)
    company_id = Column(String, ForeignKey("companies.id"))
    parts_request_id = Column(String, ForeignKey("parts_requests.id"))
    quote_id = Column(String, ForeignKey("quotes.id"))
    supplier_id = Column(String, ForeignKey("suppliers.id"))
    approved_by = Column(String, ForeignKey("users.id"))
    amount = Column(Float, nullable=False)
    currency = Column(String, default="QAR")
    status = Column(String, default="confirmed")
    # Statuses: confirmed → delivered → cancelled
    expected_delivery = Column(String)
    actual_delivery_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class MessageLog(Base):
    __tablename__ = "message_log"

    id = Column(String, primary_key=True, default=generate_uuid)
    company_id = Column(String)
    direction = Column(String)  # outbound, inbound
    from_number = Column(String)
    to_number = Column(String)
    body = Column(Text)
    message_sid = Column(String)
    linked_rfq_id = Column(String)
    linked_po_id = Column(String)
    source = Column(String)  # hexa_api, whatsapp_app, supplier
    created_at = Column(DateTime, default=datetime.utcnow)


# --- CREATE TABLES ---

def init_db():
    """Create all tables. Safe to call multiple times (only creates if not exists)."""
    Base.metadata.create_all(bind=engine)
    print("Database tables created.")


def get_db():
    """Get a database session. Use in a with statement or call .close() when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- SEED DATA ---

def seed_demo_data():
    """
    Create demo data for testing.
    This simulates Cedars Motors with a few suppliers and users.
    """
    db = SessionLocal()

    # Check if already seeded
    existing = db.query(Company).first()
    if existing:
        print("Database already has data. Skipping seed.")
        db.close()
        return existing.id

    # Create company
    company = Company(
        id="company-cedars",
        name="Cedars Motors & Trading Co.",
        whatsapp_number="+97477671777",
    )
    db.add(company)

    # Create users
    users = [
        User(id="user-ahmed", company_id="company-cedars", name="Ahmed",
             role="buyer", phone="+97455001111", approval_limit=500),
        User(id="user-raslan", company_id="company-cedars", name="Raslan",
             role="approver", phone="+97455002222", approval_limit=0),
        User(id="user-khalid", company_id="company-cedars", name="Khalid",
             role="technician", phone="+97455003333"),
    ]
    db.add_all(users)

    # IMPORTANT: For testing, we'll set supplier phone numbers to YOUR phone number
    # so that when RFQs are sent, YOU receive them and can reply as the supplier.
    # Change these to your actual phone number.
    YOUR_PHONE = "+447449367127"  # <-- CHANGE THIS

    suppliers = [
        Supplier(
            id="supplier-gulf", company_id="company-cedars",
            name="Gulf Auto Care", contact_name="Ali",
            phone=YOUR_PHONE,  # In production, this would be the real supplier's number
            categories=["transmission", "engine", "suspension", "filters"],
            location="Industrial Area, Doha",
        ),
        Supplier(
            id="supplier-global", company_id="company-cedars",
            name="Global Auto Parts", contact_name="Hassan",
            phone=YOUR_PHONE,  # Same number for testing — you play all suppliers
            categories=["general", "body", "electrical", "brakes"],
            location="Industrial Area, Doha",
        ),
        Supplier(
            id="supplier-mohamed", company_id="company-cedars",
            name="Mohamed (Sharjah)", contact_name="Mohamed",
            phone=YOUR_PHONE,  # Same number for testing
            categories=["transmission", "engine"],
            location="Sharjah, UAE",
        ),
    ]
    db.add_all(suppliers)

    db.commit()
    print("Demo data seeded successfully!")
    print(f"  Company: {company.name}")
    print(f"  Users: {len(users)}")
    print(f"  Suppliers: {len(suppliers)}")
    print(f"\n  ⚠️  Supplier phone numbers are set to {YOUR_PHONE}")
    print(f"  Change this in database.py seed_demo_data() to YOUR actual phone number!")
    db.close()

    return company.id


if __name__ == "__main__":
    init_db()
    seed_demo_data()