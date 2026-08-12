from __future__ import annotations

import csv
import json
import re
import tempfile
import uuid
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.core.config import PROJECT_ROOT
from app.db.models import (
    KnowledgeFAQ,
    KnowledgeImportRun,
    KnowledgeList,
    KnowledgeSOP,
    KnowledgeSKU,
    KnowledgeSafetyRule,
)
from app.db.session import SessionLocal
from app.sales_rag.importer import index_sales_case_embeddings_sync, replace_sales_cases


CATALOG_ITEMS = {
    "skus": {
        "table_name": "knowledge_skus",
        "display_name": "SKU 商品库",
        "description": "商品、课程、服务、套餐、价格、交付和卖点信息。",
        "use_when": "客户询问商品、课程、服务、套餐、价格、优惠、交付、适合人群、对比区别时使用。",
        "do_not_use_when": "仅寒暄、仅表达基础情况、仅询问软件操作方法且没有商品诉求时不要使用。",
        "query_hints": ["价格", "多少钱", "课程", "套餐", "服务", "优惠", "适合", "区别", "对比"],
        "source_path": "data/knowledge/skus.csv",
    },
    "sop": {
        "table_name": "knowledge_sop",
        "display_name": "销售 SOP",
        "description": "不同销售阶段、客户信号和下一步推进动作。",
        "use_when": "需要判断销售阶段、推进策略、追问方向或下一步动作时使用。",
        "do_not_use_when": "不用于风控审核，不替代安全规则。",
        "query_hints": ["开场", "探需", "异议", "价格", "购买", "转化"],
        "source_path": "data/knowledge/sop.csv",
    },
    "faq": {
        "table_name": "knowledge_faq",
        "display_name": "FAQ 问答库",
        "description": "常见业务问题、流程说明、政策解释和补充资料。",
        "use_when": "客户询问课程内容、学习方式、数据安全、流程、发票、退款等具体知识时使用。",
        "do_not_use_when": "不用于读取风控禁词和安全审核规则。",
        "query_hints": ["Excel", "Word", "PPT", "AI办公", "流程", "退款", "发票", "学习"],
        "source_path": "data/knowledge/faq.csv",
    },
    "safety_rules": {
        "table_name": "knowledge_safety_rules",
        "display_name": "风控规则",
        "description": "销售话术合规、安全审核、禁用表达和高风险承诺规则。",
        "use_when": "仅 SafetyAgent 审核草稿回复时使用。",
        "do_not_use_when": "KnowledgeAgent 知识检索阶段不要使用，避免把风控规则当作客户问题答案。",
        "query_hints": ["保证", "提效", "隐私", "退款", "违规", "敏感", "风控"],
        "source_path": "data/knowledge/safety_rules.csv",
    },
}


def import_knowledge_sources(
    *,
    knowledge_dir: Path | str | None = None,
    safety_dir: Path | str | None = None,
    db: Session | None = None,
    use_example_sources: bool = False,
    include_safety_rules: bool = True,
) -> dict[str, int]:
    """将本地知识文件同步到 knowledge_* 数据表。

    真实业务文件默认被 Git 忽略；此函数只负责把当前机器上的文件导入数据库。
    对存在的源文件采用整表替换，避免 CSV 手动删行后数据库仍保留旧数据。
    """
    owns_session = db is None
    session = db or SessionLocal()
    knowledge_path = Path(knowledge_dir) if knowledge_dir else PROJECT_ROOT / "data" / "knowledge"
    safety_path = Path(safety_dir) if safety_dir else PROJECT_ROOT / "data" / "safety_rules"
    imported: dict[str, int] = {}
    try:
        _upsert_catalog(session)
        if use_example_sources:
            sku_path = _first_existing(knowledge_path, "skus.example.csv")
            sop_path = _first_existing(knowledge_path, "sop.example.csv")
            faq_path = _first_existing(knowledge_path, "faq.example.csv")
            safety_rule_path = _first_existing(knowledge_path, "safety_rules.example.csv")
            sales_case_path = _first_existing(knowledge_path, "sales_cases.example.csv")
        else:
            sku_path = _first_existing(knowledge_path, "skus.csv", "skus.example.csv")
            sop_path = _first_existing(knowledge_path, "sop.csv", "sop.example.csv")
            faq_path = _first_existing(knowledge_path, "faq.csv", "faq.example.csv")
            sales_case_path = _first_existing(
                knowledge_path,
                "sales_cases.csv",
                "sales_cases.example.csv",
            )
            safety_rule_path = _first_existing(
                knowledge_path,
                "safety_rules.csv",
                "safety_rules.example.csv",
            )
            if safety_rule_path is None:
                safety_rule_path = _first_existing(
                    safety_path,
                    "knowledge_safety_rules.csv",
                    "safety_rules.csv",
                    "销售话术管理规定（V5.0版）.pdf",
                )

        imported["skus"] = _replace_skus(session, sku_path)
        imported["sop"] = _replace_sop(session, sop_path)
        imported["faq"] = _replace_faq(session, faq_path)
        imported["safety_rules"] = (
            _replace_safety_rules(session, safety_rule_path)
            if include_safety_rules
            else 0
        )
        imported["sales_cases"] = replace_sales_cases(session, sales_case_path)
        if sales_case_path:
            _record_import(session, "sales_cases", sales_case_path, imported["sales_cases"])
        if owns_session:
            session.commit()
            # 向量索引只由正式配置开启；评测回放只读取已建好的索引，绝不在运行时补写。
            imported["sales_cases_indexed"] = index_sales_case_embeddings_sync()
        return imported
    except Exception:
        if owns_session:
            session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def _upsert_catalog(db: Session) -> None:
    now = _utc_now()
    for key, item in CATALOG_ITEMS.items():
        existing = db.get(KnowledgeList, key)
        payload = {
            "table_name": item["table_name"],
            "display_name": item["display_name"],
            "description": item["description"],
            "use_when": item["use_when"],
            "do_not_use_when": item["do_not_use_when"],
            "query_hints_json": _json(item["query_hints"]),
            "status": "active",
            "source_path": item["source_path"],
            "updated_at": now,
        }
        if existing:
            for field, value in payload.items():
                setattr(existing, field, value)
        else:
            db.add(KnowledgeList(knowledge_key=key, created_at=now, **payload))


def _replace_skus(db: Session, path: Path | None) -> int:
    if not path:
        return 0
    rows = _read_csv(path)
    db.execute(delete(KnowledgeSKU))
    count = 0
    for index, row in enumerate(rows, start=1):
        sku_id = str(_first_value(row, "sku_id", "SKU ID", "id") or f"sku-{index}")
        list_price = _clean_price(_first_value(row, "list_price_yuan", "price_yuan", "price_cents", "价格"))
        discount_policy = str(_first_value(row, "discount_policy", "优惠政策") or "")
        deal_price = _clean_price(_first_value(row, "deal_price_yuan", "成交价")) or _extract_deal_price(discount_policy)
        target_users = _split_list(_first_value(row, "target_users", "适合人群"))
        learning_goals = _split_list(_first_value(row, "learning_goals", "学习目标"))
        selling_points = _split_list(_first_value(row, "selling_points", "卖点"))
        tags = _split_list(_first_value(row, "tags", "标签"))
        search_text = _search_text(row)
        db.add(
            KnowledgeSKU(
                sku_id=sku_id,
                sku_name=str(_first_value(row, "sku_name", "SKU名称", "名称") or ""),
                sku_alias=str(_first_value(row, "sku_alias", "别名") or ""),
                sku_type=str(_first_value(row, "sku_type", "类型") or ""),
                url=str(_first_value(row, "url", "链接") or ""),
                status=str(_first_value(row, "status", "状态") or ""),
                target_users_json=_json(target_users),
                learning_goals_json=_json(learning_goals),
                selling_points_json=_json(selling_points),
                delivery=str(_first_value(row, "delivery", "交付方式") or ""),
                list_price_yuan=list_price,
                deal_price_yuan=deal_price,
                currency=str(_first_value(row, "currency", "币种") or "CNY"),
                discount_policy=discount_policy,
                policy_notes=str(_first_value(row, "policy_notes", "政策备注") or ""),
                tags_json=_json(tags),
                notes=str(_first_value(row, "notes", "备注") or ""),
                raw_json=_json(row),
                search_text=search_text,
            )
        )
        count += 1
    _record_import(db, "skus", path, count)
    return count


def _replace_sop(db: Session, path: Path | None) -> int:
    if not path:
        return 0
    rows = _read_csv(path)
    db.execute(delete(KnowledgeSOP))
    seen_stages: set[str] = set()
    count = 0
    for index, row in enumerate(rows, start=1):
        stage = str(_first_value(row, "SOP阶段", "stage", "阶段") or "").strip()
        if not stage:
            raise ValueError(f"SOP 第 {index} 行缺少 SOP阶段")
        if stage in seen_stages:
            raise ValueError(f"SOP阶段必须唯一，发现重复阶段：{stage}")
        seen_stages.add(stage)

        sop_id = str(_first_value(row, "ID", "sop_id", "id", "编号") or index).strip()
        wait_minutes = _safe_int(_first_value(row, "客户未回复最长等待时间min", "wait_minutes", "等待时间min"))
        timeout_action = str(_first_value(row, "超时动作", "timeout_action") or "").strip().lower()
        record = KnowledgeSOP(
            sop_id=sop_id,
            stage=stage,
            goal=str(_first_value(row, "任务目标", "goal", "任务", "目标") or "").strip(),
            reference_script=str(_first_value(row, "参考话术", "reference_script", "话术") or "").strip(),
            handover_criteria=str(_first_value(row, "转人工判断", "handover_criteria") or "").strip(),
            wait_minutes=wait_minutes,
            timeout_action=timeout_action,
            raw_json=_json(row),
            search_text=" ".join(str(value) for value in row.values()),
        )
        db.add(record)
        count += 1
    _record_import(db, "sop", path, count)
    return count


def _replace_faq(db: Session, path: Path | None) -> int:
    if not path:
        return 0
    rows = _read_csv(path)
    db.execute(delete(KnowledgeFAQ))
    count = 0
    for index, row in enumerate(rows, start=1):
        faq_id = str(_first_value(row, "faq_id", "FAQ ID", "id") or f"faq-{index}")
        title = str(_first_value(row, "title", "问题", "question", "标题") or f"FAQ {index}")
        content = str(_first_value(row, "content", "答案", "answer", "回答") or "")
        if not content:
            raise ValueError(f"FAQ 第 {index} 行缺少 content")
        tags = _split_list(_first_value(row, "tags", "标签"))
        source_section = str(
            _first_value(row, "source_section", "分类", "category", "章节") or title
        )
        db.add(
            KnowledgeFAQ(
                faq_id=faq_id,
                title=title[:255],
                content=content,
                tags_json=_json(tags),
                source_section=source_section,
                raw_json=_json(row),
                search_text=f"{title}\n{content}",
            )
        )
        count += 1
    _record_import(db, "faq", path, count)
    return count


def _replace_safety_rules(db: Session, path: Path | None) -> int:
    if path is None:
        return 0
    if path.suffix.lower() == ".csv":
        rows = _read_safety_rule_csv(path)
        source_path = path
    elif path.exists():
        rows = _read_safety_rule_table(path)
        source_path = path
    else:
        return 0
    expected_rule_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        rule_id = f"safety-{index:03d}"
        expected_rule_ids.add(rule_id)
        existing = db.get(KnowledgeSafetyRule, rule_id)
        if existing:
            existing.level = row["level"]
            existing.primary_category = row["primary_category"]
            existing.secondary_category = row["secondary_category"]
            existing.standard = row["standard"]
            existing.violation = row["violation"]
            existing.handling_result = row["handling_result"]
        else:
            db.add(
                KnowledgeSafetyRule(
                    rule_id=rule_id,
                    level=row["level"],
                    primary_category=row["primary_category"],
                    secondary_category=row["secondary_category"],
                    standard=row["standard"],
                    violation=row["violation"],
                    handling_result=row["handling_result"],
                )
            )
    if expected_rule_ids:
        existing_rules = db.scalars(select(KnowledgeSafetyRule.rule_id)).all()
        stale_rule_ids = [rule_id for rule_id in existing_rules if rule_id not in expected_rule_ids]
        if stale_rule_ids:
            db.execute(delete(KnowledgeSafetyRule).where(KnowledgeSafetyRule.rule_id.in_(stale_rule_ids)))
    _record_import(db, "safety_rules", source_path, len(rows))
    return len(rows)


def _read_safety_rule_csv(path: Path) -> list[dict[str, str]]:
    rows = _read_csv(path)
    normalized: list[dict[str, str]] = []
    for row in rows:
        normalized.append(
            {
                "level": str(_first_value(row, "level", "等级") or ""),
                "primary_category": str(_first_value(row, "primary_category", "一级类别") or ""),
                "secondary_category": str(_first_value(row, "secondary_category", "二级类别") or ""),
                "standard": str(_first_value(row, "standard", "标准") or ""),
                "violation": str(_first_value(row, "violation", "违规") or ""),
                "handling_result": str(_first_value(row, "handling_result", "处理结果") or ""),
            }
        )
    return normalized


# 风控 PDF 是扫描表格：先用表格线定位行列，再用 OCR 文本落格。
def _read_safety_rule_table(path: Path) -> list[dict[str, str]]:
    try:
        import cv2
        import fitz
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:
        raise RuntimeError("导入风控 PDF 需要 pymupdf、opencv 和 rapidocr-onnxruntime") from exc

    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "safety-rules-page.png"
        with fitz.open(str(path)) as document:
            if not document:
                return []
            document[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(str(image_path))

        image = cv2.imread(str(image_path))
        if image is None:
            return []
        row_lines, table_left, table_right = _detect_safety_table_rows(image)
        if len(row_lines) < 3:
            raise RuntimeError("未能识别风控 PDF 表格线，请检查 PDF 清晰度")

        column_bounds = _safety_column_bounds(table_left, table_right)
        ocr_result, _ = RapidOCR()(str(image_path))
        items = _ocr_items_with_position(ocr_result or [])
        return _build_safety_rows(items, row_lines, column_bounds)


def _detect_safety_table_rows(image: Any) -> tuple[list[int], int, int]:
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, image.shape[1] // 30), 1))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[tuple[int, int, int]] = []
    for contour in contours:
        x, y, width, _height = cv2.boundingRect(contour)
        if width > image.shape[1] * 0.1 and 120 < y < image.shape[0] * 0.9:
            candidates.append((y, x, width))
    if not candidates:
        return [], 0, image.shape[1]

    full_width = max(width for _y, _x, width in candidates)
    full_lines = [(y, x, width) for y, x, width in candidates if width >= full_width * 0.98]
    table_left = min(x for _y, x, _width in full_lines)
    table_right = max(x + width for _y, x, width in full_lines)
    row_lines = _merge_positions([y for y, _x, _width in candidates if table_left - 5 <= _x <= table_right])
    return row_lines, table_left, table_right


def _safety_column_bounds(table_left: int, table_right: int) -> list[int]:
    width = table_right - table_left
    # PDF 表格列从左到右为：等级、一级类别、二级类别、标准、违规、处理结果。
    ratios = [0, 0.033, 0.099, 0.209, 0.359, 0.652, 1]
    return [round(table_left + width * ratio) for ratio in ratios]


def _ocr_items_with_position(result: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        box = item[0]
        text = str(item[1] or "").strip()
        if not text or not isinstance(box, (list, tuple)) or len(box) < 4:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append(
            {
                "text": text,
                "cx": sum(xs) / len(xs),
                "cy": sum(ys) / len(ys),
            }
        )
    return items


def _build_safety_rows(
    items: list[dict[str, Any]],
    row_lines: list[int],
    column_bounds: list[int],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if len(row_lines) < 3:
        return rows

    header_bottom = row_lines[1]
    for row_index in range(1, len(row_lines) - 1):
        top = row_lines[row_index]
        bottom = row_lines[row_index + 1]
        if top < header_bottom:
            continue
        cells = [[] for _ in range(6)]
        for item in items:
            cy = float(item["cy"])
            cx = float(item["cx"])
            if not (top <= cy < bottom):
                continue
            column_index = _safety_column_index(cx, column_bounds)
            if column_index is None:
                continue
            cells[column_index].append(item)

        normalized_cells = [_join_ocr_cell(cell) for cell in cells]
        level, primary_category = _safety_section_for_row((top + bottom) / 2, row_lines)
        # OCR 偶尔会把“C类/过度承诺”“D类/投诉类”分到等级、一级类别格里；以固定分区为准。
        row = {
            "level": level,
            "primary_category": primary_category,
            "secondary_category": _clean_safety_cell(normalized_cells[2]),
            "standard": _clean_safety_cell(normalized_cells[3]),
            "violation": _clean_safety_cell(normalized_cells[4]),
            "handling_result": _clean_safety_cell(normalized_cells[5]),
        }
        if row["primary_category"] == "其他" and not any(
            row[key] for key in ("secondary_category", "standard", "violation", "handling_result")
        ):
            row["standard"] = "其他"
        if any(row[key] for key in ("secondary_category", "standard", "violation", "handling_result")):
            rows.append(row)
    return rows


def _safety_column_index(cx: float, bounds: list[int]) -> int | None:
    for index in range(len(bounds) - 1):
        if bounds[index] <= cx < bounds[index + 1]:
            return index
    return None


def _safety_section_for_row(cy: float, row_lines: list[int]) -> tuple[str, str]:
    section_lines = [row_lines[1]] + [line for line in row_lines[2:] if line >= row_lines[1] and line in _major_safety_lines(row_lines)]
    if len(section_lines) >= 6:
        spans = [
            (section_lines[0], section_lines[1], "A类", "损害公司利益"),
            (section_lines[1], section_lines[2], "B类", "违规操作"),
            (section_lines[2], section_lines[3], "C类", "过度承诺"),
            (section_lines[3], section_lines[4], "D类", "投诉类"),
            (section_lines[4], section_lines[5], "", "其他"),
        ]
        for top, bottom, level, primary in spans:
            if top <= cy < bottom:
                return level, primary
    # 兜底按页面纵向比例分区，避免扫描边框少量缺失导致导入失败。
    if cy < 830:
        return "A类", "损害公司利益"
    if cy < 1430:
        return "B类", "违规操作"
    if cy < 1940:
        return "C类", "过度承诺"
    if cy < 2085:
        return "D类", "投诉类"
    return "", "其他"


def _major_safety_lines(row_lines: list[int]) -> set[int]:
    # 这些分割线对应等级合并单元格的边界：A/B/C/D/其他。
    if len(row_lines) < 6:
        return set(row_lines)
    selected: set[int] = set()
    for target in (829, 1428, 1938, 2080, 2116):
        nearest = min(row_lines, key=lambda value: abs(value - target))
        if abs(nearest - target) <= 20:
            selected.add(nearest)
    return selected


def _join_ocr_cell(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    sorted_items = sorted(items, key=lambda item: (round(float(item["cy"]) / 8), float(item["cx"])))
    return "\n".join(str(item["text"]).strip() for item in sorted_items if str(item["text"]).strip())


def _clean_safety_cell(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _merge_positions(values: list[int], *, tolerance: int = 4) -> list[int]:
    merged: list[int] = []
    for value in sorted(values):
        if not merged or value - merged[-1] > tolerance:
            merged.append(value)
    return merged


def _record_import(db: Session, source_name: str, path: Path, rows: int) -> None:
    db.add(
        KnowledgeImportRun(
            run_id=str(uuid.uuid4()),
            source_name=source_name,
            source_path=str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path),
            status="success",
            rows_imported=rows,
            error_message="",
        )
    )


def _first_existing(base: Path, *filenames: str) -> Path | None:
    for filename in filenames:
        path = base / filename
        if path.exists():
            return path
    return None


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [
            {str(key).strip(): (value or "").strip() for key, value in row.items() if key}
            for row in reader
            if row
        ]


def _chunk_text(text: str, *, max_chars: int) -> Iterable[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
    for start in range(0, len(normalized), max_chars):
        yield normalized[start : start + max_chars].strip()


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def _split_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[;；,，、\n]", text) if item.strip()]


def _safe_int(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    match = re.search(r"-?\d+", text)
    return int(match.group(0)) if match else 0


def _clean_price(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"\d+(?:\.\d+)?", text)
    return match.group(0) if match else text


def _extract_deal_price(text: str) -> str:
    match = re.search(r"(?:成交价|到手价|优惠价|实付)[^\d]*(\d+(?:\.\d+)?)", text)
    return match.group(1) if match else ""


def _search_text(row: dict[str, Any]) -> str:
    return "\n".join(str(value) for value in row.values() if value not in (None, ""))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _utc_now() -> datetime:
    return beijing_now()


def has_imported_knowledge(db: Session) -> bool:
    """判断 knowledge_* 表是否已有可用数据。"""
    return bool(db.execute(select(KnowledgeList.knowledge_key).limit(1)).first())
