from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from agentteams.build_worker_packages import OUTPUT_ROOT, build
from scripts.runtime_fingerprint import build_fingerprint, iter_build_files


ROOT = Path(__file__).resolve().parents[1]


def test_public_lifecycle_entrypoints_exist() -> None:
    for relative_path in (
        "setup.cmd",
        "start_all.cmd",
        "stop_all.cmd",
        "scripts/setup_project.ps1",
        "scripts/start_all.ps1",
        "scripts/stop_all.ps1",
    ):
        assert (ROOT / relative_path).is_file(), relative_path


def test_lifecycle_configuration_and_secret_boundaries() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in (
        "AGENTTEAMS_ENABLED=true",
        "AGENTTEAMS_LLM_PROVIDER=",
        "AGENTTEAMS_OPENAI_BASE_URL=",
        "AGENTTEAMS_DEFAULT_MODEL=",
        "AGENTTEAMS_LLM_API_KEY=",
    ):
        assert key in env_example

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".env\n" in dockerignore
    assert ".runtime\n" in dockerignore
    assert "evaluation/private_datasets\n" in dockerignore
    assert "data/*\n" in dockerignore
    assert "!data/knowledge/faq.example.csv\n" in dockerignore

    stop_script = (ROOT / "scripts" / "stop_all.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "deployment/docker-compose.demo-db.yml" in stop_script
    assert "deployment/docker-compose.mcp.yml" in stop_script
    assert "sales_agent-sales-agent" not in stop_script
    assert "sales_agent-postgres" not in stop_script
    assert "sales_agent-redis" not in stop_script


def test_worker_package_build_is_reproducible() -> None:
    first_outputs = build()
    first_hashes = {
        output.name: sha256(output.read_bytes()).hexdigest()
        for output in first_outputs
    }
    second_outputs = build()
    second_hashes = {
        output.name: sha256(output.read_bytes()).hexdigest()
        for output in second_outputs
    }

    assert first_hashes == second_hashes
    assert set(first_hashes) == {
        "conversation_worker.zip",
        "intent_worker.zip",
        "knowledge_worker.zip",
        "memory_worker.zip",
        "safety_worker.zip",
        "sop_worker.zip",
    }
    assert all((OUTPUT_ROOT / name).is_file() for name in first_hashes)


def test_mcp_build_fingerprint_is_stable_and_excludes_private_results() -> None:
    first = build_fingerprint()
    second = build_fingerprint()
    relative_paths = {
        path.relative_to(ROOT).as_posix() for path in iter_build_files()
    }

    assert first == second
    assert len(first) == 64
    assert "requirements.txt" in relative_paths
    assert "deployment/Dockerfile.mcp" in relative_paths
    assert not any("private_datasets" in path for path in relative_paths)
    assert not any("evaluation/results" in path for path in relative_paths)
