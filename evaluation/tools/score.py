from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 同时支持 `python evaluation/tools/score.py` 和 `python -m evaluation.tools.score`。
PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from evaluation.core.scoring import (
    EvaluationScoringError,
    create_blind_review_package,
    score_blind_review,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成销售回复盲评表或汇总盲评分数")
    parser.add_argument("--run-dir", type=Path, required=True, help="evaluation/results 下的一次运行目录")
    parser.add_argument(
        "--create-blind-review",
        action="store_true",
        help="重新生成盲评表和来源映射；正常运行评测时已自动生成，无需重复执行",
    )
    parser.add_argument("--review-file", type=Path, help="评审人填写完成的盲评 CSV")
    parser.add_argument("--mapping-file", type=Path, help="来源映射 CSV，默认使用运行目录中的盲评映射.csv")
    parser.add_argument("--output-dir", type=Path, help="评分文件输出目录，默认本次运行目录")
    parser.add_argument(
        "--force",
        action="store_true",
        help="仅与 --create-blind-review 同用，确认覆盖已有盲评表和映射",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.create_blind_review:
            review_path, mapping_path = create_blind_review_package(
                args.run_dir,
                overwrite=args.force,
            )
            print(
                json.dumps(
                    {"blind_review": str(review_path), "blind_mapping": str(mapping_path)},
                    ensure_ascii=False,
                )
            )
            return 0
        if args.review_file is None:
            raise EvaluationScoringError(
                "请提供 --review-file；盲评表会在运行评测后自动生成。"
            )
        summary = score_blind_review(
            args.run_dir,
            args.review_file,
            mapping_file=args.mapping_file,
            output_dir=args.output_dir,
        )
    except EvaluationScoringError as exc:
        print(f"评分未完成：{exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "turns_total": summary.turns_total,
                "human_sales_score": round(summary.human_score, 2),
                "system_sales_score": round(summary.system_score, 2),
                "system_minus_human": round(summary.score_difference, 2),
                "technical_failed_turns": summary.technical_failed_turns,
                "score_detail": str(summary.score_detail_path),
                "evaluation_report": str(summary.report_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
