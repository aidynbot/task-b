"""CRM SQLAlchemy models."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Manager(Base):
    __tablename__ = "managers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'no_answer', 'refused', 'meeting_set')",
            name="ck_companies_status",
        ),
        CheckConstraint("bin ~ '^[0-9]{12}$'", name="ck_companies_bin_format"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    bin: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", server_default="new"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'cancelled')", name="ck_meetings_status"
        ),
        CheckConstraint("end_time > start_time", name="ck_meetings_time_order"),
        ExcludeConstraint(
            ("manager_id", "="),
            (text("tstzrange(start_time, end_time, '[)')"), "&&"),
            where=text("status = 'scheduled'"),
            using="gist",
            name="ex_meetings_manager_time",
        ),
        Index(
            "uq_meetings_active_company",
            "company_id",
            unique=True,
            postgresql_where=text("status = 'scheduled'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("managers.id", ondelete="RESTRICT"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled", server_default="scheduled"
    )
    rescheduled_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        CheckConstraint(
            "result IN ('meeting_set', 'no_answer', 'refused')",
            name="ck_calls_result",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    manager_id: Mapped[int] = mapped_column(
        ForeignKey("managers.id", ondelete="RESTRICT"), nullable=False
    )
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    meeting_id: Mapped[int | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
