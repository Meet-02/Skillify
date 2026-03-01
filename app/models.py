from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base


class Login(Base):
    __tablename__ = "login"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True)
    email = Column(String(255), unique=True)
    password_hash = Column(String(255))
    created_at = Column(DateTime)

class Users(Base):
    __tablename__ = "Users"

    user_id = Column(Integer, primary_key=True)
    name = Column(String(255))
    email = Column(String(255))
    password_hash = Column(String(255))
    role = Column(String(50))
    created_at = Column(DateTime)


class UserProfile(Base):
    __tablename__ = "User_Profile"

    profile_id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    education = Column(String(255))
    experience_level = Column(String(255))
    domain_interest = Column(String(255))
    profile_completion_score = Column(Integer)


class Skills(Base):
    __tablename__ = "Skills"

    skill_id = Column(Integer, primary_key=True)
    skill_name = Column(String(255))
    skill_type = Column(String(255))


class UserSkills(Base):
    __tablename__ = "User_Skills"

    user_id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, primary_key=True)
    proficiency_level = Column(String(50))
    source = Column(String(50))