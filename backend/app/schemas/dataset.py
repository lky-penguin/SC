"""数据集请求模型。"""
from pydantic import BaseModel


class DatasetAnalysisRequest(BaseModel):
    regenerate: bool = False
