from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import PROJECT_ROOT
from app.db.models import (
    KnowledgeFAQ,
    KnowledgeList,
    KnowledgeSOP,
    KnowledgeSKU,
    KnowledgeSafetyRule,
)
from app.db.session import SessionLocal


class KnowledgeLoader:
    def __init__(
        self,
        knowledge_dir: Path | str | None = None,
        *,
        business_dir: Path | str | None = None,
        use_database: bool = True,
    ) -> None:
        self.knowledge_dir = Path(knowledge_dir) if knowledge_dir else PROJECT_ROOT / "data" / "knowledge"
        self.business_dir = Path(business_dir) if business_dir else PROJECT_ROOT / "data" / "business"
        # 评测快照可显式关闭数据库，避免正式知识内容混入评测。
        self.use_database = use_database

    def load_context(self) -> dict[str, Any]:
        """加载回合初始化所需的轻量知识上下文。

        注意：这里不加载 SKU/FAQ/SOP 全量内容。KnowledgeAgent 需要知识时，
        通过 query_context() 按需读取。SafetyAgent 的风控规则单独读取。
        """
        catalog = self.load_catalog()
        return {
            "knowledge_catalog": catalog,
            "sales_sop": {},
            "safety_rules": self.load_safety_rules(),
            "skus": [],
            "courses": [],
            "faq": "",
        }

    def load_business_identity(self) -> str:
        """读取所有 Agent 共用的业务身份说明。"""
        for filename in ("identity.md", "identity.example.md"):
            path = self.business_dir / filename
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        return ""

    def query_context(
        self,
        *,
        message: str,
        intent: dict[str, Any] | None = None,
        current_stage: str = "开场",
    ) -> dict[str, Any]:
        """按需读取 KnowledgeAgent 本轮需要的知识子集。

        knowledge_safety_rules 不在候选范围内；风控规则只允许 SafetyAgent 读取。
        """
        selected_sources = self.select_knowledge_sources(
            message=message,
            intent=intent or {},
            current_stage=current_stage,
        )
        db_context = (
            self._query_context_from_db(
                message=message,
                current_stage=current_stage,
                selected_sources=selected_sources,
            )
            if self.use_database
            else None
        )
        if db_context is not None:
            return db_context
        return self._query_context_from_files(
            message=message,
            current_stage=current_stage,
            selected_sources=selected_sources,
        )

    def query_sop_docs(self, *, message: str, current_stage: str = "开场") -> dict[str, Any]:
        """为 SOPAgent 单独读取 SOP 子集。"""
        db_sop = (
            self._query_sop_from_db(message=message, current_stage=current_stage, limit=8)
            if self.use_database
            else None
        )
        if db_sop is not None:
            return self._organize_sop_by_stage(db_sop)
        sop_rows = self._load_csv("sop.csv") or self._load_csv("sop.example.csv")
        return self._organize_sop_by_stage(self._rank_rows(sop_rows, message, limit=8))

    def list_sop_stages(self, *, include_terminal: bool = False) -> list[str]:
        """按 knowledge_sop.stage 去重返回销售阶段列表，供后端约束和前端展示使用。"""
        if self.use_database:
            try:
                with SessionLocal() as db:
                    rows = db.scalars(select(KnowledgeSOP)).all()
                    if rows:
                        sorted_rows = sorted(rows, key=_sop_row_order)
                        stages = _dedupe_sop_stages(
                            (row.stage for row in sorted_rows),
                            include_terminal=include_terminal,
                        )
                        if stages:
                            return stages
            except SQLAlchemyError:
                pass

        sop_rows = self._load_csv("sop.csv") or self._load_csv("sop.example.csv")
        sorted_rows = sorted(sop_rows, key=_sop_mapping_order)
        return _dedupe_sop_stages(
            (
                row.get("SOP阶段")
                or row.get("stage")
                or row.get("阶段")
                or ""
                for row in sorted_rows
            ),
            include_terminal=include_terminal,
        )

    def load_catalog(self) -> list[dict[str, Any]]:
        if self.use_database:
            try:
                with SessionLocal() as db:
                    rows = db.scalars(
                        select(KnowledgeList)
                        .where(KnowledgeList.status == "active")
                        .order_by(KnowledgeList.knowledge_key)
                    ).all()
                    if rows:
                        return [
                            {
                                "knowledge_key": row.knowledge_key,
                                "table_name": row.table_name,
                                "display_name": row.display_name,
                                "description": row.description,
                                "use_when": row.use_when,
                                "do_not_use_when": row.do_not_use_when,
                                "query_hints": _json_loads(row.query_hints_json, []),
                            }
                            for row in rows
                        ]
            except SQLAlchemyError:
                pass
        return [
            {
                "knowledge_key": "skus",
                "table_name": "knowledge_skus",
                "display_name": "SKU 商品库",
                "description": "商品、课程、服务、价格、交付和卖点信息。",
                "use_when": "客户询问商品、课程、服务、价格、优惠、适合人群时使用。",
                "do_not_use_when": "简单寒暄或非商品问题不要使用。",
                "query_hints": ["价格", "课程", "套餐", "服务", "优惠"],
            },
            {
                "knowledge_key": "sop",
                "table_name": "knowledge_sop",
                "display_name": "销售 SOP",
                "description": "销售阶段和推进动作。",
                "use_when": "判断销售阶段、追问方向或推进策略时使用。",
                "do_not_use_when": "不用于风控审核。",
                "query_hints": ["开场", "探需", "异议", "报名"],
            },
            {
                "knowledge_key": "faq",
                "table_name": "knowledge_faq",
                "display_name": "FAQ 问答库",
                "description": "常见业务问题、流程说明和政策解释。",
                "use_when": "客户询问考试、报名、证书、流程、发票、退款等知识时使用。",
                "do_not_use_when": "不用于风控审核。",
                "query_hints": ["报名", "证书", "考试", "流程", "退款", "发票"],
            },
        ]

    def load_safety_rules(self) -> dict[str, Any]:
        """读取风控规则。该方法只应由 SafetyAgent 链路使用。"""
        if self.use_database:
            try:
                with SessionLocal() as db:
                    rows = db.scalars(select(KnowledgeSafetyRule).order_by(KnowledgeSafetyRule.rule_id)).all()
                    if rows:
                        return {
                            "source": "knowledge_safety_rules",
                            "rules": [
                                {
                                    "level": row.level,
                                    "primary_category": row.primary_category,
                                    "secondary_category": row.secondary_category,
                                    "standard": row.standard,
                                    "violation": row.violation,
                                    "handling_result": row.handling_result,
                                }
                                for row in rows
                            ],
                        }
            except SQLAlchemyError:
                pass
        rows = self._load_csv("safety_rules.csv") or self._load_csv(
            "safety_rules.example.csv"
        )
        if not rows:
            return {}
        return {
            "source": "safety_rules_csv",
            "rules": [
                {
                    "level": str(row.get("level") or row.get("等级") or ""),
                    "primary_category": str(
                        row.get("primary_category") or row.get("一级类别") or ""
                    ),
                    "secondary_category": str(
                        row.get("secondary_category") or row.get("二级类别") or ""
                    ),
                    "standard": str(row.get("standard") or row.get("标准") or ""),
                    "violation": str(row.get("violation") or row.get("违规") or ""),
                    "handling_result": str(
                        row.get("handling_result") or row.get("处理结果") or ""
                    ),
                }
                for row in rows
            ],
        }

    def select_knowledge_sources(
        self,
        *,
        message: str,
        intent: dict[str, Any],
        current_stage: str,
    ) -> list[str]:
        selected: list[str] = []
        normalized = message.lower()
        intent_text = json.dumps(intent, ensure_ascii=False).lower()

        if _needs_sku(normalized, intent_text):
            selected.append("skus")
        if _needs_faq(normalized, intent_text):
            selected.append("faq")
        if _needs_sop(normalized, intent_text, current_stage):
            selected.append("sop")
        if not selected:
            selected.append("faq")
        return selected

    def _query_context_from_db(
        self,
        *,
        message: str,
        current_stage: str,
        selected_sources: list[str],
    ) -> dict[str, Any] | None:
        try:
            with SessionLocal() as db:
                has_catalog = db.scalars(select(KnowledgeList.knowledge_key).limit(1)).first()
                if not has_catalog:
                    return None
                skus = self._query_skus_from_db(message=message, limit=3) if "skus" in selected_sources else []
                sop_rows = self._query_sop_from_db(message=message, current_stage=current_stage, limit=8) or []
                faq_rows = self._query_faq_from_db(message=message, limit=6) if "faq" in selected_sources else []
                return {
                    "selected_knowledge_sources": selected_sources,
                    "skus": skus,
                    "courses": skus,
                    "sop_docs": self._organize_sop_by_stage(sop_rows),
                    "faq": _format_faq_rows(faq_rows),
                }
        except SQLAlchemyError:
            return None

    def _query_context_from_files(
        self,
        *,
        message: str,
        current_stage: str,
        selected_sources: list[str],
    ) -> dict[str, Any]:
        skus = []
        if "skus" in selected_sources:
            skus = self._rank_rows(self._load_csv("skus.csv") or self._load_csv("skus.example.csv"), message, limit=3)
            skus = [_normalize_sku_row(row) for row in skus]
        sop_rows = self._rank_rows(self._load_csv("sop.csv") or self._load_csv("sop.example.csv"), message, limit=8)
        faq_rows = self._rank_rows(
            self._load_csv("faq.csv") or self._load_csv("faq.example.csv"),
            message,
            limit=6,
        )
        faq = _format_faq_rows([_normalize_faq_row(row) for row in faq_rows])
        return {
            "selected_knowledge_sources": selected_sources,
            "skus": skus,
            "courses": skus,
            "sop_docs": self._organize_sop_by_stage(sop_rows),
            "faq": faq if "faq" in selected_sources else "",
        }

    def _query_skus_from_db(self, *, message: str, limit: int) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = db.scalars(select(KnowledgeSKU)).all()
            ranked = _rank_objects(rows, message, limit=limit)
            return [
                {
                    "sku_id": row.sku_id,
                    "sku_name": row.sku_name,
                    "sku_alias": row.sku_alias,
                    "sku_type": row.sku_type,
                    "url": row.url,
                    "status": row.status,
                    "target_users": _json_loads(row.target_users_json, []),
                    "learning_goals": _json_loads(row.learning_goals_json, []),
                    "selling_points": _json_loads(row.selling_points_json, []),
                    "delivery": row.delivery,
                    "list_price_yuan": row.list_price_yuan,
                    "deal_price_yuan": row.deal_price_yuan,
                    "currency": row.currency,
                    "discount_policy": row.discount_policy,
                    "policy_notes": row.policy_notes,
                    "tags": _json_loads(row.tags_json, []),
                    "notes": row.notes,
                }
                for row in ranked
            ]

    def _query_sop_from_db(self, *, message: str, current_stage: str, limit: int) -> list[dict[str, Any]] | None:
        try:
            with SessionLocal() as db:
                rows = db.scalars(select(KnowledgeSOP)).all()
                if not rows:
                    return []
                ranked = _rank_objects(rows, f"{current_stage}\n{message}", limit=limit)
                return [
                    {
                        **_json_loads(row.raw_json, {}),
                        "sop_id": row.sop_id,
                        "ID": row.sop_id,
                        "SOP阶段": row.stage,
                        "stage": row.stage,
                        "任务目标": row.goal,
                        "goal": row.goal,
                        "参考话术": row.reference_script,
                        "reference_script": row.reference_script,
                        "转人工判断": row.handover_criteria,
                        "handover_criteria": row.handover_criteria,
                        "客户未回复最长等待时间min": row.wait_minutes,
                        "wait_minutes": row.wait_minutes,
                        "超时动作": row.timeout_action,
                        "timeout_action": row.timeout_action,
                    }
                    for row in ranked
                ]
        except SQLAlchemyError:
            return None

    def _query_faq_from_db(self, *, message: str, limit: int) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = db.scalars(select(KnowledgeFAQ)).all()
            ranked = _rank_objects(rows, message, limit=limit)
            return [{"title": row.title, "content": row.content} for row in ranked]

    def _organize_sop_by_stage(self, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """将 SOP 行按阶段分组，供 SOPAgent 按阶段检索。"""
        stages: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            stage = str(row.get("SOP阶段") or row.get("stage") or row.get("阶段") or "").strip()
            if not stage:
                stage = "未分组"
            stages.setdefault(stage, []).append(row)
        return stages

    def _load_csv(self, filename: str) -> list[dict[str, Any]]:
        path = self.knowledge_dir / filename
        if not path.exists():
            return []

        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if not row:
                    continue
                normalized = {
                    str(key).strip(): self._normalize_csv_value(str(key).strip(), value)
                    for key, value in row.items()
                    if key and str(key).strip()
                }
                if any(value not in ("", [], None) for value in normalized.values()):
                    rows.append(normalized)
        return rows

    def _normalize_csv_value(self, key: str, value: Any) -> Any:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if key in {"stock", "sort_order"}:
            try:
                return int(text)
            except ValueError:
                return text
        if key in {"target_users", "learning_goals", "selling_points", "tags"}:
            return [item.strip() for item in re.split(r"[;；]", text) if item.strip()]
        return text

    def _rank_rows(self, rows: list[dict[str, Any]], message: str, *, limit: int) -> list[dict[str, Any]]:
        terms = _terms(message)
        ranked = sorted(
            rows,
            key=lambda row: _score_text(json.dumps(row, ensure_ascii=False), terms),
            reverse=True,
        )
        return ranked[:limit]


def _needs_sku(message: str, intent_text: str) -> bool:
    keywords = ("多少钱", "价格", "费用", "优惠", "折扣", "套餐", "产品", "课程", "服务", "班型", "包含", "区别", "对比")
    return any(keyword in message or keyword in intent_text for keyword in keywords)


def _needs_faq(message: str, intent_text: str) -> bool:
    keywords = (
        "报名",
        "证书",
        "考试",
        "考证",
        "怎么考",
        "流程",
        "退款",
        "发票",
        "上课",
        "交付",
        "时间",
        "条件",
        "资格",
        "零基础",
    )
    return any(keyword in message or keyword in intent_text for keyword in keywords)


def _needs_sop(message: str, intent_text: str, current_stage: str) -> bool:
    if current_stage:
        return True
    keywords = ("想了解", "考虑", "担心", "预算", "基础", "报名", "购买", "犹豫")
    return any(keyword in message or keyword in intent_text for keyword in keywords)


def _dedupe_sop_stages(
    stages: Any,
    *,
    include_terminal: bool,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in stages:
        stage = str(value or "").strip()
        if not stage or stage in seen:
            continue
        if not include_terminal and _is_terminal_sop_stage(stage):
            continue
        seen.add(stage)
        result.append(stage)
    return result


def _is_terminal_sop_stage(stage: str) -> bool:
    normalized = re.sub(r"\s+", "", stage).lower()
    return normalized in {"handover", "closed", "转人工", "已结束", "结束"}


def _sop_row_order(row: KnowledgeSOP) -> tuple[int, str]:
    raw = _json_loads(row.raw_json, {})
    return _sop_order_key(
        raw.get("sort_order")
        or raw.get("ID")
        or raw.get("id")
        or raw.get("序号")
        or row.sop_id
    )


def _sop_mapping_order(row: dict[str, Any]) -> tuple[int, str]:
    return _sop_order_key(
        row.get("sort_order")
        or row.get("ID")
        or row.get("id")
        or row.get("序号")
        or row.get("sop_id")
        or ""
    )


def _sop_order_key(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    match = re.search(r"\d+", text)
    if match:
        return int(match.group(0)), text
    return 10**9, text


def _rank_objects(rows: list[Any], message: str, *, limit: int) -> list[Any]:
    terms = _terms(message)
    ranked = sorted(rows, key=lambda row: _score_text(getattr(row, "search_text", ""), terms), reverse=True)
    return ranked[:limit]


def _terms(message: str) -> list[str]:
    text = re.sub(r"\s+", "", message)
    terms = [text] if text else []
    terms.extend(item for item in re.split(r"[，,。！？?、\s]+", message) if item)
    terms.extend(re.findall(r"[\u4e00-\u9fff]{2,6}", message))
    return list(dict.fromkeys(term for term in terms if term))


def _score_text(text: str, terms: list[str]) -> int:
    if not terms:
        return 0
    return sum(3 if term in text else 0 for term in terms) + sum(text.count(term) for term in terms)


def _format_faq_rows(rows: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"## {row['title']}\n{row['content']}" for row in rows if row.get("content"))


def _normalize_sku_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    if "price_cents" in normalized and "list_price_yuan" not in normalized:
        normalized["list_price_yuan"] = normalized.pop("price_cents")
    return normalized


def _normalize_faq_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(
            row.get("title")
            or row.get("问题")
            or row.get("question")
            or row.get("标题")
            or ""
        ),
        "content": str(
            row.get("content")
            or row.get("答案")
            or row.get("answer")
            or row.get("回答")
            or ""
        ),
    }


def _json_loads(text: str, default: Any) -> Any:
    try:
        return json.loads(text or "")
    except (TypeError, json.JSONDecodeError):
        return default
