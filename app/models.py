from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class Login(Base):

    __tablename__ = "login"

    id = Column(Integer, primary_key=True, index=True)

    username = Column(String(100), unique=True, nullable=False)

    email = Column(String(255), unique=True, nullable=False)

    password_hash = Column(String(255), nullable=False)

    created_at = Column(DateTime)


class Users(Base):

    __tablename__ = "Users"

    user_id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    email = Column(String(255), unique=True, nullable=False)

    password_hash = Column(String(255), nullable=False)

    role = Column(String(50), default="student")

    created_at = Column(DateTime)

    # Optional profile fields (columns should exist in TiDB)
    phone = Column(String(50))

    bio = Column(String(500))


class UserProfile(Base):

    __tablename__ = "User_Profile"

    profile_id = Column(Integer, primary_key=True)

    user_id = Column(
        Integer,
        ForeignKey("Users.user_id", ondelete="CASCADE")
    )

    education = Column(String(500))

    experience_level = Column(String(50))

    domain_interest = Column(String(255))

    profile_completion_score = Column(Integer, default=0)


class Skills(Base):

    __tablename__ = "Skills"

    skill_id = Column(Integer, primary_key=True)

    skill_name = Column(String(100), unique=True)

    skill_type = Column(String(50))


class UserSkills(Base):

    __tablename__ = "User_Skills"

    user_id = Column(
        Integer,
        ForeignKey("Users.user_id", ondelete="CASCADE"),
        primary_key=True
    )

    skill_id = Column(
        Integer,
        ForeignKey("Skills.skill_id", ondelete="CASCADE"),
        primary_key=True
    )

    proficiency_level = Column(String(50))

    source = Column(String(50))


class UserCompanyRecord(Base):

    __tablename__ = "User_Company_Record"

    record_id = Column(Integer, primary_key=True)

    user_id = Column(
        Integer,
        ForeignKey("Users.user_id", ondelete="CASCADE")
    )

    company_name = Column(String(200))

    role_title = Column(String(200))

    match_score = Column(Integer)

    gap_severity = Column(String(50))

    application_status = Column(String(50))

    created_at = Column(DateTime)


class TrendingSkills(Base):

    __tablename__ = "Trending_Skills"

    skill_id = Column(
        Integer,
        ForeignKey("Skills.skill_id", ondelete="CASCADE"),
        primary_key=True
    )

    demand_score = Column(Integer)

    last_updated = Column(DateTime)