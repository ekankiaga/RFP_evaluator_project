from __future__ import annotations

import json
import sqlite3
import sys
import types

import pymupdf
import pytest

from rfp_compass.agents.evaluation_agent import EvaluationAgent
from rfp_compass.llm.base import GenerationResult, LLMProvider
from rfp_compass.llm.connection_tester import ConnectionTester
from rfp_compass.llm.errors import ErrorCategory, classify_exception, classify_http_error
from rfp_compass.llm.key_vault import SessionKeyVault, redact
from rfp_compass.llm.mock_provider import MockLLM
from rfp_compass.db import connect, migrate
from rfp_compass.models import ConnectionConfig, ProviderKind
from rfp_compass.orchestrator import Orchestrator
from rfp_compass.tools.ranking_tool import RankingTool


def mock_config(model: str = "mock-deterministic") -> ConnectionConfig:
    return ConnectionConfig(connection_id="phase5", provider_id=ProviderKind.MOCK, model=model)


class FailingProvider(LLMProvider):
    def generate_json(self, system, user, schema, **opts):
        raise RuntimeError("primary unavailable")

    def list_models(self):
        return [self.config.model]


class CountingMock(MockLLM):
    calls = 0

    def generate_json(self, *args, **kwargs):
        self.calls += 1
        return super().generate_json(*args, **kwargs)


def test_session_vault_isolation_and_secret_redaction():
    first_state, second_state = {}, {}
    first, second = SessionKeyVault(first_state), SessionKeyVault(second_state)
    raw = "sk-test-secret-value-123456789"
    first.set("openai", raw)
    assert first.get("openai").get_secret_value() == raw
    assert second.get("openai") is None
    assert raw not in redact(f"provider said {raw}")
    first.clear("openai")
    assert first.get("openai") is None
    assert not first_state


def test_fallback_provider_is_used_when_primary_fails():
    primary = FailingProvider(mock_config())
    fallback = MockLLM(mock_config())
    orchestrator = Orchestrator(primary, fallback_provider=fallback, retries=0)
    result, used_provider, cached = orchestrator._generate("sys", "user", {}, "doc-hash", [])
    assert used_provider is fallback
    assert json.loads(result.text)
    assert cached is False


def test_malformed_json_gets_one_repair_attempt():
    calls = []
    def generate(system, user, schema, **opts):
        calls.append(user)
        if len(calls) == 1:
            return GenerationResult("not-json", "test")
        payload = {"supplier_name": "Demo", "criteria": [{"criterion_id": "sec", "score": 8,
            "max_score": 10, "justification": "Found control.", "evidence": "AES-256 protects stored data.", "confidence": "high"}],
            "risks": [], "overall_summary": "Pass", "gates": []}
        return GenerationResult(json.dumps(payload), "test")
    payload, warnings = EvaluationAgent(generate).evaluate(supplier_name="Demo",
        criteria=[{"criterion_id": "sec", "name": "Security", "weight": 100, "max_score": 10}],
        pages=[{"page": 1, "text": "AES-256 protects stored data."}])
    assert payload.criteria[0].score == 8
    assert len(calls) == 2
    assert any("repaired once" in warning for warning in warnings)


def test_mandatory_gate_failure_ranks_below_compliant_supplier():
    ranked = RankingTool().rank([
        {"supplier_name": "High Score", "compliant": False, "ppi": 100, "submission_date": "2026-01-01", "experience_rating": 10},
        {"supplier_name": "Compliant", "compliant": True, "ppi": 70, "submission_date": "2026-01-02", "experience_rating": 6},
    ])
    assert [item["supplier_name"] for item in ranked] == ["Compliant", "High Score"]


def test_budget_cap_aborts_before_provider_call(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "The proposal provides secure implementation and support evidence.")
    pdf = doc.tobytes()
    doc.close()
    provider = CountingMock(mock_config("gpt-4o-mini"))
    orchestrator = Orchestrator(provider, db_path=tmp_path / "budget.sqlite3", retries=0)
    with pytest.raises(ValueError, match="exceeds budget cap"):
        orchestrator.evaluate([{"supplier_name": "Demo", "submission_date": "2026-01-01",
            "experience_rating": 5, "pdf": pdf}], criteria=[{"criterion_id": "security", "name": "Security",
            "weight": 100, "max_score": 10, "is_active": True}], budget_cap_usd=1e-12)
    assert provider.calls == 0


def test_connection_tester_mock_and_error_classification():
    health = ConnectionTester().test(mock_config())
    assert health.status == "passed"
    assert classify_http_error(429, "quota exceeded") == ErrorCategory.QUOTA
    assert classify_http_error(401) == ErrorCategory.INVALID_KEY
    assert classify_exception(TimeoutError("late")) == ErrorCategory.TIMEOUT


def test_custom_database_adapter_factory_hook(monkeypatch):
    captured = {}
    module = types.ModuleType("test_custom_db_adapter")
    def factory(uri):
        captured["uri"] = uri
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        return connection
    module.connect = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("RFP_COMPASS_DB_ADAPTER", "custom")
    monkeypatch.setenv("RFP_COMPASS_DB_ADAPTER_FACTORY", "test_custom_db_adapter:connect")
    with connect("file:remote-demo") as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('ok')")
        assert connection.execute("SELECT value FROM sample").fetchone()["value"] == "ok"
    assert captured["uri"] == "file:remote-demo"


def test_none_database_path_uses_configured_default(tmp_path, monkeypatch):
    import rfp_compass.db as database
    default_db = tmp_path / "default.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", default_db)
    migrate(None)
    with connect(None) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='rfp_runs'").fetchone()[0] == "rfp_runs"


def test_key_is_not_serialized_to_run_database_or_export(tmp_path):
    from rfp_compass.ui.pages.export import _exportable_run

    key = "sk-sentinel-never-persist-this-123456"
    config = ConnectionConfig(connection_id="secret-test", provider_id=ProviderKind.MOCK,
        model="mock-deterministic", api_key=key)
    assert key not in config.model_dump_json()
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Security controls and implementation plan are documented.")
    pdf = doc.tobytes()
    doc.close()
    db_path = tmp_path / "no-secret.sqlite3"
    run = Orchestrator(MockLLM(config), db_path=db_path, retries=0).evaluate(
        [{"supplier_name": "Demo", "submission_date": "2026-01-01", "experience_rating": 5,
          "document_name": "demo.pdf", "pdf": pdf}],
        criteria=[{"criterion_id": "security", "name": "Security", "weight": 100, "max_score": 10, "is_active": True}],
        run_id="NO-SECRET-001")
    exported = json.dumps(_exportable_run(run), default=str)
    assert "document_pages" not in exported
    assert key not in exported
    assert key.encode() not in db_path.read_bytes()
