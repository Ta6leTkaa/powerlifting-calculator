from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("sex IN ('male', 'female')"),
        CheckConstraint("bodyweight > 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    nickname: Mapped[str] = mapped_column(String(64))
    sex: Mapped[str] = mapped_column(String(10))
    bodyweight: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LiftResult(Base):
    __tablename__ = "lift_results"
    __table_args__ = (
        UniqueConstraint("user_id", "submission_key"),
        UniqueConstraint("total_result_id", "movement", name="uq_lift_total_movement"),
        CheckConstraint("movement IN ('bench', 'squat', 'deadlift')"),
        CheckConstraint("lifted > 0 AND bodyweight > 0"),
        CheckConstraint("sex IN ('male', 'female')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    total_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("total_results.id", ondelete="CASCADE", name="fk_lift_total_result"),
        nullable=True,
    )
    movement: Mapped[str] = mapped_column(String(16))
    lifted: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    bodyweight: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    sex: Mapped[str] = mapped_column(String(10))
    formula_version: Mapped[str] = mapped_column(String(32))
    performed_on: Mapped[date] = mapped_column(Date)
    submission_key: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TotalResult(Base):
    """A complete three-lift performance on one date, with one weigh-in."""

    __tablename__ = "total_results"
    __table_args__ = (
        UniqueConstraint("user_id", "submission_key"),
        CheckConstraint("squat > 0 AND bench > 0 AND deadlift > 0 AND bodyweight > 0"),
        CheckConstraint("sex IN ('male', 'female')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    squat: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    bench: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    deadlift: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    bodyweight: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    sex: Mapped[str] = mapped_column(String(10))
    formula_version: Mapped[str] = mapped_column(String(32))
    performed_on: Mapped[date] = mapped_column(Date)
    submission_key: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    @property
    def lifted(self):
        return self.squat + self.bench + self.deadlift

    @property
    def movement(self):
        return "total"
