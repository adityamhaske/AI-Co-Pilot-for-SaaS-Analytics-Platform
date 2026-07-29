from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def utcnow() -> datetime:
    """Timezone-aware UTC now. `datetime.utcnow` is deprecated from Python 3.12."""
    return datetime.now(UTC)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'viewer', 'analyst', 'admin'
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    segment = Column(String)  # e.g. 'enterprise', 'smb'
    created_at = Column(DateTime, default=utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    mrr = Column(Float, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)  # None means active
    status = Column(String, nullable=False)  # 'active', 'canceled'

    customer = relationship("Customer")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    amount = Column(Float, nullable=False)
    issue_date = Column(Date, nullable=False)
    status = Column(String, nullable=False)  # 'paid', 'unpaid'


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    event_type = Column(String, nullable=False)  # e.g. 'login', 'report_run'
    timestamp = Column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Conversations
#
# Without these the product was single-turn: every question started a fresh context, so
# "and how does that compare to last year?" had nothing to refer back to.
# ---------------------------------------------------------------------------


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False, default="New conversation")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.sequence",
    )

    # The sidebar lists a user's conversations newest-first; this is that query.
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, index=True)
    conversation_id = Column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised so a tenant filter never depends on joining through conversations.
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    role = Column(String, nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False, default="")
    #: JSON array of {name, input, data} recording which tools produced this answer.
    tool_calls = Column(Text, nullable=True)
    sequence = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conversation_sequence", "conversation_id", "sequence"),
    )


# ---------------------------------------------------------------------------
# Security and metering
# ---------------------------------------------------------------------------


class RefreshToken(Base):
    """One row per issued refresh token, so tokens can actually be revoked.

    Previously a refresh token was valid until it expired, with no way to invalidate it:
    signing out, a password change or a stolen cookie all left it working for seven days.
    """

    __tablename__ = "refresh_tokens"

    jti = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    issued_at = Column(DateTime, default=utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    #: Set when this token is rotated, so a replayed old token is detectable.
    replaced_by = Column(String, nullable=True)


class UsageRecord(Base):
    """Token spend per request, for per-user budgets and cost attribution."""

    __tablename__ = "usage_records"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=utcnow, index=True)

    __table_args__ = (Index("ix_usage_user_created", "user_id", "created_at"),)
