"""软件 C 个人本地配置。"""
from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

APP_NAME = "风险数据集迭代与贝叶斯模型训练评估系统"
APP_SLUG = "C-data-model"
APP_VERSION = "1.0.0"
API_PORT = int(os.getenv("PORT", "18201"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "18202"))
