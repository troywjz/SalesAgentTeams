from pathlib import Path

from app.knowledge import importer


def _capture_import_paths(monkeypatch) -> dict[str, Path | None]:
    selected_paths: dict[str, Path | None] = {}
    monkeypatch.setattr(importer, "_upsert_catalog", lambda _db: None)
    monkeypatch.setattr(
        importer,
        "_replace_skus",
        lambda _db, path: selected_paths.setdefault("skus", path) is not None,
    )
    monkeypatch.setattr(
        importer,
        "_replace_sop",
        lambda _db, path: selected_paths.setdefault("sop", path) is not None,
    )
    monkeypatch.setattr(
        importer,
        "_replace_faq",
        lambda _db, path: selected_paths.setdefault("faq", path) is not None,
    )
    monkeypatch.setattr(
        importer,
        "_replace_safety_rules",
        lambda _db, path: selected_paths.setdefault("safety_rules", path) is not None,
    )
    monkeypatch.setattr(
        importer,
        "replace_sales_cases",
        lambda _db, path: selected_paths.setdefault("sales_cases", path) is not None,
    )
    monkeypatch.setattr(importer, "_record_import", lambda *_args: None)
    return selected_paths


def _write_source_variants(tmp_path: Path) -> None:
    for filename in (
        "skus.csv",
        "skus.example.csv",
        "sop.csv",
        "sop.example.csv",
        "faq.csv",
        "faq.example.csv",
        "safety_rules.csv",
        "safety_rules.example.csv",
        "sales_cases.csv",
        "sales_cases.example.csv",
    ):
        (tmp_path / filename).write_text(filename, encoding="utf-8")


def test_demo_import_uses_only_public_csv_examples(tmp_path, monkeypatch) -> None:
    _write_source_variants(tmp_path)
    selected_paths = _capture_import_paths(monkeypatch)

    result = importer.import_knowledge_sources(
        knowledge_dir=tmp_path,
        safety_dir=tmp_path,
        db=object(),
        use_example_sources=True,
        include_safety_rules=True,
    )

    assert result["sales_cases"] is True
    assert selected_paths == {
        "skus": tmp_path / "skus.example.csv",
        "sop": tmp_path / "sop.example.csv",
        "faq": tmp_path / "faq.example.csv",
        "safety_rules": tmp_path / "safety_rules.example.csv",
        "sales_cases": tmp_path / "sales_cases.example.csv",
    }


def test_formal_import_prefers_private_csv_sources(tmp_path, monkeypatch) -> None:
    _write_source_variants(tmp_path)
    selected_paths = _capture_import_paths(monkeypatch)

    result = importer.import_knowledge_sources(
        knowledge_dir=tmp_path,
        safety_dir=tmp_path,
        db=object(),
        use_example_sources=False,
        include_safety_rules=True,
    )

    assert result["sales_cases"] is True
    assert selected_paths == {
        "skus": tmp_path / "skus.csv",
        "sop": tmp_path / "sop.csv",
        "faq": tmp_path / "faq.csv",
        "safety_rules": tmp_path / "safety_rules.csv",
        "sales_cases": tmp_path / "sales_cases.csv",
    }
