"""数据集级算法适配分析（AI 可选，规则结果始终标记来源）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select

from app.models.algorithm import Algorithm
from app.models.dataset import Dataset
from app.schemas.common import ok
from app.services.ai_stream import AIStreamContract, stream_ai_result
from app.services.base import ServiceBase, ServiceError, service_call
from app.services.constants import ALGORITHM_STATUS_AVAILABLE, dataset_display_name_of
from app.utils.runtime import get_logger
from app.utils.validation import dataset_has_numeric_features

logger = get_logger("dataset_analysis")
ANALYSIS_VERSION = "1.0"
STREAM_CONTRACT = AIStreamContract(
    start_status="开始分析数据集",
    cached_done_status="已读取已保存的分析结果",
    not_configured_message="AI 服务未配置，已使用确定性规则分析（非大模型输出）",
    not_configured_reason_code="not_configured",
    not_configured_done_status="已使用规则分析完成",
    success_done_status="数据集分析完成",
    failure_message_prefix="AI 分析失败，已回退确定性规则（非大模型输出）：",
    failure_done_status="已使用规则分析完成",
    log_message="AI dataset analysis failed reason=%s",
)


def _facts(db, dataset: Dataset) -> dict[str, Any]:
    fields = dataset.fields_schema or []
    algorithms = db.scalars(
        select(Algorithm).where(Algorithm.status == ALGORITHM_STATUS_AVAILABLE).order_by(Algorithm.id)
    ).all()
    return {
        "dataset": {
            "name": dataset_display_name_of(dataset),
            "version": dataset.version,
            "label_field": dataset.label_field,
            "field_count": len(fields),
            "features": [f for f in fields if isinstance(f, dict) and f.get("role") != "label"],
            "has_numeric_features": dataset_has_numeric_features(fields),
        },
        "algorithms": [
            {
                "code": a.code,
                "name": a.display_name,
                "description": a.description,
                "parameter_schema": a.param_schema or [],
            }
            for a in algorithms
        ],
    }


def fallback_analysis(facts: dict[str, Any]) -> str:
    d = facts["dataset"]
    algorithms = facts.get("algorithms") or []
    lines = [
        "### 数据集结构结论",
        f"- 数据集：{d.get('name')}",
        f"- 当前版本：v{d.get('version')}；字段数：{d.get('field_count')}；标签字段：{d.get('label_field')}",
        f"- 数值特征：{'有，训练前可使用离散化参数' if d.get('has_numeric_features') else '无或无法识别'}",
        "",
        "### 可用算法",
    ]
    for item in algorithms:
        lines.append(f"- {item['name']}（{item['code']}）：{item.get('description') or '已注册算法'}")
    lines.extend([
        "",
        "### 使用提示",
        "- 建议先用同一数据集版本、同一评估口径训练至少两个算法，再比较准确率、F1 与风险类召回率。",
        "- 上述内容由本地规则根据数据库中的字段和算法注册信息生成，**不是大模型输出**。",
    ])
    return "\n".join(lines)


def _prompt(facts: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是数据集算法适配助手。只能依据输入事实输出 Markdown，不得编造字段、算法或指标。"},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]


class DatasetAnalysisService(ServiceBase):
    def _dataset(self, dataset_id: int) -> Dataset:
        dataset = self.db.get(Dataset, dataset_id)
        if dataset is None:
            raise ServiceError(404, "数据集不存在")
        return dataset

    def _cache(self, dataset: Dataset) -> dict[str, Any]:
        return ((dataset.ai_analysis or {}).get("current") or {})

    @service_call
    def get_analysis(self, dataset_id: int):
        dataset = self._dataset(dataset_id)
        cached = self._cache(dataset)
        return ok(data={
            "dataset_id": dataset.id,
            "name": dataset_display_name_of(dataset),
            "available": bool(cached.get("markdown")),
            "markdown": cached.get("markdown"),
            "source": cached.get("source"),
            "generated_at": cached.get("generated_at"),
        })

    def stream(self, dataset_id: int, regenerate: bool = False) -> Iterable[tuple[str, dict[str, Any]]]:
        dataset = self._dataset(dataset_id)
        facts = _facts(self.db, dataset)
        cached = self._cache(dataset)
        cache_current = bool(cached.get("markdown")) and cached.get("facts") == facts
        cached_markdown = str(cached["markdown"]) if cache_current else None
        yield from stream_ai_result(
            self.db,
            cached_markdown=cached_markdown,
            regenerate=regenerate,
            facts=facts,
            prompt=_prompt(facts),
            fallback=fallback_analysis,
            save=lambda markdown, source, ai_model: self._save(
                dataset, markdown, source, facts, ai_model
            ),
            contract=STREAM_CONTRACT,
            logger=logger,
        )

    def _save(self, dataset: Dataset, markdown: str, source: str, facts: dict[str, Any], ai_model: str | None) -> None:
        dataset.ai_analysis = {
            "current": {
                "markdown": markdown,
                "source": source,
                "facts": facts,
                "ai_model": ai_model,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "contract_version": ANALYSIS_VERSION,
            }
        }
        self.commit()