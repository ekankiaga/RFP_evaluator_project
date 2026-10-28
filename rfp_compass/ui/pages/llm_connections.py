"""Bring-your-own-key connection management and diagnostics."""

from __future__ import annotations

import os
import uuid

import streamlit as st
from pydantic import SecretStr

from ...audit.audit_log import AuditLog
from ...llm.connection_tester import ConnectionTester
from ...llm.key_vault import forget_secret, redact, register_secret
from ...llm.registry import PROVIDERS, get_provider
from ...models import ConnectionConfig, ProviderKind


ENV_KEYS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "cohere": "COHERE_API_KEY", "litellm": "LITELLM_API_KEY"}


def render() -> None:
    viewer = st.session_state.get("role") == "Viewer"
    st.title("Provider connections")
    st.caption("Optional · Demo mode works without a provider. Add a connection only when you want evaluations to use a live model.")
    st.info("To use a live model: choose the provider or compatible endpoint, enter its API key and exact model/deployment ID, save the connection, test it, then assign it for evaluation. Saving keeps your current mode; assigning a tested connection switches evaluation out of Offline demo mode.")
    saved = st.session_state.setdefault("saved_connections", {})
    provider_ids = list(PROVIDERS)
    provider_id = st.selectbox("1 · Choose provider", provider_ids,
        format_func=lambda x: f"{PROVIDERS[x].icon}  {PROVIDERS[x].display_name}",
        help="Select the service that issued your API key. For self-hosted OpenAI-compatible APIs, choose Custom OpenAI-compatible.")
    spec = get_provider(provider_id)
    if provider_id == "openai":
        st.info("Use an API key from the OpenAI developer platform. A ChatGPT login or Plus subscription is not an API key; API usage is billed separately. The connection test sends two short requests.")
        st.markdown("[Create or manage an API key](https://platform.openai.com/api-keys)")
    elif provider_id == "litellm":
        st.info("Use LiteLLM Universal for a broad catalog of hosted, cloud, gateway, and local providers. Enter the exact provider/model route (for example, `bedrock/…`, `vertex_ai/…`, `fireworks_ai/…`, or `github/…`). Provider credentials can be entered below or supplied through that provider's environment variables.")
        st.markdown("[Browse LiteLLM provider routes](https://docs.litellm.ai/docs/providers)")
        st.caption("Install the optional adapter once with `python -m pip install -r requirements-litellm.txt`, then restart Streamlit. Compatible services can also use **Custom OpenAI-compatible** without LiteLLM.")
    with st.form("connection_form"):
        show_key = spec.needs_api_key or provider_id == "litellm"
        key_help = "Optional for LiteLLM if provider credentials are configured in the environment. Otherwise enter the provider key here; it stays in this browser session only." if provider_id == "litellm" else spec.key_format_hint or "The key stays in this browser session and is never stored in SQLite."
        key = st.text_input("API key", type="password", help=key_help, disabled=viewer) if show_key else ""
        if provider_id == "mock":
            model = "mock-rfp-v1"
            st.caption("Demo mode uses its built-in mock model and needs no model ID.")
        else:
            model_placeholder = "provider/model, e.g. bedrock/… or vertex_ai/…" if provider_id == "litellm" else "Type the exact identifier your provider or endpoint expects"
            model_help = "Enter the LiteLLM route as provider/model. Use the provider catalog for exact route prefixes and authentication requirements." if provider_id == "litellm" else "Free text: enter any model ID supported by the selected provider. For Azure, enter the deployment name."
            model = st.text_input("2 · Model ID or deployment name", value="",
                placeholder=model_placeholder, help=model_help, disabled=viewer)
        with st.expander("Advanced connection settings"):
            default_url = spec.default_base_url or ""
            base_url = st.text_input("Base URL", value=default_url, help="Custom endpoints require HTTPS, except localhost. Local endpoints need the allow-local-network switch.", disabled=viewer)
            allow_local = st.checkbox("Allow local/private network endpoints", value=provider_id in {"ollama", "lm_studio", "vllm"}, disabled=viewer)
            azure_endpoint = st.text_input("Azure endpoint", disabled=viewer) if provider_id == "azure_openai" else None
            azure_deployment = model.strip() if provider_id == "azure_openai" else None
            azure_api_version = st.text_input("Azure API version", value="2024-10-21", disabled=viewer) if provider_id == "azure_openai" else None
            timeout = st.slider("Timeout (seconds)", 10, 180, 60, disabled=viewer)
            max_tokens = st.number_input("Max output tokens", min_value=256, max_value=32000, value=3000, step=256, disabled=viewer)
            retries = st.number_input("Retries", min_value=0, max_value=6, value=2, disabled=viewer)
            st.caption("Temperature is locked at 0 for repeatable evaluations.")
        saved_button = st.form_submit_button("3 · Save connection for this session", type="primary", disabled=viewer,
            on_click=_set_demo_mode, args=(provider_id,))
    st.caption("API keys are session-only. They are cleared when you clear connections or end this browser session.")
    if saved_button:
        secret = key or _fallback_secret(provider_id)
        if provider_id != "mock" and not model.strip():
            st.error("Enter the exact model ID or deployment name supplied by your provider.")
        elif spec.needs_api_key and not secret:
            st.error("Enter an API key or configure a fallback in Streamlit secrets/environment variables.")
        else:
            wrapped = register_secret(secret)
            config = ConnectionConfig(connection_id=str(uuid.uuid4()), provider_id=ProviderKind(provider_id), model=model,
                api_key=wrapped, base_url=base_url or None, azure_endpoint=azure_endpoint or None,
                azure_deployment=azure_deployment or None, azure_api_version=azure_api_version or None,
                timeout_seconds=timeout, max_output_tokens=int(max_tokens), retries=int(retries), allow_local_network=allow_local)
            saved[config.connection_id] = config
            st.session_state["connection_health"] = st.session_state.setdefault("connection_health", {})
            st.session_state["active_connection_id"] = config.connection_id
            if st.session_state["demo_mode"]:
                st.session_state["evaluation_connection"] = config
            AuditLog().append(actor="analyst", role=st.session_state.get("role", "Analyst"), event_type="llm_connection_created",
                entity_type="llm_connection", entity_id=config.connection_id,
                after={"provider": provider_id, "model": model, "base_url_host": _host(config.base_url or config.azure_endpoint)})
            st.success("Connection saved for this session. The key is masked and is not persisted.")

    if saved:
        st.subheader("Saved connections · this session")
        ids = list(saved)
        selected_id = st.selectbox("Connection", ids,
            format_func=lambda x: f"{saved[x].provider_id.value} · {saved[x].model}", key="connection_pick")
        config = saved[selected_id]
        col1, col2 = st.columns([1, 1])
        if col1.button("4 · Test connection", type="primary", key="test_connection", disabled=viewer):
            with st.status("Running connection diagnostics…", expanded=True) as status:
                health = ConnectionTester().test(config)
                st.session_state.setdefault("connection_health", {})[selected_id] = health
                for stage in health.stages:
                    icon = "✅" if stage.status == "pass" else "⚠️" if stage.status == "warn" else "❌"
                    st.write(f"{icon} **{stage.name}** · {stage.message}" + (f" · {stage.latency_ms:.0f} ms" if stage.latency_ms is not None else ""))
                    detail = (stage.details or {}).get("detail")
                    if detail:
                        st.caption(f"Provider detail: {detail}")
                status.update(label="Connection test passed" if health.status == "passed" else "Connection test failed", state="complete" if health.status == "passed" else "error")
            AuditLog().append(actor="analyst", role=st.session_state.get("role", "Analyst"), event_type="llm_connection_tested",
                entity_type="llm_connection", entity_id=selected_id,
                after={"provider": config.provider_id.value, "model": config.model,
                       "base_url_host": _host(config.base_url or config.azure_endpoint), "status": health.status,
                       "stages": [{"name": x.name, "status": x.status, "latency_ms": x.latency_ms} for x in health.stages],
                       "key_fingerprint": health.key_fingerprint})
        health = st.session_state.get("connection_health", {}).get(selected_id)
        if health:
            st.info(f"Health: **{health.status}** · tested {health.tested_at.isoformat()} · fingerprint `{health.key_fingerprint or 'no-key'}`")
            if health.status == "failed":
                st.caption("Use the failed stage above to diagnose the connection. The fingerprint reflects the saved key when one was attached; `no-key` means the saved connection had no key.")
        if config.provider_id.value in {"ollama", "lm_studio", "vllm"}:
            st.caption("Local endpoints work only when this app is running on the same machine as the model server. They are not reachable from Streamlit Community Cloud.")
        col2.button("5 · Use for evaluation", key="assign_evaluation", disabled=viewer,
                    on_click=_assign_evaluation_connection, args=(selected_id,))
        assignment_notice = st.session_state.pop("connection_assignment_notice", None)
        if assignment_notice:
            kind, message = assignment_notice
            getattr(st, kind)(message)
        with st.expander("Optional · assign this connection to other tasks"):
            st.caption("Evaluation uses the primary model above. These assignments are for optional template parsing, insights, or fallback calls.")
            roles = st.columns(3)
            for column, role in zip(roles, ("Light tasks", "Narrative/insights", "Fallback")):
                if column.button(f"Assign {role}", key=f"assign_{role}", disabled=viewer):
                    st.session_state[f"{role.casefold().replace('/', '_').replace(' ', '_')}_connection_id"] = selected_id
                    st.success(f"Assigned {role} connection for this session.")
        if st.button("Clear selected connection", key="clear_connection", disabled=viewer):
            secret = config.api_key.get_secret_value() if config.api_key else None
            forget_secret(secret)
            del saved[selected_id]
            st.session_state.get("connection_health", {}).pop(selected_id, None)
            if st.session_state.get("evaluation_connection") is config:
                st.session_state.pop("evaluation_connection", None)
            AuditLog().append(actor="analyst", role=st.session_state.get("role", "Analyst"), event_type="llm_connection_cleared",
                entity_type="llm_connection", entity_id=selected_id, reason="User cleared connection")
            st.rerun()
        st.button("Clear all connections", key="clear_all_connections", disabled=viewer,
                  on_click=_clear_all_connections)
        clear_notice = st.session_state.pop("connections_cleared_notice", False)
        if clear_notice:
            st.success("All session connections cleared. Offline demo mode is on.")
    st.markdown("### Data privacy")
    st.warning("Evaluation sends supplier proposal text to the selected third-party provider. Review the provider’s data handling terms and avoid uploading unnecessary personal or confidential data. Local models keep inference on the configured endpoint.")
    st.caption("Keys are session-only, are not written to the database, logs, exports, or reproducibility bundle, and are cleared when you clear connections or end the browser session.")


def _fallback_secret(provider_id: str) -> str | None:
    env_name = ENV_KEYS.get(provider_id)
    if env_name:
        try:
            value = st.secrets.get(env_name)
            if value:
                return str(value)
        except Exception:
            pass
        return os.getenv(env_name)
    return None


def _host(value: str | None) -> str | None:
    from urllib.parse import urlparse
    return urlparse(value or "").hostname


def _set_demo_mode(provider_id: str) -> None:
    """Turn demo mode on when the built-in mock provider is saved."""
    if provider_id == ProviderKind.MOCK.value:
        st.session_state["demo_mode"] = True


def _assign_evaluation_connection(connection_id: str) -> None:
    saved = st.session_state.get("saved_connections", {})
    config = saved.get(connection_id)
    health = st.session_state.get("connection_health", {}).get(connection_id)
    if config is None or health is None or health.status != "passed":
        st.session_state["connection_assignment_notice"] = (
            "warning", "Test this connection successfully before assigning it as the evaluation model.")
        return
    st.session_state["evaluation_connection"] = config
    st.session_state["active_connection_id"] = connection_id
    st.session_state["demo_mode"] = config.provider_id == ProviderKind.MOCK
    st.session_state["connection_assignment_notice"] = ("success", "Evaluation connection selected.")


def _clear_all_connections() -> None:
    saved = st.session_state.setdefault("saved_connections", {})
    for item in saved.values():
        forget_secret(item.api_key.get_secret_value() if item.api_key else None)
    saved.clear()
    st.session_state.pop("evaluation_connection", None)
    st.session_state["connection_health"] = {}
    st.session_state["demo_mode"] = True
    AuditLog().append(actor="analyst", role=st.session_state.get("role", "Analyst"), event_type="llm_connection_cleared",
        entity_type="llm_connection", entity_id="all", reason="User cleared all connections")
    st.session_state["connections_cleared_notice"] = True
