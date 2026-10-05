from sqlalchemy import CheckConstraint, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrderNumberCounter(Base):
    __tablename__ = "order_number_counters"
    __table_args__ = (
        CheckConstraint("year BETWEEN 1 AND 9999", name="year_range"),
        CheckConstraint("last_value >= 0", name="last_value_nonnegative"),
    )

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
