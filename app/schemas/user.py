from pydantic import BaseModel, EmailStr
from typing import Optional


class UserRegister(BaseModel):
    fullname: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


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
        from_attributes = True
