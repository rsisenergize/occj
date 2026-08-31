from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import UserRole
from app.models.mixins import IdMixin, TimestampMixin, enum_column


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[UserRole] = enum_column(UserRole)
    display_name: Mapped[str] = mapped_column(String(128))
