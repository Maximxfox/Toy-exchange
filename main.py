from fastapi import FastAPI
from models import *
from sqlalchemy import create_engine, Column, String, Enum, Uuid
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

app = FastAPI(title="Toy exchange", version="0.1.0")

@app.post("/api/v1/public/register",tags=["public"],
          summary="Register",
          description="Регистрация пользователя в платформе. Обязательна для совершения сделок",
          operation_id="register_api_v1_public_register_post",
          responses={
             422: {
                "description": "Validation Error",
                "model": HTTPValidationError
             }
          })
async def register_user(new_user: NewUser):
   user_id = uuid4()
   api_key = f"key-{uuid4()}"
   user = User(
      id=user_id,
      name=new_user.name,
      role=UserRole.USER,
      api_key=api_key
   )
   return user