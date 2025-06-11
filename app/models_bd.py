from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Enum, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from models import UserRole, Direction, OrderStatus


Base = declarative_base()

class User_BD(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.USER)
    api_key = Column(String, unique=True, nullable=False, default=lambda: f"key-{uuid.uuid4()}")
    orders = relationship("Order_BD", back_populates="user")
    balances = relationship("Balance_BD", back_populates="user")


class Instrument_BD(Base):
    __tablename__ = "instruments"
    ticker = Column(String, primary_key=True)
    name = Column(String, nullable=False)


class Order_BD(Base):
    __tablename__ = "orders"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String, ForeignKey("instruments.ticker"), nullable=False)
    direction = Column(Enum(Direction), nullable=False)
    qty = Column(Integer, nullable=False)
    price = Column(Integer)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.NEW)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    filled = Column(Integer, default=0)
    user = relationship("User_BD", back_populates="orders")


class Balance_BD(Base):
    __tablename__ = "balances"
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ticker = Column(String, ForeignKey("instruments.ticker"), primary_key=True)
    amount = Column(Integer, nullable=False, default=0)
    user = relationship("User_BD", back_populates="balances")


class Transaction_BD(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticker = Column(String, ForeignKey("instruments.ticker"), nullable=False)
    amount = Column(Integer, nullable=False)
    price = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)