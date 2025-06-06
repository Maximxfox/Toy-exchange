from typing import *
from pydantic import BaseModel, Field, constr
from enum import Enum
from uuid import UUID, uuid4
from datetime import datetime


class UserRole(str, Enum):
   USER = "USER"
   ADMIN = "ADMIN"


class Direction(str, Enum):
   BUY = "BUY"
   SELL = "SELL"


class OrderStatus(str, Enum):
   NEW = "NEW"
   EXECUTED = "EXECUTED"
   PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
   CANCELLED = "CANCELLED"


class Body_deposit_api_v1_admin_balance_deposit_post(BaseModel):
   user_id: UUID = Field(
      ...,
      title="User Id",
      examples=["35b0884d-9a1d-47b0-91c7-eecf0ca56bc8"]
   )
   ticker: str = Field(
      ...,
      title="Ticker",
      examples=["MEMCOIN"]
   )
   amount: int = Field(
      ...,
      gt=0,
      title="Amount"
   )


class Body_withdraw_api_v1_admin_balance_withdraw_post(BaseModel):
   user_id: UUID = Field(
      ...,
      title="User Id",
      examples=["35b0884d-9a1d-47b0-91c7-eecf0ca56bc8"]
   )
   ticker: str = Field(
      ...,
      title="Ticker",
      examples=["MEMCOIN"]
   )
   amount: int = Field(
      ...,
      gt=0,
      title="Amount"
   )


class CreateOrderResponse(BaseModel):
   success: Literal[True] = Field(True, title="Success")
   order_id: UUID = Field(..., title="Order Id", json_schema_extra={"format": "uuid4"})


class Instrument(BaseModel):
   name: str = Field(..., title="Name")
   ticker: constr(pattern=r"^[A-Z]{2,10}$") = Field(..., title="Ticker")


class Level(BaseModel):
   price: int = Field(..., title="Price")
   qty: int = Field(..., title="Qty")


class L2OrderBook(BaseModel):
   bid_levels: List[Level] = Field(..., title="Bid Levels")
   ask_levels: List[Level] = Field(..., title="Ask Levels")


class LimitOrderBody(BaseModel):
   direction: Direction
   ticker: str = Field(..., title="Ticker")
   qty: int = Field(..., ge=1, title="Qty")
   price: int = Field(..., gt=0, title="Price")


class LimitOrder(BaseModel):
   id: UUID = Field(..., title="Id", json_schema_extra={"format": "uuid4"})
   status: OrderStatus
   user_id: UUID = Field(..., title="User Id", json_schema_extra={"format": "uuid4"})
   timestamp: datetime = Field(..., title="Timestamp")
   body: LimitOrderBody
   filled: int = Field(0, title="Filled")


class MarketOrderBody(BaseModel):
   direction: Direction
   ticker: str = Field(..., title="Ticker")
   qty: int = Field(..., ge=1, title="Qty")


class MarketOrder(BaseModel):
   id: UUID = Field(..., title="Id", json_schema_extra={"format": "uuid4"})
   status: OrderStatus
   user_id: UUID = Field(..., title="User Id", json_schema_extra={"format": "uuid4"})
   timestamp: datetime = Field(..., title="Timestamp")
   body: MarketOrderBody


class NewUser(BaseModel):
   name:str = Field(..., min_length=3, title="Name")


class Ok(BaseModel):
   success: Literal[True] = Field(True, title="Success")


class Transaction(BaseModel):
   ticker: str = Field(..., title="Ticker")
   amount: int = Field(..., title="Amount")
   price: int = Field(..., title="Price")
   timestamp: datetime = Field(..., title="Timestamp")


class User(BaseModel):
   id: UUID = Field(..., title="Id", json_schema_extra={"format": "uuid4"})
   name: str = Field(..., title = 'Name')
   role: UserRole
   api_key: str = Field(..., title = 'Api Key')


class ValidationError(BaseModel):
   loc: List[Union[str, int]] = Field(..., title = 'Location')
   msg: str = Field(..., title = 'Message')
   type: str = Field(..., title = 'Error Type')


class HTTPValidationError(BaseModel):
   detail: List[ValidationError] = Field(
      default_factory=list,
      title="Detail"
   )
