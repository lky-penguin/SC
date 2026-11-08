"""模型版本表 model_version —— 记录每次训练生成的本地模型版本。"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.algorithm import Algorithm
    from app.models.dataset import Dataset


class ModelVersion(Base):
    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dataset.id"), nullable=False
    )
    algorithm_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("algorithm.id"), nullable=False
    )
    training_parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evaluation_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 模型级解释事实与 AI 措辞缓存；个人版只保留 current 一个键。
    model_attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_evaluation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    dataset: Mapped["Dataset"] = relationship(back_populates="model_versions")
    algorithm: Mapped["Algorithm"] = relationship(back_populates="model_versions")
