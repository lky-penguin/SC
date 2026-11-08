"""模型评价请求。个人版只有单一阅读视角。"""
from pydantic import BaseModel


class ModelEvaluationRequest(BaseModel):
    regenerate: bool = False
