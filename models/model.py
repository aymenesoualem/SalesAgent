from sqlalchemy import (
    Column, Integer, String, Boolean, Numeric, TIMESTAMP,
    ForeignKey, create_engine, Text
)
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Car(Base):
    __tablename__ = 'cars'

    id = Column(Integer, primary_key=True)
    make = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    year = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    type = Column(String(50), nullable=False)
    available = Column(Boolean, default=True, nullable=False)



class Lead(Base):
    __tablename__ = 'leads'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    phone_number = Column(String(15), unique=True, nullable=False)
    lead_source = Column(String(50))
    interest_score = Column(Integer, nullable=False)
    call_summary = Column(Text)

def get_session():
    DATABASE_URL = "postgresql://agent:sales@localhost:5432/CarDealership_db"
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return Session()
