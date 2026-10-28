from __future__ import annotations

import json
import random
from datetime import date

import pytest

from rfp_compass.audit.audit_log import AuditLog
from rfp_compass.db import connect
from rfp_compass.llm.connection_tester import validate_base_url
from rfp_compass.llm.errors import ErrorCategory, classify_exception, classify_http_error
from rfp_compass.llm.base import GenerationResult, LLMProvider
from rfp_compass.llm.mock_provider import MockLLM
from rfp_compass.models import ConnectionConfig, ProviderKind
from rfp_compass.orchestrator import Orchestrator
from rfp_compass.agents.evaluation_agent import EvaluationAgent
from rfp_compass.agents.template_parser_agent import TemplateParserAgent
from rfp_compass.tools.criteria_tool import CriteriaTool
from rfp_compass.tools.ranking_tool import RankingTool
from rfp_compass.tools.scoring_tool import absolute_weighted_score, benchmark_metrics, peer_performance_index
from rfp_compass.tools.validation_tool import ValidationTool
from rfp_compass.tools.what_if_tool import WhatIfEngine


@pytest.fixture
def criteria():
    return [
        {"criterion_id": 1, "name": "A", "weight": 60, "max_score": 10, "is_active": True},
        {"criterion_id": 2, "name": "B", "weight": 40, "max_score": 10, "is_active": True},
    ]


def test_weight_normalization(criteria):
    criteria[0]["weight"], criteria[1]["weight"] = 3, 1
    normalized = CriteriaTool.normalize_weights(criteria)
    assert [c["weight"] for c in normalized] == [75, 25]
    assert CriteriaTool.validate_weights(normalized)


def test_score_and_peer_formulas(criteria):
    scores = [{"criterion_id": 1, "score": 8}, {"criterion_id": 2, "score": 5}]
    assert absolute_weighted_score(scores, criteria) == pytest.approx(68)
    peers = {"Apex": scores, "Bright": [{"criterion_id": 1, "score": 4}, {"criterion_id": 2, "score": 0}]}
    metrics = benchmark_metrics(peers, criteria)
    assert metrics["Apex"]["1"]["gap"] == 0
    assert metrics["Bright"]["1"]["gap"] == -4
    assert metrics["Bright"]["2"]["relative_pct"] == 0
    assert peer_performance_index(metrics["Apex"], criteria) == pytest.approx(100)


def test_zero_benchmark_is_one_hundred_percent_for_zero(criteria):
    metrics = benchmark_metrics({"A": [{"criterion_id": 1, "score": 0}, {"criterion_id": 2, "score": 0}]}, criteria)
    assert metrics["A"]["1"]["relative_pct"] == 100


def test_validation_clips_fills_drops_unknown_and_checks_evidence(criteria):
    raw = {"criteria": [
        {"criterion_id": 1, "score": 12, "justification": "x", "evidence": "Evidence sentence."},
        {"criterion_id": 999, "score": 2},
    ]}
    payload, warnings = ValidationTool().validate(raw, criteria, [{"page": 1, "text": "Evidence sentence."}])
    assert len(payload.criteria) == 2
    assert payload.criteria[0].score == 10
    assert payload.criteria[0].evidence.page == 1
    assert payload.criteria[1].score == 0
    assert any("unknown" in warning for warning in warnings)
    assert any("Missing criterion" in warning for warning in warnings)


def test_validation_strips_markdown_and_repair_prompt():
    tool = ValidationTool()
    parsed = tool.parse_json('```json\n{"criteria": []}\n```')
    assert parsed == {"criteria": []}
    assert "Return JSON only" in tool.repair_prompt("bad", "syntax")


def test_ranking_tiebreak_order(criteria):
    ranking = RankingTool()
    items = [
        {"supplier_name": "Zeta", "ppi": 90, "submission_date": "2025-01-02", "experience_rating": 9},
        {"supplier_name": "Beta", "ppi": 90, "submission_date": "2025-01-01", "experience_rating": 3},
        {"supplier_name": "Alpha", "ppi": 90, "submission_date": "2025-01-01", "experience_rating": 8},
        {"supplier_name": "Aaron", "ppi": 90, "submission_date": "2025-01-01", "experience_rating": 8},
        {"supplier_name": "Winner", "ppi": 95, "submission_date": "2025-01-09", "experience_rating": 1},
    ]
    ranked = ranking.rank(items)
    assert [x["supplier_name"] for x in ranked] == ["Winner", "Aaron", "Alpha", "Beta", "Zeta"]
    assert "name ascending" in ranked[1]["tie_break_explanation"]
    assert "earlier submission date" in ranked[3]["tie_break_explanation"]


def test_ranking_is_independent_of_input_order(criteria):
    base = [{"supplier_name": f"S{i}", "ppi": 50 + (i % 3), "submission_date": f"2025-01-{i+1:02d}", "experience_rating": i % 4} for i in range(20)]
    expected = [item["supplier_name"] for item in RankingTool().rank(base)]
    for seed in range(100):
        shuffled = base.copy()
        random.Random(seed).shuffle(shuffled)
        assert [item["supplier_name"] for item in RankingTool().rank(shuffled)] == expected


def test_audit_chain_and_tamper_detection(tmp_path):
    db = tmp_path / "audit.sqlite"
    audit = AuditLog(db)
    audit.append(actor="a", role="Analyst", event_type="x", entity_type="run", entity_id="1", timestamp_utc="2025-01-01T00:00:00Z")
    audit.append(actor="a", role="Analyst", event_type="y", entity_type="run", entity_id="1", timestamp_utc="2025-01-02T00:00:00Z")
    assert audit.verify() == (True, None)
    with connect(db) as conn:
        conn.execute("UPDATE audit_log SET after_json='{}' WHERE id=1")
    assert audit.verify() == (False, 1)


def test_base_url_ssrf_guards(monkeypatch):
    import socket
    real_getaddrinfo = socket.getaddrinfo
    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "api.openai.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("104.18.33.45", 443))]
        return real_getaddrinfo(host, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert validate_base_url("http://localhost:11434/v1", allow_local_network=True)[0]
    assert not validate_base_url("http://example.com/v1")[0]
    assert not validate_base_url("https://10.0.0.8/v1")[0]
    assert not validate_base_url("https://metadata.google.internal")[0]
    assert validate_base_url("https://api.openai.com/v1")[0]


@pytest.mark.parametrize("status,hint,expected", [
    (401, "", ErrorCategory.INVALID_KEY), (403, "", ErrorCategory.INVALID_KEY),
    (404, "model not found", ErrorCategory.MODEL_NOT_FOUND), (404, "", ErrorCategory.WRONG_URL),
    (429, "", ErrorCategory.RATE_LIMITED), (429, "quota exceeded", ErrorCategory.QUOTA),
    (503, "", ErrorCategory.PROVIDER_OUTAGE),
])
def test_http_error_classification(status, hint, expected):
    assert classify_http_error(status, hint) == expected


def test_network_error_classification():
    class SSLError(Exception):
        pass
    class ConnectError(Exception):
        pass
    assert classify_exception(TimeoutError()) == ErrorCategory.TIMEOUT
    assert classify_exception(SSLError("certificate verify failed")) == ErrorCategory.SSL
    assert classify_exception(ConnectError("DNS resolution failed")) == ErrorCategory.NETWORK
    assert classify_exception(json.JSONDecodeError("bad", "{", 1)) == ErrorCategory.MALFORMED_JSON


class FlakyProvider(LLMProvider):
    def __init__(self, config, failures=0):
        super().__init__(config)
        self.failures = failures
        self.calls = 0

    def generate_json(self, system, user, schema, **opts):
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("temporary")
        return GenerationResult('{"ok":true}', self.config.model)

    def list_models(self):
        return [self.config.model]


def test_retry_cache_and_model_keying(tmp_path):
    cfg = ConnectionConfig(connection_id="fake", provider_id=ProviderKind.MOCK, model="m1")
    primary = FlakyProvider(cfg, failures=1)
    orch = Orchestrator(primary, tmp_path / "cache.sqlite", retries=1)
    first, _, hit = orch._generate("sys", "proposal", {}, "doc", [{"name": "C"}])
    assert first.text == '{"ok":true}' and not hit and primary.calls == 2
    orch._generate("sys", "proposal", {}, "doc", [{"name": "C"}])
    assert primary.calls == 2
    orch._generate("sys", "proposal", {}, "doc", [{"name": "C"}], bypass_cache=True)
    assert primary.calls == 3
    orch.prompt_version = "v2"
    orch._generate("sys", "proposal", {}, "doc", [{"name": "C"}])
    assert primary.calls == 4


def _minimal_pdf(text: str) -> bytes:
    import pymupdf
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((60, 80), text)
    return document.tobytes()


def test_end_to_end_mock_pipeline(tmp_path, criteria):
    config = ConnectionConfig(connection_id="offline", provider_id=ProviderKind.MOCK, model="mock-rfp-v1")
    orchestrator = Orchestrator(MockLLM(config), tmp_path / "e2e.sqlite")
    result = orchestrator.evaluate([{
        "supplier_name": "Demo Supplier", "submission_date": date(2025, 1, 2),
        "experience_rating": 7, "pdf": _minimal_pdf("Technical architecture is scalable. Security controls and support plan are documented.")
    }], criteria=criteria)
    assert result["rfp_run_id"].startswith("RFP-")
    assert result["suppliers"][0]["rank"] == 1
    assert result["suppliers"][0]["absolute_score"] > 0
    assert len(result["suppliers"][0]["scores"]) == 2
    assert result["steps"][-1]["status"] == "complete"


def test_template_json_parse_validation_and_pack_diff():
    content = json.dumps({"criteria": [
        {"name": "Delivery Method", "description": "Assess documented delivery approach.", "weight": 70,
         "max_score": 10, "what_to_inspect": "Method and milestones", "red_flags": "no milestones|unclear owners"},
        {"name": "Price Transparency", "description": "Assess price details and assumptions.", "weight": 30,
         "max_score": 5, "is_mandatory_gate": "no"},
    ]}).encode()
    pack = {"resolved_criteria": [{"name": "Delivery Method", "description": "Old description.", "weight": 50, "max_score": 10},
                                    {"name": "Security Review", "description": "Review controls.", "weight": 50, "max_score": 10}]}
    review = TemplateParserAgent().parse(content, "custom.json", pack)
    assert review.valid
    assert review.diff["changed"][0]["name"] == "Delivery Method"
    assert review.diff["added"][0]["name"] == "Price Transparency"
    assert review.diff["removed"][0]["name"] == "Security Review"


def test_evaluation_agent_prompt_evidence_and_deterministic_chunk_merge(criteria):
    config = ConnectionConfig(connection_id="mock", provider_id=ProviderKind.MOCK, model="mock-rfp-v1")
    provider = MockLLM(config)
    def generate(system, user, schema, **opts):
        return provider.generate_json(system, user, schema)
    agent = EvaluationAgent(generate, chunk_chars=45)
    eval_criteria = [{"criterion_id": "tech", "name": "Technical Capability", "weight": 50, "max_score": 10},
                     {"criterion_id": "plan", "name": "Implementation Plan", "weight": 50, "max_score": 10}]
    pages = [{"page": 1, "text": "The technical architecture plan has detailed evidence. "},
             {"page": 2, "text": "The implementation plan includes another documented assessment."}]
    payload, warnings = agent.evaluate(supplier_name="A", criteria=eval_criteria, pages=pages, domain_addendum="SaaS guidance.")
    assert len(payload.criteria) == 2
    assert payload.criteria[0].evidence.quote
    assert any("page chunks" in warning for warning in warnings)


def test_what_if_and_sensitivity_are_deterministic():
    criteria = [{"criterion_id": "x", "name": "Technical", "weight": 50, "max_score": 10},
                {"criterion_id": "y", "name": "Commercial", "weight": 50, "max_score": 10}]
    suppliers = [
        {"supplier_name": "Apex", "submission_date": "2025-01-01", "experience_rating": 7, "scores": [
            {"criterion_id": "x", "score": 9, "max_score": 10}, {"criterion_id": "y", "score": 4, "max_score": 10}]},
        {"supplier_name": "Bright", "submission_date": "2025-01-02", "experience_rating": 6, "scores": [
            {"criterion_id": "x", "score": 5, "max_score": 10}, {"criterion_id": "y", "score": 10, "max_score": 10}]},
    ]
    engine = WhatIfEngine()
    one = engine.evaluate(suppliers, criteria, {"x": 70, "y": 30})
    two = engine.evaluate(list(reversed(suppliers)), criteria, {"x": 70, "y": 30})
    assert [s["supplier_name"] for s in one["ranked_suppliers"]] == [s["supplier_name"] for s in two["ranked_suppliers"]]
    assert one["official"] is False
    assert engine.sensitivity(suppliers, criteria, simulations=25, seed=7) == engine.sensitivity(suppliers, criteria, simulations=25, seed=7)
