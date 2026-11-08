"""运行环境相关的小工具。"""
from __future__ import annotations

import logging
import os
import sys


def get_logger(name: str) -> logging.Logger:
    """返回业务代码统一使用的 logger。"""
    return logging.getLogger(f"app.services.{name}")


def running_under_test_runner() -> bool:
    """判断当前进程是否由测试框架启动。

    后台训练执行器不应在测试进程中连接真实数据库或修改训练状态。
    """
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    if getattr(spec, "name", None) in ("unittest.__main__", "pytest", "pytest.__main__"):
        return True
    if "pytest" in sys.modules:
        return True
    argv0 = os.path.basename(sys.argv[0] or "")
    return argv0.startswith("test_") and argv0.endswith(".py")
