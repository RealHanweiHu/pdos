import pytest

from pdos_next.workflows.checkpoints import verified_checkpoint_url


@pytest.mark.parametrize(
    "target",
    [
        "postgresql+psycopg://pdos_checkpoint:synthetic@127.0.0.1:57432/pdos_checkpoints",
        "postgresql+psycopg://pdos_checkpoint:synthetic@localhost:65109/pdos_checkpoints",
        "postgresql+psycopg://pdos_checkpoint:synthetic@127.0.0.1:65109/pdos_test",
        "postgresql+psycopg://pdos_next_app:synthetic@127.0.0.1:65109/pdos_checkpoints",
        "postgresql+psycopg://pdos_checkpoint:synthetic@127.0.0.1:65109/pdos_checkpoints?host=elsewhere",
    ],
)
def test_checkpoint_guard_rejects_nonselected_target_before_connect(monkeypatch, target):
    monkeypatch.setenv("PDOS_STATE_DB_PORT", "65109")
    monkeypatch.setenv("PDOS_STATE_DB_MARKER", "synthetic-marker-only")

    def forbidden(_url):
        raise AssertionError("A rejected checkpoint target must never connect")

    monkeypatch.setattr("pdos_next.workflows.checkpoints.engine_for", forbidden)
    with pytest.raises(RuntimeError, match="explicitly selected independent target"):
        verified_checkpoint_url(target)


def test_checkpoint_guard_rejects_marker_mismatch_and_disposes_fake_engine(monkeypatch):
    monkeypatch.setenv("PDOS_STATE_DB_PORT", "65109")
    monkeypatch.setenv("PDOS_STATE_DB_MARKER", "expected-synthetic-marker")

    class FakeEngine:
        disposed = False

        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            return self

        def scalar_one(self):
            return "wrong-synthetic-marker"

        def dispose(self):
            self.disposed = True

    fake = FakeEngine()
    monkeypatch.setattr("pdos_next.workflows.checkpoints.engine_for", lambda _url: fake)
    with pytest.raises(RuntimeError, match="marker mismatch"):
        verified_checkpoint_url(
            "postgresql+psycopg://pdos_checkpoint:synthetic@127.0.0.1:65109/pdos_checkpoints"
        )
    assert fake.disposed
