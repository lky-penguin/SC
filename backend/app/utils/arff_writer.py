"""ARFF 写出时使用的共享记号工具。"""
from __future__ import annotations

from typing import Any


def arff_token(value: Any) -> str:
    """把字段名 / 枚举值 / 数据值写成合法 ARFF 记号（必要时加单引号转义）。

    该函数是跨模块复用的稳定接口。
    """
    text = "" if value is None else str(value)
    if (
        text == ""
        or text != text.strip()
        or any(ch.isspace() for ch in text)
        or any(ch in text for ch in ",{}'\"%\\")
    ):
        escaped = text.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return text

