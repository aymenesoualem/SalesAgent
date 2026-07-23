import os
from sqlalchemy import (
    Column, Integer, String, Boolean, Numeric, Date, TIMESTAMP,
    ForeignKey, create_engine, Text
)
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Product(Base):
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True)
    brand = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    material = Column(String(50), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    in_stock = Column(Boolean, default=True, nullable=False)


class Store(Base):
    __tablename__ = 'stores'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    city = Column(String(50), nullable=False)
    address = Column(String(150), nullable=False)
    phone = Column(String(20), nullable=False)
    opening_hours = Column(String(100), nullable=False)


class Customer(Base):
    __tablename__ = 'customers'

    id = Column(Integer, primary_key=True)
    full_name = Column(String(150), nullable=False)
    phone_number = Column(String(20), nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)


class Order(Base):
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True)
    order_number = Column(String(20), unique=True, nullable=False)
    customer_name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=False)
    product_reference = Column(String(30), nullable=False)
    product_name = Column(String(255), nullable=False)
    status = Column(String(30), nullable=False)
    estimated_delivery = Column(Date)


class SupportTicket(Base):
    __tablename__ = 'support_tickets'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    phone_number = Column(String(15), nullable=False)
    issue_type = Column(String(50), nullable=False)
    priority = Column(Integer, nullable=False)
    summary = Column(Text)

def get_session():
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://agent:sales@localhost:5432/ThomGroupSupport_db")
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return Session()
