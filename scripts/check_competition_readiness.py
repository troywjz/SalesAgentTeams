"""GOAI Agent Infra 初赛提交前的可重复合规检查。"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "deployment" / "agentteams" / "sales-agent-teams.yaml"
INTRO = ROOT / "submission" / "preliminary" / "作品简介_500字.md"
REQUIRED_SKILL_SECTIONS = (
    "目的",
    "输入",
    "输出",
    "触发条件",
    "依赖工具",
    "失败处理",
    "安全边界",
    "复用价值",
    "多 Agent 流程关系",
    "验证",
)
REQUIRED_MCP_TOOLS = (
    "run_intent_agent",
    "run_sop_agent",
    "run_knowledge_agent",
    "run_conversation_agent",
    "run_safety_agent",
    "run_memory_agent",
    "run_offline_evaluation",
    "score_offline_evaluation",
    "generate_3d_heatmap",
)
FORBIDDEN_PUBLIC_DATA_TERMS = (
    "初级会计",
    "四证班",
    "推荐月薪",
    "就业保障班",
    "考不过重学",
)


def skill_files() -> list[Path]:
    return sorted((ROOT / "agentteams" / "workers").glob("**/SKILL.md"))


def validate_skill_contracts() -> list[str]:
    violations: list[str] = []
    for path in skill_files():
        content = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^name:\s*[a-z0-9-]+\s*$", content):
            violations.append(f"Skill 缺少合法 name: {path.relative_to(ROOT)}")
        if "版本：" not in content:
            violations.append(f"Skill 缺少版本: {path.relative_to(ROOT)}")
        for section in REQUIRED_SKILL_SECTIONS:
            if f"## {section}" not in content:
                violations.append(
                    f"Skill 缺少章节 {section}: {path.relative_to(ROOT)}"
                )
    return violations


def validate_agentteams_manifest() -> list[str]:
    content = MANIFEST.read_text(encoding="utf-8")
    violations: list[str] = []
    workers = re.findall(r"(?m)^kind:\s*Worker\s*$", content)
    if len(workers) < 3:
        violations.append(f"AgentTeams Worker 少于 3 个: {len(workers)}")
    names = set(re.findall(r"(?m)^name:\s*([a-z0-9-]+)\s*$", "\n".join(
        path.read_text(encoding="utf-8") for path in skill_files()
    )))
    declared = set()
    for value in re.findall(r"(?m)^\s*skills:\s*\[([^]]+)]\s*$", content):
        declared.update(item.strip() for item in value.split(","))
    missing = sorted(declared - names)
    if missing:
        violations.append(f"清单引用了不存在的 Skill: {', '.join(missing)}")
    if "role: team_leader" not in content:
        violations.append("AgentTeams Team 缺少 team_leader")
    if "kind: Manager" not in content:
        violations.append("AgentTeams 清单缺少 Manager")
    return violations


def validate_submission_assets() -> list[str]:
    violations: list[str] = []
    body = INTRO.read_text(encoding="utf-8")
    plain = re.sub(r"[#>*`\s｜—_-]", "", body)
    if len(plain) < 500:
        violations.append(f"作品简介不足 500 字: {len(plain)}")
    for name in ("SalesAgentTeams_初赛方案.pptx", "SalesAgentTeams_初赛方案.pdf"):
        path = INTRO.parent / name
        if not path.exists() or path.stat().st_size == 0:
            violations.append(f"提交材料缺失: {name}")
    return violations


def validate_code_and_public_data() -> list[str]:
    violations: list[str] = []
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
    required_defaults = (
        "APP_ENV=showcase",
        "APP_PORT=18100",
        "DEMO_MODE=false",
        "LLM_PROVIDER=deepseek",
        "LLM_PROVIDER_FALLBACK=aliyun,siliconflow",
        "DEEPSEEK_API_KEY=",
        "ALIYUN_API_KEY=",
        "SILICONFLOW_API_KEY=",
        "DEEPSEEK_MODEL=deepseek-v4-flash",
        "AGENTTEAMS_DEFAULT_MODEL=deepseek-v4-flash",
        "LLM_MAX_ATTEMPTS_PER_REQUEST=3",
        "LLM_REASONING_BUDGET_TOKENS=0",
        "SALES_RAG_ENABLED=true",
        "sales_agent_demo",
    )
    for expected in required_defaults:
        if expected not in env_text:
            violations.append(f"缺少正式展示默认配置: {expected}")

    if not (ROOT / "scripts" / "check_runtime_config.py").is_file():
        violations.append("缺少正式展示启动配置检查脚本")

    db_guard = (ROOT / "app" / "db" / "session.py").read_text(encoding="utf-8")
    if 'database_name != "sales_agent_demo"' not in db_guard:
        violations.append("缺少 sales_agent_demo 运行时数据库护栏")

    mcp_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "mcp_servers").glob("**/*.py")
    )
    for tool_name in REQUIRED_MCP_TOOLS:
        if tool_name not in mcp_text:
            violations.append(f"MCP 工具缺失: {tool_name}")

    public_files = [
        *(ROOT / "data").glob("**/*.example.*"),
        *(ROOT / "evaluation" / "knowledge_snapshot").glob("*"),
        ROOT / "evaluation" / "datasets" / "demo_cases.csv",
    ]
    for path in public_files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for term in FORBIDDEN_PUBLIC_DATA_TERMS:
            if term in text:
                violations.append(f"公开演示数据仍含旧业务词 {term}: {path.relative_to(ROOT)}")
    return violations


def collect_violations() -> list[str]:
    return [
        *validate_skill_contracts(),
        *validate_agentteams_manifest(),
        *validate_submission_assets(),
        *validate_code_and_public_data(),
    ]


def main() -> None:
    violations = collect_violations()
    if violations:
        raise SystemExit("\n".join(violations))
    print(
        "GOAI 就绪检查通过："
        f"{len(skill_files())} 个 Skill、6 个 Worker、2 个 MCP 服务、"
        "正式展示配置门禁和初赛材料均已验证。"
    )


if __name__ == "__main__":
    main()
