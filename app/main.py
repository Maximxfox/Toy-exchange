from fastapi import FastAPI, Depends, HTTPException, Header, Query, Path, Security
from fastapi.security import APIKeyHeader
from models import *
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, Session
from models_bd import Base, User_BD, Instrument_BD, Order_BD, Balance_BD, Transaction_BD
from models import (
    NewUser, User, Instrument, L2OrderBook, Transaction,
    LimitOrderBody, MarketOrderBody, LimitOrder, MarketOrder, CreateOrderResponse, Ok,
    Body_deposit_api_v1_admin_balance_deposit_post, Body_withdraw_api_v1_admin_balance_withdraw_post,
    HTTPValidationError, ValidationError, UserRole, Direction, OrderStatus
)


SQLALCHEMY_DATABASE_URL = "sqlite:///./toy_exchange.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_test_users(db: Session):
    if not db.query(User_BD).filter(User_BD.name == "testuser").first():
        test_user = User_BD(
            name="testuser",
            role=UserRole.USER,
            api_key="key-testuser-12345"
        )
        db.add(test_user)
        db.commit()
        db.refresh(test_user)
    if not db.query(User_BD).filter(User_BD.name == "adminuser").first():
        admin_user = User_BD(
            name="adminuser",
            role=UserRole.ADMIN,
            api_key="key-admin-67890"
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)


def create_user(db: Session, user: NewUser):
    db_user = User_BD(name=user.name, role=UserRole.USER, api_key=f"key-{uuid4()}")
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_instruments(db):
    return db.query(Instrument_BD).all()

def get_orderbook(db: Session, ticker: str, limit: int = 10):
    bids = db.query(Order_BD).filter(
        and_(Order_BD.ticker == ticker, Order_BD.direction == Direction.BUY, Order_BD.status != OrderStatus.CANCELLED)
    ).order_by(Order_BD.price.desc()).limit(limit).all()

    asks = db.query(Order_BD).filter(
        and_(Order_BD.ticker == ticker, Order_BD.direction == Direction.SELL, Order_BD.status != OrderStatus.CANCELLED)
    ).order_by(Order_BD.price.asc()).limit(limit).all()

    return {
        "bid_levels": [{"price": order.price, "qty": order.qty - order.filled} for order in bids if order.price],
        "ask_levels": [{"price": order.price, "qty": order.qty - order.filled} for order in asks if order.price]
    }

def get_transactions(db: Session, ticker: str, limit: int = 10):
    return db.query(Transaction_BD).filter(Transaction_BD.ticker == ticker).order_by(Transaction_BD.timestamp.desc()).limit(limit).all()


def _get_balances(db: Session, user_id: str):
    balances = db.query(Balance_BD).filter(Balance_BD.user_id == user_id).all()
    return {b.ticker: b.amount for b in balances}


def create_order(db: Session, user_id: str, order: Union[LimitOrderBody, MarketOrderBody]):
    db_order = Order_BD(
        user_id = user_id,
        ticker = order.ticker,
        direction = order.direction,
        qty = order.qty,
        price = order.price if isinstance(order, LimitOrderBody) else None,
        status = OrderStatus.NEW,
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order


def get_orders(db: Session, user_id: str):
    orders = db.query(Order_BD).filter(Order_BD.user_id == user_id).all()
    result = []
    for order in orders:
        if order.price is not None:
            body = LimitOrderBody(direction=order.direction, ticker=order.ticker, qty=order.qty, price=order.price)
            result.append(LimitOrder(id=order.id, status=order.status, user_id=order.user_id, timestamp=order.timestamp, body=body, filled=order.filled))
        else:
            body = MarketOrderBody(direction=order.direction, ticker=order.ticker, qty=order.qty)
            result.append(MarketOrder(id=order.id, status=order.status, user_id=order.user_id, timestamp=order.timestamp, body=body))
    return result


def get_order(db: Session, order_id: str):
    order = db.query(Order_BD).filter(Order_BD.id == order_id).first()
    if not order:
        return None
    if order.price is not None:
        body = LimitOrderBody(direction=order.direction, ticker=order.ticker, qty=order.qty, price=order.price)
        return LimitOrder(id=order.id, status=order.status, user_id=order.user_id, timestamp=order.timestamp, body=body, filled=order.filled)
    else:
        body = MarketOrderBody(direction=order.direction, ticker=order.ticker, qty=order.qty)
        return MarketOrder(id=order.id, status=order.status, user_id=order.user_id, timestamp=order.timestamp, body=body)


def cancel_order(db: Session, order_id: str):
    order = db.query(Order_BD).filter(Order_BD.id == order_id).first()
    if order:
        order.status = OrderStatus.CANCELLED
        db.commit()
        return True
    return False

def delete_user(db: Session, user_id: str):
    user = db.query(User_BD).filter(User_BD.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
        return user
    return None

def add_instrument(db: Session, instrument: Instrument):
    db_instrument = Instrument_BD(name=instrument.name, ticker=instrument.ticker)
    db.add(db_instrument)
    db.commit()
    return True

def delete_instrument(db: Session, ticker: str):
    instrument = db.query(Instrument_BD).filter(Instrument_BD.ticker == ticker).first()
    if instrument:
        db.delete(instrument)
        db.commit()
        return True
    return False

def deposit(db: Session, body: Body_deposit_api_v1_admin_balance_deposit_post):
    balance = db.query(Balance_BD).filter(
        and_(Balance_BD.user_id == str(body.user_id), Balance_BD.ticker == body.ticker)
    ).first()
    if balance:
        balance.amount += body.amount
    else:
        balance = Balance_BD(user_id=str(body.user_id), ticker=body.ticker, amount=body.amount)
        db.add(balance)
    db.commit()
    return True

def withdraw(db: Session, body: Body_withdraw_api_v1_admin_balance_withdraw_post):
    balance = db.query(Balance_BD).filter(
        and_(Balance_BD.user_id == str(body.user_id), Balance_BD.ticker == body.ticker)
    ).first()
    if balance and balance.amount >= body.amount:
        balance.amount -= body.amount
        db.commit()
        return True
    return False


app = FastAPI(title="Toy exchange", version="0.1.0")

@app.on_event("startup")
async def startup_event():
    db = SessionLocal()
    try:
        initialize_test_users(db)
    finally:
        db.close()


api_key_header = APIKeyHeader(name="Authorization")

def get_current_user(
    authorization: str = Security(api_key_header),
    db: Session = Depends(get_db)
):
    print(f"Received Authorization header: '{authorization}'")
    if not authorization or not authorization.startswith("TOKEN key"):
        raise HTTPException(status_code=401, detail="Недействительный ключ")
    api_key = authorization[6:]
    user = db.query(User_BD).filter(User_BD.api_key == api_key).first()
    if not user:
        raise HTTPException(status_code=401, detail="Нет пользователя")
    return user


@app.post("/api/v1/public/register", tags=["public"],
          summary="Register",
          description="Регистрация пользователя в платформе. Обязательна для совершения сделок",
          operation_id="register_api_v1_public_register_post",
          responses={
              200: {"description": "Successful Response", "model": User},
              422: {"description": "Validation Error", "model": HTTPValidationError}
          })
async def register(user: NewUser, db: Session = Depends(get_db)):
    return User.from_orm(create_user(db, user))


@app.get("/api/v1/public/instrument",tags=["public"],
         summary="List Instruments",
         description="Список доступных инструментов",
         operation_id="list_instruments_api_v1_public_instrument_get",
         response_model=List[Instrument],
         responses={
             200: {"description": "Successful Response", "model": List[Instrument]},
         })
async def list_instruments(db: Session = Depends(get_db)):
    return [Instrument.from_orm(i) for i in get_instruments(db)]


@app.get("/api/v1/public/orderbook/{ticker}",tags=["public"],
         summary="Get Orderbook",
         description="Текущие заявки",
         operation_id="get_orderbook_api_v1_public_orderbook__ticker__get",
         response_model=L2OrderBook,
         responses={
             200: {"description": "Successful Response", "model": L2OrderBook},
             422: {"description": "Validation Error", "model": HTTPValidationError}
         })
async def get_orderbook(ticker: str, limit: int = Query(10, le=25), db: Session = Depends(get_db)):
    return get_orderbook(db, ticker, limit)



@app.get(
    "/api/v1/public/transactions/{ticker}",
    tags=["public"],
    summary="Get Transaction History",
    description="История сделок",
    operation_id="get_transaction_history_api_v1_public_transactions__ticker__get",
    response_model=List[Transaction],
    responses={
        200: {"description": "Successful Response", "model": List[Transaction]},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def get_transaction_history(ticker: str, limit: int = Query(10, le=100), db: Session = Depends(get_db)):
    return get_transactions(db, ticker, limit)


@app.get("/api/v1/balance", tags=["balance"],
         summary="Get Balances",
         operation_id="get_balances_api_v1_balance_get",
         response_model=Dict[str, int],
         responses={
             200: {
                 "description": "Successful Response",
                 "additionalProperties": {"type": "integer"},
                 "example": {
                    "MEMCOIN": 0,
                    "DODGE": 100500
                 }
             },
             422: {"description": "Validation Error", "model": HTTPValidationError}
         })
async def get_balances(current_user: User = Security(get_current_user), db: Session = Depends(get_db)):
    return _get_balances(db, str(current_user.id))


@app.post(
    "/api/v1/order",
    tags=["order"],
    summary="Create Order",
    operation_id="create_order_api_v1_order_post",
    response_model=CreateOrderResponse,
    responses={
        200: {"description": "Successful Response", "model": CreateOrderResponse},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def create_order(
    order: Union[LimitOrderBody, MarketOrderBody],
    current_user: User = Security(get_current_user),
    db: Session = Depends(get_db)
):
    db_order = create_order(db, str(current_user.id), order)
    return CreateOrderResponse(order_id=db_order.id)

@app.get(
"/api/v1/order",
    tags=["order"],
    summary="List Orders",
    operation_id="list_orders_api_v1_order_get",
    response_model=List[Union[LimitOrder, MarketOrder]],
    responses={
        200: {"description": "Successful Response", "model": List[Union[LimitOrder, MarketOrder]]},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def list_order(db: Session = Depends(get_db), current_user: User = Security(get_current_user)):
    return get_orders(db, str(current_user.id))



@app.get(
    "/api/v1/order/{order_id}",
    tags=["order"],
    summary="Get Order",
    description="Получение информации об ордере",
    operation_id="get_order_api_v1_order__order_id__get",
    response_model=Union[LimitOrder, MarketOrder],
    responses={
        200: {"description": "Successful Response", "model": Union[LimitOrder, MarketOrder]},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def get_order(order_id: str, current_user: User = Security(get_current_user), db: Session = Depends(get_db)):
    order = get_order(db, order_id)
    if not order or order.user_id != str(current_user.id):
        raise HTTPException(status_code=404, detail=HTTPValidationError(detail=[ValidationError(loc="order_id", msg="Order not found", type="value_error")]).dict())
    return order

@app.delete(
    "/api/v1/order/{order_id}",
    tags=["order"],
    summary="Cancel Order",
    operation_id="cancel_order_api_v1_order__order_id__delete",
    response_model=Ok,
    responses={
        200: {"description": "Successful Response", "model": Ok},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def cancel_order(order_id: str = Path(..., format="uuid4"), current_user: User = Security(get_current_user), db: Session = Depends(get_db)):
    if not cancel_order(db, order_id):
        raise HTTPException(status_code=404, detail=HTTPValidationError(detail=[ValidationError(loc="order_id", msg="Order not found", type="value_error")]).dict())
    return Ok

@app.delete(
    "/api/v1/admin/user/{user_id}",
    tags=["admin", "user"],
    summary="Delete User",
    operation_id="delete_user_api_v1_admin_user__user_id__delete",
    response_model=User,
    responses={
        200: {"description": "Successful Response", "model": User},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def delete_user(user_id: str = Path(..., format="uuid4"), current_user: User = Security(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc="authorization", msg="Admin access required", type="permission_error")]).dict())
    user = delete_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail=HTTPValidationError(detail=[ValidationError(loc="user_id", msg="User not found", type="value_error")]).dict())
    return user

@app.post(
    "/api/v1/admin/instrument",
    tags=["admin"],
    summary="Add Instrument",
    operation_id="add_instrument_api_v1_admin_instrument_post",
    response_model=Ok,
    responses={
        200: {"description": "Successful Response", "model": Ok},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def add_instrument(
    instrument: Instrument,
    current_user: User = Security(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc="authorization", msg="Admin access required", type="permission_error")]).dict())
    add_instrument(db, instrument)
    return Ok()

@app.delete(
    "/api/v1/admin/instrument/{ticker}",
    tags=["admin"],
    summary="Delete Instrument",
    description="Удаление инструмента",
    operation_id="delete_instrument_api_v1_admin_instrument__ticker__delete",
    response_model=Ok,
    responses={
        200: {"description": "Successful Response", "model": Ok},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def delete_instrument(ticker: str, current_user: User = Security(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc="authorization", msg="Admin access required", type="permission_error")]).dict())
    if not delete_instrument(db, ticker):
        raise HTTPException(status_code=404, detail=HTTPValidationError(detail=[ValidationError(loc="ticker", msg="Instrument not found", type="value_error")]).dict())
    return Ok

@app.post(
    "/api/v1/admin/balance/deposit",
    tags=["admin", "balance"],
    summary="Deposit",
    description="Пополнение баланса",
    operation_id="deposit_api_v1_admin_balance_deposit_post",
    response_model=Ok,
    responses={
        200: {"description": "Successful Response", "model": Ok},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def deposit_balance(
    body: Body_deposit_api_v1_admin_balance_deposit_post,
    current_user: User = Security(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc="authorization", msg="Admin access required", type="permission_error")]).dict())
    deposit(db, body)
    return Ok()

@app.post(
    "/api/v1/admin/balance/withdraw",
    tags=["admin", "balance"],
    summary="Withdraw",
    description="Вывод доступных средств с баланса",
    operation_id="withdraw_api_v1_admin_balance_withdraw_post",
    response_model=Ok,
    responses={
        200: {"description": "Successful Response", "model": Ok},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def withdraw_balance(
    body: Body_withdraw_api_v1_admin_balance_withdraw_post,
    current_user: User = Security(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc="authorization", msg="Admin access required", type="permission_error")]).dict())
    if not withdraw(db, body):
        raise HTTPException(status_code=400, detail=HTTPValidationError(detail=[ValidationError(loc="amount", msg="Insufficient balance", type="value_error")]).dict())
    return Ok