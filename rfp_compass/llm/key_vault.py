"""Redacting secret wrappers and helpers; keys belong in session state only."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from collections.abc import MutableMapping
from collections.abc import Iterable
from pydantic import SecretStr

_KNOWN_SECRETS: set[str] = set()
_PATTERNS = [re.compile(r"(?i)(sk-[A-Za-z0-9_-]{8,})"), re.compile(r"(?i)(AIza[A-Za-z0-9_-]{20,})")]


class RedactedSecret(SecretStr):
    """SecretStr-compatible value whose common representations are redacted."""
    def __repr__(self) -> str:
        return "RedactedSecret('**********')"

    def __str__(self) -> str:
        return "**********"


def register_secret(value: str | None) -> RedactedSecret | None:
    """Wrap a key and add it to the process-local log redaction set."""
    if not value:
        return None
    _KNOWN_SECRETS.add(value)
    return RedactedSecret(value)


def forget_secret(value: str | None) -> None:
    """Remove a previously registered value when clearing a session key."""
    if value:
        _KNOWN_SECRETS.discard(value)


class SessionKeyVault:
    """Store provider keys only in a caller-owned session mapping.

    Streamlit creates an independent session-state mapping per browser session;
    this helper deliberately has no process-global credential storage.
    """
    def __init__(self, state: MutableMapping[str, object], namespace: str = "rfp_compass.keys"):
        self.state = state
        self.namespace = namespace

    def set(self, provider_id: str, value: str) -> RedactedSecret:
        secret = register_secret(value)
        assert secret is not None
        self.state[f"{self.namespace}.{provider_id}"] = secret
        return secret

    def get(self, provider_id: str) -> RedactedSecret | None:
        value = self.state.get(f"{self.namespace}.{provider_id}")
        return value if isinstance(value, RedactedSecret) else None

    def clear(self, provider_id: str) -> None:
        value = self.get(provider_id)
        if value:
            forget_secret(value.get_secret_value())
        self.state.pop(f"{self.namespace}.{provider_id}", None)

    def clear_all(self) -> None:
        prefix = f"{self.namespace}."
        for key in list(self.state):
            if key.startswith(prefix):
                value = self.state.pop(key)
                if isinstance(value, RedactedSecret):
                    forget_secret(value.get_secret_value())


def redact(value: object) -> str:
    """Redact registered secrets and common provider key shapes from text."""
    result = str(value)
    for secret in sorted(_KNOWN_SECRETS, key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    for pattern in _PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts message and arguments before emission."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            record.msg, record.args = "[REDACTED LOG MESSAGE]", ()
        return True


def key_fingerprint(key: str, salt: bytes | None = None) -> str:
    """Return salted short identifier (fingerprint plus last four characters)."""
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.sha256(actual_salt + key.encode("utf-8")).hexdigest()[:8]
    return f"{digest}:{key[-4:]}"


def install_redaction_filter(logger: logging.Logger | None = None) -> None:
    """Install the redaction filter on the root logger and its current handlers."""
    target = logger or logging.getLogger()
    if not any(isinstance(existing, SecretRedactionFilter) for existing in target.filters):
        target.addFilter(SecretRedactionFilter())
    for handler in target.handlers:
        if not any(isinstance(existing, SecretRedactionFilter) for existing in handler.filters):
            handler.addFilter(SecretRedactionFilter())
