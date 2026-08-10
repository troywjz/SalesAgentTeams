from app.knowledge.loader import KnowledgeLoader


def test_knowledge_loader_never_selects_safety_rules_for_knowledge() -> None:
    loader = KnowledgeLoader()

    selected = loader.select_knowledge_sources(
        message="这个课程多少钱，有没有优惠？",
        intent={},
        current_stage="开场",
    )

    assert "skus" in selected
    assert "safety_rules" not in selected


def test_knowledge_loader_skips_skus_for_exam_process_question() -> None:
    loader = KnowledgeLoader()

    selected = loader.select_knowledge_sources(
        message="初级会计怎么考，需要什么条件？",
        intent={},
        current_stage="开场",
    )

    assert "faq" in selected
    assert "skus" not in selected
    assert "safety_rules" not in selected


def test_knowledge_loader_treats_legacy_price_cents_as_yuan(tmp_path) -> None:
    (tmp_path / "skus.example.csv").write_text(
        "\ufeffsku_id,sku_name,price_cents,currency,discount_policy\n"
        "sku-1,初级会计体验课,598,CNY,限时实际成交价298\n",
        encoding="utf-8",
    )
    loader = KnowledgeLoader(tmp_path)
    loader._query_context_from_db = lambda **_: None  # type: ignore[method-assign]

    context = loader.query_context(
        message="这个课程多少钱？",
        intent={},
        current_stage="开场",
    )

    assert context["skus"][0]["sku_name"] == "初级会计体验课"
    assert context["skus"][0]["list_price_yuan"] == "598"
    assert "price_cents" not in context["skus"][0]


def test_knowledge_loader_reads_faq_from_csv_when_database_is_unavailable(tmp_path) -> None:
    (tmp_path / "faq.example.csv").write_text(
        "faq_id,title,content,tags\n"
        "faq-1,零基础可以学习吗？,可以从常见办公任务开始学习。,零基础;学习\n",
        encoding="utf-8",
    )
    (tmp_path / "sop.example.csv").write_text(
        "ID,SOP阶段,任务描述\n1,开场,确认需求\n",
        encoding="utf-8",
    )
    loader = KnowledgeLoader(tmp_path)
    loader._query_context_from_db = lambda **_: None  # type: ignore[method-assign]

    context = loader.query_context(
        message="零基础可以学习吗？",
        intent={},
        current_stage="开场",
    )

    assert "零基础可以学习吗？" in context["faq"]
    assert "可以从常见办公任务开始学习" in context["faq"]
