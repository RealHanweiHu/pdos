from __future__ import annotations

import os

import pytest

from app.ai.runtime_factory import RuntimeConfigurationError, required_database_url


def test_process_database_configuration_fails_closed_on_missing_or_shared_app_url() -> None:
    with pytest.raises(RuntimeConfigurationError, match="PDOS_AGENT_DATABASE_URL must be set"):
        required_database_url({}, key="PDOS_AGENT_DATABASE_URL")
    with pytest.raises(RuntimeConfigurationError, match="must not reuse DATABASE_URL"):
        required_database_url(
            {
                "DATABASE_URL": "postgresql://pdos_app:secret@db/pdos",
                "PDOS_AGENT_DATABASE_URL": "postgresql://pdos_app:secret@db/pdos",
            },
            key="PDOS_AGENT_DATABASE_URL",
        )
    with pytest.raises(RuntimeConfigurationError, match="must use the pdos_agent database role"):
        required_database_url(
            {"PDOS_AGENT_DATABASE_URL": "postgresql://pdos_app:secret@db/pdos"},
            key="PDOS_AGENT_DATABASE_URL",
        )
    with pytest.raises(RuntimeConfigurationError, match="must use the pdos_worker database role"):
        required_database_url(
            {"PDOS_WORKER_DATABASE_URL": "postgresql://pdos_agent:secret@db/pdos"},
            key="PDOS_WORKER_DATABASE_URL",
        )
    assert (
        required_database_url(
            {
                "DATABASE_URL": "postgresql://pdos:pdos@db/pdos_test",
                "PDOS_AGENT_DATABASE_URL": "postgresql://pdos:pdos@db/pdos_test",
                "PDOS_ALLOW_SHARED_RUNTIME_DATABASE_URL": "true",
            },
            key="PDOS_AGENT_DATABASE_URL",
        )
        == "postgresql://pdos:pdos@db/pdos_test"
    )


def test_dispatcher_entrypoint_import_does_not_require_model_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(os.environ):
        if name.startswith(("PDOS_LLM_", "ANTHROPIC_API_KEY")):
            monkeypatch.delenv(name, raising=False)

    from scripts import run_dispatcher

    assert callable(run_dispatcher.main)
