"""软件 C 服务层导出：仅登记个人版实际使用的服务。"""

from importlib import import_module

_EXPORTS = {
    "ServiceBase": ("base", "ServiceBase"),
    "ServiceError": ("base", "ServiceError"),
    "service_call": ("base", "service_call"),
    "DatasetService": ("dataset_service", "DatasetService"),
    "AlgorithmService": ("algorithm_service", "AlgorithmService"),
    "ModelVersionService": ("model_version_service", "ModelVersionService"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute_name)
    globals()[name] = value
    return value
