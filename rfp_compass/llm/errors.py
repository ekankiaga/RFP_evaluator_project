"""Provider error taxonomy and user-safe connection explanations."""

from __future__ import annotations

from enum import StrEnum


class ErrorCategory(StrEnum):
    INVALID_KEY = "invalid_key"
    WRONG_URL = "wrong_base_url"
    MODEL_NOT_FOUND = "model_not_found"
    QUOTA = "quota_or_billing"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK = "network_blocked_or_dns"
    SSL = "ssl_error"
    PROVIDER_OUTAGE = "provider_outage"
    MALFORMED_JSON = "malformed_json"
    INVALID_SCORE = "out_of_range_score"
    UNKNOWN = "unknown"


FRIENDLY_MESSAGES: dict[ErrorCategory, str] = {
    ErrorCategory.INVALID_KEY: "Authentication failed. Check the key and its provider/account permissions.",
    ErrorCategory.WRONG_URL: "The endpoint was not found. Check the base URL, Azure endpoint, and API version.",
    ErrorCategory.MODEL_NOT_FOUND: "The selected model or deployment is unavailable to this account.",
    ErrorCategory.QUOTA: "The provider reports exhausted quota or missing billing. Check account usage and billing.",
    ErrorCategory.RATE_LIMITED: "The provider rate limit was reached. Wait briefly or reduce parallel requests.",
    ErrorCategory.TIMEOUT: "The provider did not respond in time. Check endpoint availability or increase timeout.",
    ErrorCategory.NETWORK: "The endpoint could not be reached. Check DNS, firewall, and network access.",
    ErrorCategory.SSL: "TLS verification failed. Use a valid HTTPS endpoint and certificate.",
    ErrorCategory.PROVIDER_OUTAGE: "The provider returned a server error. Retry after the service recovers.",
    ErrorCategory.MALFORMED_JSON: "The model response was not valid JSON. Retry with structured output enabled.",
    ErrorCategory.INVALID_SCORE: "The model returned a score outside the configured range.",
    ErrorCategory.UNKNOWN: "The connection failed. Review the redacted diagnostic and test again.",
}


def classify_http_error(status_code: int, message: str = "") -> ErrorCategory:
    """Classify common HTTP errors using status and a small message hint."""
    hint = message.casefold()
    if status_code in (401, 403):
        return ErrorCategory.INVALID_KEY
    if status_code == 404:
        return ErrorCategory.MODEL_NOT_FOUND if "model" in hint or "deployment" in hint else ErrorCategory.WRONG_URL
    if status_code == 429:
        return ErrorCategory.QUOTA if "quota" in hint or "billing" in hint else ErrorCategory.RATE_LIMITED
    if status_code >= 500:
        return ErrorCategory.PROVIDER_OUTAGE
    return ErrorCategory.UNKNOWN


def classify_exception(error: BaseException) -> ErrorCategory:
    """Classify common SDK/network exceptions without returning provider details."""
    name = type(error).__name__.casefold()
    if "timeout" in name or isinstance(error, TimeoutError):
        return ErrorCategory.TIMEOUT
    if "ssl" in name or "certificate" in name:
        return ErrorCategory.SSL
    if any(part in name for part in ("connecterror", "connectionerror", "networkerror", "gaierror", "dns")):
        return ErrorCategory.NETWORK
    if "json" in name or isinstance(error, ValueError):
        return ErrorCategory.MALFORMED_JSON
    status = getattr(error, "status_code", None)
    if status is not None:
        return classify_http_error(int(status), str(error))
    message = str(error).casefold()
    if "ssl" in message or "certificate" in message:
        return ErrorCategory.SSL
    if "name resolution" in message or "dns" in message or "network is unreachable" in message:
        return ErrorCategory.NETWORK
    return ErrorCategory.UNKNOWN
