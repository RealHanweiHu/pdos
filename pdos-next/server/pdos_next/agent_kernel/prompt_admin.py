"""Local code review workflow for prompt drafts, activation and rollback."""

import difflib
import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .prompts import PromptCatalog, validate_version


def _load(directory):
    return json.loads((Path(directory) / "registry.json").read_text())


@contextmanager
def _locked(directory):
    with (Path(directory) / ".registry.lock").open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _write(directory, data):
    directory = Path(directory)
    active = PromptCatalog(directory, data=data).active
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".registry-", suffix=".json", dir=directory)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "registry.json")
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return active


def _entry(data, version):
    return next((item for item in data["versions"] if item["version"] == version), None)


def create_draft(directory, version, *, source):
    validate_version(version)
    directory = Path(directory)
    with _locked(directory):
        data = _load(directory)
        if _entry(data, version) is not None:
            raise ValueError("Prompt version already exists")
        original = PromptCatalog(directory).version(source)
        path = (directory / "versions" / f"{version}.md").resolve()
        if not path.is_relative_to((directory / "versions").resolve()):
            raise ValueError("Draft path must stay inside the package")
        path.parent.mkdir(parents=True, exist_ok=True)
        data["versions"].append({
            "version": version,
            "file": f"versions/{version}.md",
            "digest": original.digest,
            "status": "draft",
            "created_at": datetime.now(UTC).date().isoformat(),
        })
        created = False
        try:
            with path.open("x") as stream:
                created = True
                stream.write(original.content)
            candidate = PromptCatalog(directory, data=data).version(version)
            _write(directory, data)
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
        return candidate


def register_draft(directory, version):
    directory = Path(directory)
    with _locked(directory):
        data = _load(directory)
        entry = _entry(data, version)
        if entry is None or entry["status"] != "draft":
            raise ValueError("Only an editable draft can be registered")
        content = (directory / entry["file"]).read_text()
        if not content.strip():
            raise ValueError("A prompt cannot be empty")
        entry["digest"] = hashlib.sha256(content.encode()).hexdigest()
        candidate = PromptCatalog(directory, data=data).version(version)
        _write(directory, data)
        return candidate


def diff(directory, baseline, candidate):
    catalog = PromptCatalog(directory)
    before, after = catalog.version(baseline), catalog.version(candidate)
    return "".join(difflib.unified_diff(
        before.content.splitlines(keepends=True),
        after.content.splitlines(keepends=True),
        fromfile=f"{before.key}@{before.version}",
        tofile=f"{after.key}@{after.version}",
    ))


def assert_evaluation_current(report, source_root=None, *, current_hashes=None):
    hashes = report.get("inputs", {}).get("source_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Evaluation has no source fingerprint")
    if current_hashes is not None:
        if current_hashes != hashes:
            raise ValueError("Evaluation source fingerprint is stale")
        return
    if source_root is None:
        raise ValueError("A source root or complete current manifest is required")
    source_root = Path(source_root).resolve()
    for relative, expected in hashes.items():
        path = (source_root / relative).resolve()
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or not path.is_relative_to(source_root)
            or not path.is_file()
            or not isinstance(expected, str)
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Evaluation source fingerprint is stale")


def activate(
    directory, version, *, expected_active, evaluation, reviewer, current_sources,
):
    if not reviewer or not reviewer.strip():
        raise ValueError("A named code reviewer is required")
    directory = Path(directory)
    with _locked(directory):
        data = _load(directory)
        if data["active"] != expected_active:
            raise ValueError("Active prompt changed; reread before activation")
        catalog = PromptCatalog(directory)
        current = catalog.active
        candidate_entry = _entry(data, version)
        if candidate_entry is None or candidate_entry["status"] not in {"draft", "published"}:
            raise ValueError("Only a draft or previously published prompt can be activated")
        candidate = catalog.version(version)
        from .skills import SkillCatalog

        index = SkillCatalog().index
        _, current_identity = current.compose(index)
        _, candidate_identity = candidate.compose(index)
        baseline = evaluation.get("baseline", {})
        if (
            evaluation.get("schema") != "xiaopai-prompt-ab/v1"
            or evaluation.get("control_status") != "passed"
            or baseline.get("key") != current.key
            or baseline.get("version") != current.version
            or baseline.get("content_digest") != current.digest
            or baseline.get("system_digest") != current_identity["system_digest"]
            or evaluation.get("candidate", {}).get("version") != version
            or evaluation.get("candidate", {}).get("content_digest") != candidate.digest
            or evaluation.get("candidate", {}).get("system_digest")
            != candidate_identity["system_digest"]
        ):
            raise ValueError("Activation requires a passing evaluation of this exact prompt")
        assert_evaluation_current(
            evaluation,
            current_hashes=current_sources() if callable(current_sources) else current_sources,
        )
        previous = data["active"]
        _entry(data, previous)["status"] = "published"
        candidate_entry["status"] = "active"
        data["active"] = version
        data["history"].append({
            "kind": "activate",
            "version": version,
            "previous": previous,
            "at": datetime.now(UTC).isoformat(),
            "reviewer": reviewer.strip(),
            "quality_status": evaluation.get("quality_status", "not_scored"),
            "evaluation_digest": hashlib.sha256(json.dumps(
                evaluation, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest(),
        })
        return _write(directory, data)


def rollback(directory, version, *, expected_active, reviewer, reason):
    if not reviewer or not reviewer.strip() or not reason or not reason.strip():
        raise ValueError("Rollback requires a named reviewer and reason")
    directory = Path(directory)
    with _locked(directory):
        data = _load(directory)
        if data["active"] != expected_active:
            raise ValueError("Active prompt changed; reread before rollback")
        catalog = PromptCatalog(directory)
        current = catalog.active
        if current.version != expected_active:
            raise ValueError("Active prompt changed; reread before rollback")
        target_entry = _entry(data, version)
        historical = any(
            version in {item.get("version"), item.get("previous")}
            for item in data["history"]
            if isinstance(item, dict)
        )
        if target_entry is None or target_entry["status"] != "published" or not historical:
            raise ValueError("Rollback target must be a previously active published prompt")
        catalog.version(version)
        previous = data["active"]
        _entry(data, previous)["status"] = "published"
        target_entry["status"] = "active"
        data["active"] = version
        data["history"].append({
            "kind": "rollback",
            "version": version,
            "previous": previous,
            "at": datetime.now(UTC).isoformat(),
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
        })
        return _write(directory, data)
