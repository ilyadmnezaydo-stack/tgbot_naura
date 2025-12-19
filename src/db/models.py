import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)  # Telegram user_id
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    language_code = Column(String(10), default="ru")
    timezone = Column(String(50), default="Europe/Moscow")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contacts = relationship(
        "Contact", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    username = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(ARRAY(Text), default=[])
    reminder_frequency = Column(
        String(50), default="biweekly"
    )  # daily, weekly, biweekly, monthly, custom, one_time
    custom_interval_days = Column(Integer, nullable=True)
    next_reminder_date = Column(Date, nullable=True)
    last_contacted_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="active")  # active, paused, one_time
    one_time_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = relationship("User", back_populates="contacts")
    history = relationship(
        "ContactHistory", back_populates="contact", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "username", name="unique_user_contact"),
        CheckConstraint(
            "status IN ('active', 'paused', 'one_time')", name="check_status"
        ),
    )

    def __repr__(self) -> str:
        return f"<Contact(id={self.id}, username={self.username}, status={self.status})>"


class ContactHistory(Base):
    __tablename__ = "contact_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    action = Column(
        String(50), nullable=False
    )  # contacted, reminder_sent, paused, resumed
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    contact = relationship("Contact", back_populates="history")

    def __repr__(self) -> str:
        return f"<ContactHistory(id={self.id}, action={self.action})>"
