"""算法注册表的只读查询。算法只能由代码注册，不提供页面增删改。"""
from sqlalchemy import select

from app.models.algorithm import Algorithm
from app.schemas.common import ok
from app.services.base import ServiceBase, ServiceError, service_call
from app.services.constants import ALGORITHM_STATUS_AVAILABLE
from app.utils.serialization import row_to_dict


class AlgorithmService(ServiceBase):
    @service_call
    def get_list(self, only_available: bool = True):
        stmt = select(Algorithm).order_by(Algorithm.id)
        if only_available:
            stmt = stmt.where(Algorithm.status == ALGORITHM_STATUS_AVAILABLE)
        algorithms = self.db.scalars(stmt).all()
        return ok(data=[row_to_dict(algorithm) for algorithm in algorithms])

    @service_call
    def get(self, algorithm_id: int):
        algorithm = self.db.get(Algorithm, algorithm_id)
        if algorithm is None:
            raise ServiceError(404, "算法不存在")
        return ok(data=row_to_dict(algorithm))
