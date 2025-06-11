import logging
from fastapi import FastAPI, Depends, HTTPException, Header, Query, Path, Body
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


logging.basicConfig(
    level=logging.DEBUG,
    format="[%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)
SQLALCHEMY_DATABASE_URL = "sqlite:///./toy_exchange.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_test_users(db: Session):
    logger.info("Initializing test users")
    if not db.query(User_BD).filter(User_BD.name == "testuser").first():
        test_user = User_BD(
            id = "358243f5-7e6c-4eb7-b9c3-df6ce49bf5ce",
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
    logger.info(f"Creating user with name: {user.name}")
    db_user = User_BD(name=user.name, role=UserRole.USER, api_key=f"key-{uuid4()}")
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_instruments(db):
    logger.info("Fetching all instruments")
    return db.query(Instrument_BD).all()

def get_orderbook(db: Session, ticker: str, limit: int):
    logger.info(f"Fetching order book for ticker: {ticker}, limit: {limit}")
    bids = db.query(Order_BD).filter(
        and_(
            Order_BD.ticker == ticker,
            Order_BD.direction == Direction.BUY,
            Order_BD.status.notin_([OrderStatus.CANCELLED, OrderStatus.EXECUTED]),
            Order_BD.qty > Order_BD.filled
        )
    ).order_by(Order_BD.price.desc()).limit(limit).all()

    asks = db.query(Order_BD).filter(
        and_(
            Order_BD.ticker == ticker,
            Order_BD.direction == Direction.SELL,
            Order_BD.status.notin_([OrderStatus.CANCELLED, OrderStatus.EXECUTED]),
            Order_BD.qty > Order_BD.filled
        )
    ).order_by(Order_BD.price.asc()).limit(limit).all()

    logger.debug(f"Raw bids: {[order.__dict__ for order in bids]}")
    logger.debug(f"Raw asks: {[order.__dict__ for order in asks]}")

    return {
        "bid_levels": [{"price": order.price, "qty": order.qty - order.filled} for order in bids if order.price],
        "ask_levels": [{"price": order.price, "qty": order.qty - order.filled} for order in asks if order.price]
    }

def get_transactions(db: Session, ticker: str, limit: int):
    logger.info(f"Fetching transactions for ticker: {ticker}, limit: {limit}")
    return db.query(Transaction_BD).filter(Transaction_BD.ticker == ticker).order_by(Transaction_BD.timestamp.desc()).limit(limit).all()


def _get_balances(db: Session, user_id: str):
    logger.info(f"Fetching balances for user ID: {user_id}")
    balances = db.query(Balance_BD).filter(Balance_BD.user_id == user_id).all()
    return {b.ticker: b.amount for b in balances}


def update_balance(db: Session, user_id: str, ticker: str, amount: int):
    logger.info(f"Updating balance for user {user_id}, ticker {ticker}, amount {amount}")
    balance = db.query(Balance_BD).filter(
        and_(Balance_BD.user_id == user_id, Balance_BD.ticker == ticker)
    ).first()
    if balance:
        balance.amount += amount
    else:
        balance = Balance_BD(user_id=user_id, ticker=ticker, amount=amount)
        db.add(balance)
    db.commit()


def execute_order(db: Session, new_order: Order_BD):
    logger.info(f"Executing order ID: {new_order.id}, ticker: {new_order.ticker}, direction: {new_order.direction}, qty: {new_order.qty}, price: {new_order.price}")
    if new_order.status == OrderStatus.CANCELLED or new_order.status == OrderStatus.EXECUTED:
        return
    opposite_direction = Direction.SELL if new_order.direction == Direction.BUY else Direction.BUY
    price_condition = (Order_BD.price <= new_order.price if new_order.direction == Direction.BUY else Order_BD.price >= new_order.price) \
        if new_order.price else True
    order_by = Order_BD.price.asc() if new_order.direction == Direction.BUY else Order_BD.price.desc()
    matching_orders = (db.query(Order_BD).filter(and_(
                Order_BD.ticker == new_order.ticker,
                Order_BD.direction == opposite_direction,
                Order_BD.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                price_condition
            )
    ).order_by(order_by).all())
    remaining_qty = new_order.qty - new_order.filled
    for match_order in matching_orders:
        if remaining_qty <= 0:
            break
        price = new_order.price if new_order.price else match_order.price
        logger.debug(f"Matching with order ID: {match_order.id}, price: {price}")
        match_available = match_order.qty - match_order.filled
        matched_qty = min(remaining_qty, match_available)
        logger.debug(f"Matched qty: {matched_qty}, new_order.filled: {new_order.filled}, match_order.filled: {match_order.filled}")
        new_order.filled += matched_qty
        match_order.filled += matched_qty
        new_order.status = (
            OrderStatus.EXECUTED if new_order.filled == new_order.qty else OrderStatus.PARTIALLY_EXECUTED
        )
        match_order.status = (
            OrderStatus.EXECUTED if match_order.filled == match_order.qty else OrderStatus.PARTIALLY_EXECUTED
        )
        transaction = Transaction_BD(
            ticker=new_order.ticker,
            amount=matched_qty,
            price=price,
            timestamp=datetime.utcnow()
        )
        db.add(transaction)
        if new_order.direction == Direction.BUY:
            update_balance(db, new_order.user_id, "RUB", -matched_qty * price)
            update_balance(db, new_order.user_id, new_order.ticker, matched_qty)
            update_balance(db, match_order.user_id, "RUB", matched_qty * price)
            update_balance(db, match_order.user_id, new_order.ticker, -matched_qty)
        else:
            update_balance(db, new_order.user_id, "RUB", matched_qty * price)
            update_balance(db, new_order.user_id, new_order.ticker, -matched_qty)
            update_balance(db, match_order.user_id, "RUB", -matched_qty * price)
            update_balance(db, match_order.user_id, new_order.ticker, matched_qty)
        remaining_qty -= matched_qty
    db.commit()


def create_order(db: Session, user_id: str, order: Union[LimitOrderBody, MarketOrderBody]):
    if not db.query(Instrument_BD).filter(Instrument_BD.ticker == order.ticker).first():
        raise HTTPException(
            status_code=400,
            detail=HTTPValidationError(detail=[ValidationError(loc=["ticker"], msg="Instrument not found", type="value_error")])
        )
    user_balances = _get_balances(db, user_id)
    if order.direction == Direction.BUY:
        if isinstance(order, LimitOrderBody):
            required_rub = order.qty * order.price
            if user_balances.get("RUB", 0) < required_rub:
                raise HTTPException(
                    status_code=400,
                    detail=HTTPValidationError(detail=[ValidationError(loc=["balance"], msg="Insufficient RUB balance", type="value_error")])
                )
        else:
            pass
    else:
        if user_balances.get(order.ticker, 0) < order.qty:
            raise HTTPException(
                status_code=400,
                detail=HTTPValidationError(detail=[ValidationError(loc=["balance"], msg=f"Insufficient {order.ticker} balance", type="value_error")])
            )
    db_order = Order_BD(
        user_id=user_id,
        ticker=order.ticker,
        direction=order.direction,
        qty=order.qty,
        price=order.price if isinstance(order, LimitOrderBody) else None,
        status=OrderStatus.NEW,
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    execute_order(db, db_order)
    return db_order


def get_orders(db: Session, user_id: str):
    logger.info(f"Retrieved orders for user {user_id}")
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
    logger.info(f"Retrieved order {order_id}")
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
    logger.info(f"Cancelled order {order_id}")
    order = db.query(Order_BD).filter(Order_BD.id == order_id).first()
    if order:
        order.status = OrderStatus.CANCELLED
        db.commit()
        return True
    logger.warning(f"Order {order_id} not found for cancellation")
    return False

def delete_user(db: Session, user_id: str):
    logger.info(f"Deleted user {user_id}")
    user = db.query(User_BD).filter(User_BD.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
        return user
    logger.warning(f"User {user_id} not found for deletion")
    return None

def add_instrument(db: Session, instrument: Instrument):
    logger.info(f"Added instrument {instrument.ticker}")
    db_instrument = Instrument_BD(name=instrument.name, ticker=instrument.ticker)
    db.add(db_instrument)
    db.commit()
    return True

def delete_instrument(db: Session, ticker: str):
    logger.info(f"Deleted instrument {ticker}")
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
        logger.info(f"Updated balance for user {body.user_id}, ticker {body.ticker} by {body.amount}")
    else:
        balance = Balance_BD(user_id=str(body.user_id), ticker=body.ticker, amount=body.amount)
        db.add(balance)
        logger.info(f"Created new balance for user {body.user_id}, ticker {body.ticker} with {body.amount}")
    db.commit()
    return True

def withdraw(db: Session, body: Body_withdraw_api_v1_admin_balance_withdraw_post):
    balance = db.query(Balance_BD).filter(
        and_(Balance_BD.user_id == str(body.user_id), Balance_BD.ticker == body.ticker)
    ).first()
    if balance and balance.amount >= body.amount:
        balance.amount -= body.amount
        db.commit()
        logger.info(f"Withdrew {body.amount} {body.ticker} from user {body.user_id}")
        return True
    logger.warning(f"Insufficient balance for withdrawal: user {body.user_id}, ticker {body.ticker}, requested {body.amount}")
    return False


app = FastAPI(title="Toy exchange", version="0.1.0")

@app.on_event("startup")
async def startup_event():
    logger.info("Starting FastAPI application")
    db = SessionLocal()
    try:
        initialize_test_users(db)
    finally:
        db.close()


def get_current_user(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("TOKEN key"):
        logger.warning("Invalid or missing Authorization header")
        raise HTTPException(
            status_code=401,
            detail=HTTPValidationError(detail=[ValidationError(loc=["authorization"],msg="Недействительный ключ",type="value_error")]).dict()
        )
    api_key = authorization[6:]
    user = db.query(User_BD).filter(User_BD.api_key == api_key).first()
    logger.info(f"Authenticated user: {user.name} (ID: {user.id})")
    if not user:
        logger.warning(f"No user found for API key: {api_key}")
        raise HTTPException(
            status_code=401,
            detail=HTTPValidationError(detail=[ValidationError(loc=["authorization"],msg="Нет пользователя",type="value_error")]).dict()
        )
    return user


@app.post("/api/v1/public/register", tags=["public"],
          summary="Register",
          description='''Регистрация пользователя в платформе. Обязательна для совершения сделок\napi_key полученный из этого метода следует передавать в другие через заголовок Authorization\n\nНапример для api_key='key-bee6de4d-7a23-4bb1-a048-523c2ef0ea0c` знаначение будет таким:\n\nAuthorization: TOKEN key-bee6de4d-7a23-4bb1-a048-523c2ef0ea0c''',
          operation_id="register_api_v1_public_register_post",
          responses={
              200: {"description": "Successful Response", "model": User},
              422: {"description": "Validation Error", "model": HTTPValidationError}
          })
async def register(user: NewUser, db: Session = Depends(get_db)):
    logger.info(f"Register endpoint called for user: {user.name}")
    return create_user(db, user)


@app.get("/api/v1/public/instrument",tags=["public"],
         summary="List Instruments",
         description="Список доступных инструментов",
         operation_id="list_instruments_api_v1_public_instrument_get",
         response_model=List[Instrument],
         responses={
             200: {"description": "Successful Response", "model": List[Instrument]},
         })
async def list_instruments(db: Session = Depends(get_db)):
    logger.info("List instruments endpoint called")
    return get_instruments(db)


@app.get("/api/v1/public/orderbook/{ticker}",tags=["public"],
         summary="Get Orderbook",
         description="Текущие заявки",
         operation_id="get_orderbook_api_v1_public_orderbook__ticker__get",
         response_model=L2OrderBook,
         responses={
             200: {"description": "Successful Response", "model": L2OrderBook},
             422: {"description": "Validation Error", "model": HTTPValidationError}
         })
async def get_orderbook_endpoint(ticker: str, limit: int = Query(10, le=25), db: Session = Depends(get_db)):
    logger.info(f"Orderbook endpoint called for ticker: {ticker}, limit: {limit}")
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
    logger.info(f"Transaction history endpoint called for ticker: {ticker}, limit: {limit}")
    return get_transactions(db, ticker, limit)


@app.get(
    "/api/v1/balance",
    tags=["balance"],
    summary="Get Balances",
    operation_id="get_balances_api_v1_balance_get",
    response_model=Dict[str, int],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "example": {
                        "MEMCOIN": 0,
                        "DODGE": 100500
                    }
                }
            }
        },
        422: {
            "description": "Validation Error",
            "model": HTTPValidationError
        }
    }
)

async def get_balances(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    logger.info(f"Get balances endpoint called for user: {current_user.id}")
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
async def create_order_endpoint(
    order: Union[LimitOrderBody, MarketOrderBody] = Body(..., title="Body"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    logger.info(f"Create order endpoint called for user: {current_user.id}, ticker: {order.ticker}")
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
async def list_order(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    logger.info(f"List orders endpoint called for user: {current_user.id}")
    return get_orders(db, str(current_user.id))



@app.get(
    "/api/v1/order/{order_id}",
    tags=["order"],
    summary="Get Order",
    operation_id="get_order_api_v1_order__order_id__get",
    response_model=Union[LimitOrder, MarketOrder],
    responses={
        200: {"description": "Successful Response", "model": Union[LimitOrder, MarketOrder]},
        422: {"description": "Validation Error", "model": HTTPValidationError}
    }
)
async def get_order_endpoint(
    order_id: str = Path(..., title="Order Id", format="uuid4"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    order = get_order(db, order_id)
    logger.info(f"Get order endpoint called for order: {order_id}, user: {current_user.id}")
    if not order or order.user_id != str(current_user.id):
        logger.warning(f"Order {order_id} not found or not owned by user {current_user.id}")
        raise HTTPException(status_code=404, detail=HTTPValidationError(detail=[ValidationError(loc=["order_id"], msg="Order not found", type="value_error")]).dict())
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
async def cancel_order_endpoint(order_id: str = Path(..., format="uuid4"), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    logger.info(f"Cancel order endpoint called for order: {order_id}, user: {current_user.id}")
    if not cancel_order(db, order_id):
        logger.warning(f"Order {order_id} not found for cancellation")
        raise HTTPException(status_code=404, detail=HTTPValidationError(detail=[ValidationError(loc=["order_id"], msg="Order not found", type="value_error")]).dict())
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
async def delete_user_endpoint(user_id: str = Path(..., format="uuid4"), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    logger.info(f"Delete user endpoint called for user: {user_id}, by admin: {current_user.id}")
    if current_user.role != UserRole.ADMIN:
        logger.warning(f"Non-admin user {current_user.id} attempted to delete user {user_id}")
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc=["authorization"], msg="Admin access required", type="permission_error")]).dict())
    user = delete_user(db, user_id)
    if not user:
        logger.warning(f"User {user_id} not found for deletion")
        raise HTTPException(status_code=404, detail=HTTPValidationError(detail=[ValidationError(loc=["user_id"], msg="User not found", type="value_error")]).dict())
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
async def add_instrument_endpoint(
    instrument: Instrument,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    logger.info(f"Add instrument endpoint called for ticker: {instrument.ticker}, by user: {current_user.id}")
    if current_user.role != UserRole.ADMIN:
        logger.warning(f"Non-admin user {current_user.id} attempted to add instrument {instrument.ticker}")
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc=["authorization"], msg="Admin access required", type="permission_error")]).dict())
    add_instrument(db, instrument)
    return Ok

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
async def delete_instrument_endpoint(
    ticker: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.info(f"Delete instrument endpoint called for ticker: {ticker}, by user: {current_user.id}")
    if current_user.role != UserRole.ADMIN:
        logger.warning(f"Non-admin user {current_user.id} attempted to delete instrument {ticker}")
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc=["authorization"], msg="Admin access required", type="permission_error")]).dict())
    if not delete_instrument(db, ticker):
        logger.warning(f"Instrument {ticker} not found for deletion")
        raise HTTPException(status_code=404, detail=HTTPValidationError(detail=[ValidationError(loc=["ticker"], msg="Instrument not found", type="value_error")]).dict())
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    logger.info(f"Deposit endpoint called for user: {body.user_id}, ticker: {body.ticker}, amount: {body.amount}, by admin: {current_user.id}")
    if current_user.role != UserRole.ADMIN:
        logger.warning(f"Non-admin user {current_user.id} attempted to deposit for user {body.user_id}")
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc=["authorization"], msg="Admin access required", type="permission_error")]).dict())
    deposit(db, body)
    return Ok

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    logger.info(f"Withdraw endpoint called for user: {body.user_id}, ticker: {body.ticker}, amount: {body.amount}, by admin: {current_user.id}")
    if current_user.role != UserRole.ADMIN:
        logger.warning(f"Non-admin user {current_user.id} attempted to withdraw for user {body.user_id}")
        raise HTTPException(status_code=403, detail=HTTPValidationError(detail=[ValidationError(loc=["authorization"], msg="Admin access required", type="permission_error")]).dict())
    if not withdraw(db, body):
        logger.warning(f"Insufficient balance for withdrawal: user {body.user_id}, ticker {body.ticker}, amount {body.amount}")
        raise HTTPException(status_code=400, detail=HTTPValidationError(detail=[ValidationError(loc=["amount"], msg="Insufficient balance", type="value_error")]).dict())
    return Ok