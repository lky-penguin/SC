"""模型级 AI 评价；AI 不可用时使用明确标记的确定性规则模板。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from app.models.model_version import ModelVersion
from app.schemas.common import ok
from app.services.ai_stream import AIStreamContract, stream_ai_result
from app.services.base import ServiceBase, ServiceError, service_call
from app.services.constants import dataset_display_name_of
from app.utils.runtime import get_logger

logger = get_logger("model_evaluation")
EVALUATION_VERSION = "1.0"
ROLE = "current"
STREAM_CONTRACT = AIStreamContract(
    start_status="开始生成模型评价",
    cached_done_status="已读取已保存评价",
    not_configured_message="AI 服务未配置，已使用确定性规则评价（非大模型输出）",
    not_configured_reason_code="not_configured",
    not_configured_done_status="已使用规则模板完成评价",
    success_done_status="模型评价完成",
    failure_message_prefix="AI 评价失败，已回退确定性规则（非大模型输出）：",
    failure_done_status="已使用规则模板完成评价",
    log_message="AI model evaluation failed reason=%s",
)
_QUALITY_KEYS = (
    "accuracy", "precision", "recall", "specificity", "f1", "g_mean",
    "risk_recall", "risk_f1", "cv_mean", "cv_std", "quality_availability",
    "num_instances", "num_attributes", "num_classes", "class_distribution",
)


def _quality_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    source = metrics if isinstance(metrics, dict) else {}
    return {key: source[key] for key in _QUALITY_KEYS if key in source}


def _algorithm_reference(algorithm: Any) -> dict[str, Any]:
    return {
        "code": getattr(algorithm, "code", None),
        "name": getattr(algorithm, "display_name", None),
        "description": getattr(algorithm, "description", None),
        "parameter_schema": getattr(algorithm, "param_schema", None) or [],
    }


def build_model_attributes(model: ModelVersion) -> dict[str, Any]:
    dataset = getattr(model, "dataset", None)
    algorithm = getattr(model, "algorithm", None)
    fields = getattr(dataset, "fields_schema", None) or []
    feature_profile = [
        {"name": f.get("name"), "type": f.get("type")}
        for f in fields
        if isinstance(f, dict) and f.get("role") != "label"
    ]
    return {
        "contract_version": EVALUATION_VERSION,
        "model_version_id": model.id,
        "status": model.status,
        "dataset": {
            "name": dataset_display_name_of(dataset),
            "version": getattr(dataset, "version", None),
            "label_field": getattr(dataset, "label_field", None),
            "field_count": len(feature_profile),
        },
        "algorithm": _algorithm_reference(algorithm),
        "training_parameters": model.training_parameters or {},
        "quality_metrics": _quality_metrics(model.evaluation_metrics),
        "feature_profile": feature_profile,
        "evaluation_scope": "同一数据集版本的真实 Java 训练结果",
    }


def refresh_model_attributes(model: ModelVersion) -> dict[str, Any]:
    attributes = build_model_attributes(model)
    model.model_attributes = attributes
    return attributes


def _facts(attributes: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_version_id": attributes.get("model_version_id"),
        "dataset": attributes.get("dataset"),
        "algorithm": attributes.get("algorithm"),
        "training_parameters": attributes.get("training_parameters"),
        "quality_metrics": attributes.get("quality_metrics"),
        "feature_count": len(attributes.get("feature_profile") or []),
    }


def fallback_evaluation(facts: dict[str, Any]) -> str:
    m = facts.get("quality_metrics") or {}
    d = facts.get("dataset") or {}
    a = facts.get("algorithm") or {}
    lines = [
        "### 模型结论",
        f"- 模型版本：#{facts.get('model_version_id')}；数据集：{d.get('name')} v{d.get('version')}；算法：{a.get('name')}（{a.get('code')}）",
        f"- 训练参数：`{json.dumps(facts.get('training_parameters') or {}, ensure_ascii=False)}`",
        "",
        "### 指标快照",
        f"- Accuracy：{m.get('accuracy', '不可用')}",
        f"- Precision：{m.get('precision', '不可用')}",
        f"- Recall：{m.get('recall', '不可用')}",
        f"- F1：{m.get('f1', '不可用')}",
        f"- 风险类 Recall / F1：{m.get('risk_recall', '不可用')} / {m.get('risk_f1', '不可用')}",
        "",
        "### 使用建议",
        "- 先比较同一数据集版本上至少两个算法的指标，再选择满足使用要求的模型。",
        "- 若 F1 或风险类召回偏低，应调整训练参数、补充样本或尝试不同算法。",
        "",
        "> 本评价由本地规则根据真实训练指标生成，**不是大模型输出**。",
    ]
    return "\n".join(lines)


def _prompt(facts: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是模型评价助手。只能引用输入中的真实指标，不得重新计算、编造指标或改变结论；输出 Markdown。"},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]


def evaluation_is_current(
    artifact: dict[str, Any], attributes: dict[str, Any]
) -> bool:
    return bool(artifact.get("markdown")) and artifact.get("facts_snapshot") == _facts(attributes)


class ModelEvaluationService(ServiceBase):
    def _get(self, model_id: int) -> ModelVersion:
        model = self.db.get(ModelVersion, model_id)
        if model is None:
            raise ServiceError(404, "模型版本不存在")
        return model

    def _evaluation_context(self, model_id: int):
        model = self._get(model_id)
        attributes = refresh_model_attributes(model)
        self.commit()
        artifact = ((model.ai_evaluation or {}).get(ROLE) or {})
        return model, attributes, artifact, evaluation_is_current(artifact, attributes)

    @service_call
    def get_evaluation(self, model_id: int):
        model, attributes, artifact, current = self._evaluation_context(model_id)
        return ok(data={
            "model_version_id": model.id,
            "status": model.status,
            "role": ROLE,
            "model_attributes": attributes,
            "evaluation": {
                "available": current,
                "source": artifact.get("source") if current else None,
                "markdown": artifact.get("markdown") if current else None,
                "generated_at": artifact.get("generated_at") if current else None,
            },
        })

    def stream(self, model_id: int, regenerate: bool = False) -> Iterable[tuple[str, dict[str, Any]]]:
        model, attributes, artifact, cache_current = self._evaluation_context(model_id)
        cached_markdown = str(artifact["markdown"]) if cache_current else None
        facts = _facts(attributes)
        yield from stream_ai_result(
            self.db,
            cached_markdown=cached_markdown,
            regenerate=regenerate,
            facts=facts,
            prompt=_prompt(facts),
            fallback=fallback_evaluation,
            save=lambda markdown, source, ai_model: self._save(
                model, markdown, source, facts, ai_model
            ),
            contract=STREAM_CONTRACT,
            logger=logger,
        )

    def _save(self, model: ModelVersion, markdown: str, source: str, facts: dict[str, Any], ai_model: str | None) -> None:
        evaluations = dict(model.ai_evaluation or {})
        evaluations[ROLE] = {
            "markdown": markdown,
            "source": source,
            "facts_snapshot": facts,
            "ai_model": ai_model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "contract_version": EVALUATION_VERSION,
        }
        model.ai_evaluation = evaluations
        self.commit()