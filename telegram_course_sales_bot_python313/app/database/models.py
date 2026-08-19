"""
SQLAlchemy 2.0 Async Models Definition
Includes Users, Courses, Lessons, Categories, Orders, Payments, PromoCodes, Referrals, Settings, Broadcasts, Admins.
"""
from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional
from sqlalchemy import (
    BigInteger, String, Text, Integer, Float, Boolean, DateTime,
    ForeignKey, Enum, Numeric, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LessonType(str, PyEnum):
    VIDEO = "video"
    PDF = "pdf"
    TEXT = "text"
    HOMEWORK = "homework"


class PaymentMethod(str, PyEnum):
    PAYME = "payme"
    CLICK = "click"
    ADMIN_GRANT = "admin_grant"
    BALANCE = "balance"


class OrderStatus(str, PyEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    balance_uzs: Mapped[int] = mapped_column(BigInteger, default=0)
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    referred_by: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="ru")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    orders: Mapped[List["Order"]] = relationship("Order", back_populates="user")
    purchases: Mapped[List["UserCourseAccess"]] = relationship("UserCourseAccess", back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    courses: Mapped[List["Course"]] = relationship("Course", back_populates="category")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(256), unique=True, index=True, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    price_uzs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    old_price_uzs: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    author: Mapped[str] = mapped_column(String(128), default="Instructor")
    telegram_channel_title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    telegram_channel_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    has_tiers: Mapped[bool] = mapped_column(Boolean, default=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    category: Mapped["Category"] = relationship("Category", back_populates="courses")
    lessons: Mapped[List["Lesson"]] = relationship("Lesson", back_populates="course", cascade="all, delete-orphan")
    tiers: Mapped[List["CourseTier"]] = relationship("CourseTier", back_populates="course", cascade="all, delete-orphan")


class CourseTier(Base):
    __tablename__ = "course_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_uzs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    old_price_uzs: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    course: Mapped["Course"] = relationship("Course", back_populates="tiers")


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    order_num: Mapped[int] = mapped_column(Integer, default=1)
    type: Mapped[LessonType] = mapped_column(Enum(LessonType), default=LessonType.TEXT)
    content: Mapped[str] = mapped_column(Text, default="")
    video_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    homework_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    course: Mapped["Course"] = relationship("Course", back_populates="lessons")


class UserCourseAccess(Base):
    __tablename__ = "user_course_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    tier_title: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    granted_by: Mapped[str] = mapped_column(String(64), default="payment") # "payment" or "admin_manual"

    user: Mapped["User"] = relationship("User", back_populates="purchases")
    course: Mapped["Course"] = relationship("Course")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    tier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tier_title: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    amount_uzs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    promo_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")
    course: Mapped["Course"] = relationship("Course")


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    discount_percent: Mapped[int] = mapped_column(Integer, default=10)
    max_uses: Mapped[int] = mapped_column(Integer, default=100)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    source: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
