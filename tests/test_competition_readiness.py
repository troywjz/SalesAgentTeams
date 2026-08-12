from scripts.check_competition_readiness import (
    collect_violations,
    skill_files,
)


def test_goai_competition_readiness_contract() -> None:
    assert len(skill_files()) >= 8
    assert collect_violations() == []
