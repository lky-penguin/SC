"""Service 公共基类；个人本地版不含账号、角色或场景鉴权。"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Callable, TypeVar

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas.common import fail

logger = logging.getLogger("app.services")
T = TypeVar("T")


class ServiceError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def service_call(method: Callable[..., T]) -> Callable[..., T]:
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except ServiceError as exc:
            self.db.rollback()
            return fail(code=exc.code, message=exc.message)
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("数据库操作失败: %s.%s", type(self).__name__, method.__name__)
            return fail(code=500, message="数据服务暂时不可用，请稍后重试")
        except Exception:
            self.db.rollback()
            logger.exception("Service 异常: %s.%s", type(self).__name__, method.__name__)
            return fail(code=500, message="服务器内部错误")
    return wrapper


class ServiceBase:
    logger = logging.getLogger("app.services")

    def __init__(self, db: Session):
        self.db = db

    def commit(self) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise
