"""数据库查询结果的通用序列化工具。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

_CST = ZoneInfo("Asia/Shanghai")


def paginate(
    db: Session,
    stmt,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """执行 SQLAlchemy select 分页，返回统一的分页字典。"""
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 10)), 200)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def to_beijing(value: datetime) -> datetime:
    """把 datetime 统一归到北京时间（UTC+8）。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=_CST)
    return value.astimezone(_CST)


def row_to_dict(obj: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    """把 ORM 行转换为可 JSON 序列化的字典。"""
    result: dict[str, Any] = {}
    for column in obj.__table__.columns:
        name = column.name
        if name in exclude:
            continue
        value = getattr(obj, name)
        if isinstance(value, datetime):
            value = to_beijing(value).strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, Decimal):
            value = float(value)
        result[name] = value
    return result
