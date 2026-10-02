"""Actual pytest fixture teardown restores only its owned gateway override; no database."""

from pathlib import Path

import pytest

pytest_plugins = ("pytester",)


def test_gateway_overrides_follow_actual_owner_scope_even_on_failures(
    pytester: pytest.Pytester,
) -> None:
    pytester.syspathinsert(Path(__file__).resolve().parents[1])
    pytester.makepyfile(
        test_gateway_scope="""
        import pytest

        from app.api.ai import get_application_gateway
        from app.main import app
        from app.storage.documents import get_document_object_store
        from tests.test_application_run_budget_api import install_gateway

        MISSING = object()


        def prior_gateway():
            return "preexisting gateway"


        def document_store():
            return "unrelated legitimate override"


        @pytest.fixture
        def baseline(request):
            old_gateway = app.dependency_overrides.get(get_application_gateway, MISSING)
            old_store = app.dependency_overrides.get(get_document_object_store, MISSING)
            before = (
                MISSING if request.param in {"absent", "body_failure"} else prior_gateway
            )
            if before is MISSING:
                app.dependency_overrides.pop(get_application_gateway, None)
            else:
                app.dependency_overrides[get_application_gateway] = before
            app.dependency_overrides[get_document_object_store] = document_store
            patch = pytest.MonkeyPatch()
            state = {"case": request.param, "expected": before, "patch": patch}
            try:
                yield state
            finally:
                # The owner depends on this fixture, so its finalizers run before undo.
                patch.undo()
                try:
                    # The dependent owner fixture has already been finalized.
                    assert (
                        app.dependency_overrides.get(get_application_gateway, MISSING)
                        is state["expected"]
                    )
                    assert app.dependency_overrides[get_document_object_store] is document_store
                    if state["case"] == "mapping_replacement":
                        assert app.dependency_overrides is state["owned_map"]
                        assert (
                            state["replacement_map"][get_application_gateway]
                            is state["replacement"]
                        )
                        assert (
                            state["replacement_map"][get_document_object_store]
                            is document_store
                        )
                finally:
                    for key, value in (
                        (get_application_gateway, old_gateway),
                        (get_document_object_store, old_store),
                    ):
                        if value is MISSING:
                            app.dependency_overrides.pop(key, None)
                        else:
                            app.dependency_overrides[key] = value


        @pytest.fixture
        def installed(request, baseline):
            first = lambda: "first installed gateway"
            install_gateway(request, first)
            assert app.dependency_overrides[get_application_gateway] is first
            if baseline["case"] == "multiple":
                second = lambda: "second installed gateway"
                install_gateway(request, second)
                assert app.dependency_overrides[get_application_gateway] is second
            if baseline["case"] == "mapping_replacement":
                owned_map = app.dependency_overrides
                replacement = lambda: "gateway in a newer dictionary"
                replacement_map = {**owned_map, get_application_gateway: replacement}
                baseline["patch"].setattr(app, "dependency_overrides", replacement_map)
                baseline.update(
                    owned_map=owned_map,
                    replacement_map=replacement_map,
                    replacement=replacement,
                )
            if baseline["case"] == "setup_failure":
                raise RuntimeError("intentional fixture setup failure")
            return baseline


        @pytest.mark.parametrize(
            "baseline",
            [
                "absent", "present", "multiple", "replacement", "removed",
                "mapping_replacement",
                "body_failure", "setup_failure",
            ],
            indirect=True,
        )
        def test_owner(installed):
            if installed["case"] == "replacement":
                replacement = lambda: "newer legitimate gateway"
                app.dependency_overrides[get_application_gateway] = replacement
                installed["expected"] = replacement
            elif installed["case"] == "removed":
                app.dependency_overrides.pop(get_application_gateway)
                installed["expected"] = MISSING
            elif installed["case"] == "body_failure":
                raise RuntimeError("intentional test body failure")
        """
    )
    result = pytester.runpytest_inprocess("-q", "--tb=short", "-p", "no:cacheprovider")
    # Expected inner failures prove finalization after both setup and call exceptions.
    # A restoration failure produces an additional teardown error and fails this check.
    result.assert_outcomes(passed=6, failed=1, errors=1)
