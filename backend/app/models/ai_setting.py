"""个人本地 AI 供应商配置（单例）。

API key 加密落库，任何时候都不序列化进客户端响应。
"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AISetting(Base):
    __tablename__ = "ai_setting"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openai-compatible")
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
