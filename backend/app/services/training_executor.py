"""Java 算法训练/预测执行器。

PMWNB 使用既有服务；A2WNB、MAWNB、EMAWNB、CAVWNB、DIWNB、KFDB、FLNB、
FTAWNB 使用由 scripts/build_nb_algorithm_jars.ps1 编译的真实 Weka 算法服务。
所有训练指标均来自 Java 分类器，不再生成 mock 指标。
"""
import os

import requests

from app.services.algorithm_config import (
    ALGORITHM_SERVICE_URLS,
    PMWNB_SERVICE_URL,
    PREDICT_SERVICE_URL,
    PREDICT_TIMEOUT,
    TRAIN_TIMEOUT,
    TRAINED_MODEL_DIR,
)

__all__ = [
    "build_model_save_path",
    "execute_algorithm_predict",
    "execute_algorithm_service_predict",
    "execute_algorithm_training",
    "execute_pmwnb_training",
]


def _require_existing_file(path: str, kind: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(f"{kind}文件不存在: {path}")


def _request_java_json(
    url: str,
    endpoint: str,
    payload: dict,
    timeout: int,
    *,
    connection_error: str,
    request_error: str,
    default_error: str,
) -> dict:
    """调用 Java JSON 接口，并统一连接、请求和业务失败的错误转换。"""
    try:
        resp = requests.post(
            f"{url}/{endpoint}",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(connection_error) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"{request_error}：{exc}") from exc
    if not result.get("success"):
        raise RuntimeError(result.get("error", default_error))
    return result


def _request_train(
    url: str,
    algorithm_code: str,
    dataset_path: str,
    model_save_path: str,
    training_parameters: dict | None = None,
    risk_labels: list[str] | None = None,
) -> dict:
    _require_existing_file(dataset_path, "数据集")
    result = _request_java_json(
        url,
        "train",
        {
            "algorithm_code": algorithm_code,
            "dataset_path": dataset_path,
            "model_save_path": model_save_path,
            "training_parameters": training_parameters or {},
            "risk_labels": risk_labels or [],
        },
        TRAIN_TIMEOUT,
        connection_error=(
            f"无法连接到 {algorithm_code} 算法服务（{url}），"
            "请先运行 start_all.ps1 启动 Java 算法服务"
        ),
        request_error=f"{algorithm_code} 算法服务请求失败（{url}）",
        default_error=f"{algorithm_code} 训练失败",
    )
    metrics = result["metrics"]
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
    code, url = _resolve_algorithm_url(algorithm_code, PMWNB_SERVICE_URL)
    return _request_train(
        url, code, dataset_path, model_save_path, training_parameters, risk_labels
    )


def execute_pmwnb_training(
    dataset_path: str,
    model_save_path: str,
    training_parameters: dict | None = None,
    risk_labels: list[str] | None = None,
) -> dict:
    return execute_algorithm_training(
        "PMWNB", dataset_path, model_save_path, training_parameters, risk_labels
    )


def build_model_save_path(model_id: int, algorithm_code: str = "PMWNB") -> str:
    os.makedirs(TRAINED_MODEL_DIR, exist_ok=True)
    return os.path.join(TRAINED_MODEL_DIR, f"{algorithm_code.lower()}_mv{model_id}.model")


def _request_predict(
    url: str,
    algorithm_code: str,
    model_path: str,
    arff_path: str,
    features: dict,
    risk_labels: list[str] | None = None,
) -> dict:
    _require_existing_file(model_path, "模型")
    _require_existing_file(arff_path, "数据集")
    result = _request_java_json(
        url,
        "predict",
        {
            "algorithm_code": algorithm_code,
            "model_path": model_path,
            "arff_path": arff_path,
            "features": features,
            "risk_labels": risk_labels or [],
        },
        PREDICT_TIMEOUT,
        connection_error=f"无法连接到 Java 预测服务（{url}）",
        request_error=f"Java 预测服务请求失败（{url}）",
        default_error="Java 预测失败",
    )
    return result["data"]


def _resolve_algorithm_url(algorithm_code: str, pmwnb_url: str) -> tuple[str, str]:
    code = algorithm_code.upper()
    url = pmwnb_url if code == "PMWNB" else ALGORITHM_SERVICE_URLS.get(code)
    if not url:
        raise RuntimeError(f"未配置 {code} 算法服务")
    return code, url


def execute_algorithm_predict(
    algorithm_code: str,
    model_path: str,
    arff_path: str,
    features: dict,
    risk_labels: list[str] | None = None,
) -> dict:
    code, url = _resolve_algorithm_url(algorithm_code, PREDICT_SERVICE_URL)
    return _request_predict(url, code, model_path, arff_path, features, risk_labels)


def execute_algorithm_service_predict(
    algorithm_code: str,
    model_path: str,
    arff_path: str,
    features: dict,
    risk_labels: list[str] | None = None,
) -> dict:
    """Use the training service's own /predict endpoint for package smoke tests.

    The standalone predict-service remains available for the regular UI path, but a
    contract package must be smoke-tested by an independently startable Java service
    that is also part of the local training runtime.
    """
    code, url = _resolve_algorithm_url(algorithm_code, PMWNB_SERVICE_URL)
    return _request_predict(url, code, model_path, arff_path, features, risk_labels)
