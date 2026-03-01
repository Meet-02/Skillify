from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base


class Login(Base):
    __tablename__ = "login"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True)
    email = Column(String(255), unique=True)
    password_hash = Column(String(255))
    created_at = Column(DateTime)