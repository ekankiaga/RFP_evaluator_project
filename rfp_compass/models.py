"""Typed data contracts shared by services, providers, and persistence."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class CriterionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: int | str | None = None
    name: str = Field(min_length=1)
    description: str = ""
    weight: float = Field(ge=0, le=100)
    max_score: float = Field(gt=0, default=10)
    what_to_inspect: str = ""
    red_flags: list[str] = Field(default_factory=list)
    evidence_hints: list[str] = Field(default_factory=list)
    is_mandatory_gate: bool = False
    is_active: bool = True


class CriteriaSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria_set_id: str
    name: str
    version: int = Field(ge=1)
    domain_id: str
    merge_mode: str = "Generic + Domain pack"
    items: list[CriterionDefinition]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def unique_names(self) -> "CriteriaSet":
        names = [item.name.casefold().strip() for item in self.items]
        if len(names) != len(set(names)):
            raise ValueError("Criterion names must be unique within a criteria set")
        return self


class TemplateReview(BaseModel):
    filename: str
    proposed_criteria: list[CriterionDefinition]
    issues: list[str] = Field(default_factory=list)
    diff: dict[str, list[dict[str, Any]]] = Field(default_factory=lambda: {"added": [], "changed": [], "removed": []})
    valid: bool = False


class DomainSuggestion(BaseModel):
    domain_id: str
    confidence: float = Field(ge=0, le=1)
    rationale: str
    evidence: str = ""


class Evidence(BaseModel):
    quote: str = ""
    page: int | None = Field(default=None, ge=1)
    verified: bool = False


class CriterionJudgment(BaseModel):
    criterion_id: int | str
    score: float
    max_score: float | None = None
    justification: str = ""
    evidence: str | Evidence = ""
    confidence: str = "medium"


class EvaluationPayload(BaseModel):
    supplier_name: str = ""
    criteria: list[CriterionJudgment] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    overall_summary: str = ""
    gates: list[dict[str, Any]] = Field(default_factory=list)


class SupplierInput(BaseModel):
    supplier_name: str = Field(min_length=1)
    submission_date: date
    experience_rating: float = Field(ge=1, le=10)
    document_hash: str = ""


class ProviderKind(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    AZURE_OPENAI = "azure_openai"
    MISTRAL = "mistral"
    GROQ = "groq"
    TOGETHER = "together"
    OPENROUTER = "openrouter"
    DEEPSEEK = "deepseek"
    COHERE = "cohere"
    OLLAMA = "ollama"
    LM_STUDIO = "lm_studio"
    VLLM = "vllm"
    CUSTOM_OPENAI = "custom_openai"
    LITELLM = "litellm"
    MOCK = "mock"


class ConnectionConfig(BaseModel):
    """Session-only provider configuration. Never persist or serialize its key."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    connection_id: str
    provider_id: ProviderKind
    model: str
    api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    base_url: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    azure_api_version: str | None = None
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    max_output_tokens: int = Field(default=3000, gt=0)
    retries: int = Field(default=2, ge=0, le=10)
    temperature: float = Field(default=0, frozen=True)
    allow_local_network: bool = False


class StageResult(BaseModel):
    name: str
    status: str
    message: str = ""
    latency_ms: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ConnectionHealth(BaseModel):
    status: str
    provider_id: str
    model: str
    tested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stages: list[StageResult] = Field(default_factory=list)
    latency_ms: float | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    key_fingerprint: str | None = None


class AuditEvent(BaseModel):
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rfp_run_id: str | None = None
    actor: str
    role: str
    event_type: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
