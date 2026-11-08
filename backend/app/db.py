"""软件 C PostgreSQL 16 数据库统一入口。

- DATABASE_URL 从 backend/app/.env 读取；本地未配置时回落到 docker-compose.yml 的本地连接串，
  保证开发环境开箱即用。
- Base 是所有 ORM 模型的公共基类，模型定义见 app/models/ 目录（12 张表）。
"""
import os

import dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    # 默认连接串与根目录 docker-compose.yml 保持一致（postgres:16）
    "postgresql+psycopg2://c_personal:c_personal_dev@127.0.0.1:15441/c_personal",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类（SQLAlchemy 2.x 声明式）。"""


def get_db():
    """FastAPI 依赖注入用：每次请求一个会话，用完自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
