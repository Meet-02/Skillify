from pydantic import BaseModel, EmailStr
from typing import Optional


# -----------------------------
# Register Schema (Input)
# -----------------------------
class UserRegister(BaseModel):
    fullname: str
    email: EmailStr
    password: str


# -----------------------------
# Login Schema (Input)
# -----------------------------
class UserLogin(BaseModel):
    email: EmailStr
    password: str


# -----------------------------
# User Response Schema (Output)
# -----------------------------
class UserResponse(BaseModel):
    id: int
    fullname: str
    email: EmailStr
    profile_pic: Optional[str] = None
    phone_number: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None

class UserProfileUpdate(BaseModel):
    fullname: Optional[str] = None
    phone_number: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None

    class Config:
        from_attributes = True   # For SQLAlchemy compatibility
