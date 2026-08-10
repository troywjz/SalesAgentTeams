"""AgentTeams Worker 与 MCP 之间共享的最小数据契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    task_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    conversation_state: dict[str, Any] = Field(default_factory=dict)
    allowed_knowledge_refs: list[str] = Field(default_factory=list)
    mode: Literal["load", "run", "update"] = "run"


class Handoff(BaseModel):
    required: bool = False
    target: str | None = None
    reason: str | None = None


class AgentResponse(BaseModel):
    task_id: str
    worker_id: str
    skill_version: str
    status: Literal["success", "failed", "handoff"]
    output: dict[str, Any] | str = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    handoff: Handoff = Field(default_factory=Handoff)
    error: str | None = None


class EvaluationRunRequest(BaseModel):
    dataset_path: str = Field(min_length=1)
    output_dir: str | None = None
    model_mode: Literal["demo", "configured"] = "demo"
    review_path: str | None = None


class EvaluationScoreRequest(BaseModel):
    run_dir: str = Field(min_length=1)
    review_path: str = Field(min_length=1)
    output_dir: str | None = None


class HeatmapRequest(BaseModel):
    run_dir: str = Field(min_length=1)
    source: Literal["system", "human", "both"] = "system"
    output_dir: str | None = None
