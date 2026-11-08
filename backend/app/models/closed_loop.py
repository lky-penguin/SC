"""模型文件导出记录与本地安装标识。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InstallationIdentity(Base):
    """Stable origin namespace for packages exported by this C installation."""

    __tablename__ = "closed_loop_installation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelPackageExport(Base):
    """One immutable model-package export for a C model version."""

    __tablename__ = "closed_loop_model_package"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    model_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_version.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    dataset_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dataset.id"), nullable=False
    )
    package_path: Mapped[str] = mapped_column(String(255), nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    metadata_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    data_class: Mapped[str] = mapped_column(String(16), nullable=False)
    display_label: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="EXPORTED")
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    smoke_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

