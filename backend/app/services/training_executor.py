# Java算法训练和预测执行器
import json
import os
import requests
from app.services.algorithm_config import (
    ALGORITHM_SERVICE_URLS,
    PMWNB_SERVICE_URL,
    PREDICT_TIMEOUT,
    TRAIN_TIMEOUT,
    TRAINED_MODEL_DIR,
)
__all__ = [
    "build_model_save_path",
    "execute_algorithm_service_predict",
    "execute_algorithm_training",
    "execute_pmwnb_training",
]
def _request_java_json(
    url: str,
    endpoint: str,
    payload: dict,
    timeout: int,
    operation: str,
    connection_hint: str = "",
) -> dict:
    try:
        response = requests.post(
            f"{url.rstrip('/')}/{endpoint}",
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.ConnectionError as exc:
        message = f"无法连接到{operation}服务（{url}）"
        if connection_hint:
            message += f"，{connection_hint}"
        raise RuntimeError(message) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"{operation}请求失败：{exc}") from exc
    try:
        result = response.json()
    except ValueError as exc:
        if not response.ok:
            message = (response.text or "").strip()[:1000]
            raise RuntimeError(message or f"{operation}失败") from exc
        raise RuntimeError(f"{operation}服务响应不是有效 JSON") from exc
    if not response.ok:
        detail = None
        if isinstance(result, dict):
            detail = result.get("error") or result.get("message")
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        message = detail or (response.text or "").strip()[:1000]
        raise RuntimeError(str(message or f"{operation}失败"))
    if not isinstance(result, dict):
        raise RuntimeError(f"{operation}服务返回的数据格式不正确")
    if not result.get("success"):
        detail = result.get("error") or result.get("message")
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        raise RuntimeError(str(detail or f"{operation}失败"))
    return result
def _resolve_algorithm_url(algorithm_code: str) -> tuple[str, str]:
    code = algorithm_code.strip().upper()
    if code == "PMWNB":
        url = PMWNB_SERVICE_URL
    else:
        url = ALGORITHM_SERVICE_URLS.get(code)
    if not url:
        raise RuntimeError(f"未配置{code}算法服务")
    return code, url
def _request_train(
    url: str,
    algorithm_code: str,
    dataset_path: str,
    model_save_path: str,
    training_parameters: dict | None = None,
    risk_labels: list[str] | None = None,
) -> dict:
    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"数据集文件不存在:{dataset_path}")
    payload = {
        "algorithm_code": algorithm_code,
        "dataset_path": dataset_path,
        "model_save_path": model_save_path,
        "training_parameters": training_parameters or {},
        "risk_labels": risk_labels or [],
    }
    result = _request_java_json(
        url,
        "train",
        payload,
        TRAIN_TIMEOUT,
        f"{algorithm_code}训练",
        "请先运行start_all.ps1启动Java算法服务",
    )
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        raise RuntimeError(f"{algorithm_code}训练服务未返回有效指标")
    for key in ("accuracy", "f1", "recall", "precision"):
        if key not in metrics:
            raise RuntimeError(f"{algorithm_code}训练结果缺少指标:{key}")
    return {
        "source": f"java_{algorithm_code.lower()}",
        "algorithm_code": algorithm_code,
        "accuracy": metrics["accuracy"],
        "f1": metrics["f1"],
        "recall": metrics["recall"],
        "precision": metrics["precision"],
        "specificity": metrics.get("specificity"),
        "g_mean": metrics.get("g_mean"),
        "risk_recall": metrics.get("risk_recall"),
        "risk_f1": metrics.get("risk_f1"),
        "cv_mean": metrics.get("cv_mean"),
        "cv_std": metrics.get("cv_std"),
        "quality_availability": metrics.get("quality_availability", {}),
        "train_time_s": metrics.get("train_time_s", 0.0),
        "num_instances": metrics.get("num_instances", 0),
        "num_attributes": metrics.get("num_attributes", 0),
        "num_classes": metrics.get("num_classes", 0),
        "class_distribution": metrics.get("class_distribution", []),
        "model_saved_to": metrics.get("model_saved_to", model_save_path),
        "dataset": metrics.get("dataset", dataset_path),
    }
def execute_algorithm_training(
    algorithm_code: str,
    dataset_path: str,
    model_save_path: str,
    training_parameters: dict | None = None,
    risk_labels: list[str] | None = None,
) -> dict:
    code, url = _resolve_algorithm_url(algorithm_code)
    return _request_train(
        url,
        code,
        dataset_path,
        model_save_path,
        training_parameters,
        risk_labels,
    )
def execute_pmwnb_training(
    dataset_path: str,
    model_save_path: str,
    training_parameters: dict | None = None,
    risk_labels: list[str] | None = None,
) -> dict:
    return execute_algorithm_training(
        "PMWNB",
        dataset_path,
        model_save_path,
        training_parameters,
        risk_labels,
    )
def build_model_save_path(model_id: int, algorithm_code: str = "PMWNB") -> str:
    os.makedirs(TRAINED_MODEL_DIR, exist_ok=True)
    filename = f"{algorithm_code.lower()}_mv{model_id}.model"
    return os.path.join(TRAINED_MODEL_DIR, filename)
def _request_predict(
    url: str,
    algorithm_code: str,
    model_path: str,
    arff_path: str,
    features: dict,
    risk_labels: list[str] | None = None,
) -> dict:
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"模型文件不存在:{model_path}")
    if not os.path.isfile(arff_path):
        raise FileNotFoundError(f"数据集文件不存在:{arff_path}")
    payload = {
        "algorithm_code": algorithm_code,
        "model_path": model_path,
        "arff_path": arff_path,
        "features": features,
        "risk_labels": risk_labels or [],
    }
    result = _request_java_json(
        url,
        "predict",
        payload,
        PREDICT_TIMEOUT,
        "Java预测",
    )
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Java预测服务未返回有效预测结果")
    return data
def execute_algorithm_service_predict(
    algorithm_code: str,
    model_path: str,
    arff_path: str,
    features: dict,
    risk_labels: list[str] | None = None,
) -> dict:
    code, url = _resolve_algorithm_url(algorithm_code)
    return _request_predict(
        url,
        code,
        model_path,
        arff_path,
        features,
        risk_labels,
    )