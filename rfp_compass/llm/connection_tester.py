"""Staged connection diagnostics with endpoint safety checks and friendly errors."""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from urllib.parse import urlparse

from ..models import ConnectionConfig, ConnectionHealth, StageResult
from .errors import ErrorCategory, FRIENDLY_MESSAGES, classify_exception
from .key_vault import key_fingerprint
from .provider_factory import create_provider
from .pricing import estimate_cost
from .key_vault import redact
from .registry import get_provider
from ..tools.validation_tool import ValidationTool

METADATA_IPS = {"169.254.169.254", "100.100.100.200"}


def validate_base_url(url: str | None, allow_local_network: bool = False) -> tuple[bool, str]:
    """Reject unsafe schemes and private/link-local/metadata destinations by default."""
    if not url:
        return True, "No custom endpoint URL required."
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "Endpoint URL must contain a hostname."
    local = host.casefold() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        return False, "HTTPS is required except for localhost endpoints."
    if local and not allow_local_network:
        return False, "Local endpoints require the explicit allow-local-network option."
    if host.casefold() in {"metadata.google.internal", "metadata", "instance-data"}:
        return False, "Cloud metadata endpoints are blocked."
    try:
        addresses = {ipaddress.ip_address(host)} if _is_ip(host) else {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
    except (OSError, ValueError):
        return False, "Endpoint host could not be resolved."
    if any(str(ip) in METADATA_IPS for ip in addresses):
        return False, "Cloud metadata IP addresses are blocked."
    if not allow_local_network and any(not ip.is_global for ip in addresses):
        return False, "Private, loopback, and link-local IP ranges are blocked."
    return True, "Endpoint URL is syntactically safe."


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class ConnectionTester:
    """Run configuration, reachability, model, JSON, and smoke diagnostics."""
    def test(self, config: ConnectionConfig) -> ConnectionHealth:
        stages: list[StageResult] = []
        started = time.perf_counter()
        provider_id = config.provider_id.value
        if provider_id == "mock":
            return ConnectionHealth(status="passed", provider_id=provider_id, model=config.model,
                stages=[StageResult(name="Config check", status="pass", message="Mock provider needs no key."),
                        StageResult(name="JSON capability", status="pass", message="Deterministic JSON mode available."),
                        StageResult(name="Mini evaluation smoke test", status="pass", message="Mock evaluation pipeline ready.")],
                latency_ms=0, capabilities={"json_mode": "native", "context_window": None})
        if provider_id == "litellm":
            try:
                import litellm  # noqa: F401
            except ImportError:
                return ConnectionHealth(status="failed", provider_id=provider_id, model=config.model,
                    stages=[StageResult(name="Optional dependency", status="fail",
                        message="LiteLLM is not installed. Run `python -m pip install -r requirements-litellm.txt`, then restart the app.")])
        spec = get_provider(provider_id)
        url = config.base_url or config.azure_endpoint or spec.default_base_url
        valid, message = validate_base_url(url, config.allow_local_network)
        required_ok = bool(config.model) and (not config.api_key is None or provider_id in {"ollama", "lm_studio", "vllm", "litellm"})
        if provider_id == "custom_openai" and not config.base_url:
            required_ok = False
        if provider_id == "azure_openai":
            required_ok = required_ok and bool(config.azure_endpoint and config.azure_deployment and config.azure_api_version and config.api_key)
        stages.append(StageResult(name="Config check", status="pass" if valid and required_ok else "fail",
                                  message=message if valid else message))
        if not valid or not required_ok:
            if valid and not required_ok:
                stages[-1].message = "Model ID or required API key is missing. Save the connection again with the key, or configure the provider's environment variable."
            return ConnectionHealth(status="failed", provider_id=provider_id, model=config.model, stages=stages,
                key_fingerprint=key_fingerprint(config.api_key.get_secret_value()) if config.api_key else None)
        try:
            provider = create_provider(config)
            begin = time.perf_counter()
            models = provider.list_models()
            latency = (time.perf_counter() - begin) * 1000
            reachability_message = "Provider responded through the configured LiteLLM route." if provider_id == "litellm" else f"Provider responded; {len(models)} model(s) visible."
            stages.append(StageResult(name="Reachability and auth", status="pass", latency_ms=latency,
                                      message=reachability_message))
            model_ok = config.model in models or provider_id in {"anthropic", "gemini", "cohere", "azure_openai", "ollama", "lm_studio", "vllm", "custom_openai", "litellm"}
            stages.append(StageResult(name="Model availability", status="pass" if model_ok else "warn",
                                      message="Selected model is available." if model_ok else "Model not in returned model list."))
            result = provider.generate_json("Return strict JSON only.", 'Return exactly {"ok":true}', {"type": "object", "properties": {"ok": {"type": "boolean"}}}, max_output_tokens=256)
            try:
                json.loads(result.text)
                json_ok, json_message = True, "Received parseable JSON from the selected model."
            except (json.JSONDecodeError, TypeError):
                json_ok, json_message = False, "Provider response was not valid JSON."
            stages.append(StageResult(name="JSON capability test", status="pass" if json_ok else "fail",
                                      message=json_message, latency_ms=result.latency_ms))
            proposal = "The supplier provides an encrypted deployment. Evidence: AES-256 encryption is enabled for stored records. The rollout uses two migration milestones."
            dummy_criteria = [{"criterion_id": "security", "name": "Security Controls", "max_score": 10, "weight": 50},
                              {"criterion_id": "delivery", "name": "Delivery Plan", "max_score": 10, "weight": 50}]
            smoke_prompt = ("Evaluate only the short proposal. Return JSON with criteria array. For each criterion include criterion_id, score from 0 to 10, "
                "justification, evidence as an exact quote from proposal, and page: 1. Return both criteria.\nCriteria: " + json.dumps(dummy_criteria) + "\nProposal page 1: " + proposal)
            smoke = provider.generate_json("You are a strict proposal evaluator. Return JSON only.", smoke_prompt,
                {"type": "object", "properties": {"criteria": {"type": "array"}}}, max_output_tokens=1200)
            normalized, smoke_warnings = ValidationTool().validate(smoke.text, dummy_criteria, [{"page": 1, "text": proposal}])
            smoke_ok = (len(normalized.criteria) == 2 and all(0 <= c.score <= 10 for c in normalized.criteria)
                        and all(getattr(c.evidence, "verified", False) for c in normalized.criteria)
                        and not any("clip" in warning.casefold() or "evidence not found" in warning.casefold() for warning in smoke_warnings))
            stages.append(StageResult(name="Mini evaluation smoke test", status="pass" if smoke_ok else "fail",
                message="Actual ValidationTool accepted in-range scores and verbatim evidence." if smoke_ok else "ValidationTool found missing, out-of-range, or unverifiable evidence.",
                details={"warnings": smoke_warnings}))
            used_input = (result.input_tokens or 0) + (smoke.input_tokens or 0)
            used_output = (result.output_tokens or 0) + (smoke.output_tokens or 0)
            cost = estimate_cost(config.model, used_input, used_output)
            stages.append(StageResult(name="Usage and cost probe", status="pass",
                message=f"Observed {used_input} input / {used_output} output tokens; estimated test cost {f'${cost:.6f}' if cost is not None else 'not configured'}.",
                latency_ms=(result.latency_ms or 0) + (smoke.latency_ms or 0), details={"input_tokens": used_input, "output_tokens": used_output, "estimated_cost_usd": cost}))
            status = "passed" if all(s.status in ("pass", "warn") for s in stages) else "failed"
            return ConnectionHealth(status=status, provider_id=provider_id, model=config.model, stages=stages,
                latency_ms=(time.perf_counter()-started)*1000,
                capabilities={"json_mode": "json_object" if provider_id not in {"anthropic", "cohere"} else "prompt_only", "model_count": len(models)},
                key_fingerprint=key_fingerprint(config.api_key.get_secret_value()) if config.api_key else None)
        except Exception as exc:
            category = classify_exception(exc)
            stages.append(StageResult(name="Provider request", status="fail", message=FRIENDLY_MESSAGES[category],
                details={"category": category.value, "detail": redact(str(exc))[:500]}))
            return ConnectionHealth(status="failed", provider_id=provider_id, model=config.model, stages=stages,
                                    latency_ms=(time.perf_counter()-started)*1000)
