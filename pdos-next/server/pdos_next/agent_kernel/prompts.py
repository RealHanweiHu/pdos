"""Versioned prompt code; dynamic state never enters the fixed system prefix."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")
_STATUSES = {"draft", "active", "published"}


def validate_version(version):
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ValueError("Invalid prompt version")


@dataclass(frozen=True)
class Prompt:
    key: str
    version: str
    content: str
    digest: str
    status: str

    def compose(self, skill_directory):
        text = (
            self.content
            + "\nSkill directory:\n"
            + json.dumps(skill_directory, ensure_ascii=False)
        )
        from pdos_next.service import digest

        return text, {
            "key": self.key,
            "version": self.version,
            "content_digest": self.digest,
            "system_digest": digest(text),
        }


class PromptCatalog:
    def __init__(self, directory=None, *, data=None):
        self.directory = Path(directory) if directory is not None else (
            Path(__file__).resolve().parents[1] / "prompt_packages"
        )
        if data is None:
            data = json.loads((self.directory / "registry.json").read_text())
        if (
            data.get("schema") != "xiaopai-prompt-registry/v1"
            or not isinstance(data.get("key"), str)
            or not data["key"]
            or not isinstance(data.get("versions"), list)
            or not isinstance(data.get("active"), str)
            or not isinstance(data.get("history"), list)
        ):
            raise ValueError("Invalid prompt registry")
        self.key, self.active_version, self.history = data["key"], data["active"], data["history"]
        self._entries = {}
        for entry in data["versions"]:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"version", "file", "digest", "status", "created_at"}
                or not isinstance(entry["version"], str)
                or entry["version"] in self._entries
                or not isinstance(entry["file"], str)
                or not isinstance(entry["digest"], str)
                or re.fullmatch(r"[a-f0-9]{64}", entry["digest"]) is None
                or entry["status"] not in _STATUSES
                or not isinstance(entry["created_at"], str)
                or not entry["created_at"]
            ):
                raise ValueError("Invalid prompt version entry")
            path = Path(entry["file"])
            validate_version(entry["version"])
            if path.is_absolute() or ".." in path.parts or path.suffix != ".md":
                raise ValueError("Prompt path must stay inside the package")
            self._entries[entry["version"]] = entry
        active = self._entries.get(self.active_version)
        if active is None or active["status"] != "active":
            raise ValueError("The active prompt must identify an active version")
        if sum(entry["status"] == "active" for entry in self._entries.values()) != 1:
            raise ValueError("Exactly one prompt version must be active")

    @property
    def active(self):
        return self.version(self.active_version)

    def version(self, version):
        entry = self._entries.get(version)
        if entry is None:
            raise ValueError(f"Unknown prompt version: {version}")
        path = (self.directory / entry["file"]).resolve()
        if not path.is_relative_to(self.directory.resolve()) or not path.is_file():
            raise ValueError("Prompt file is unavailable")
        content = path.read_text()
        from pdos_next.service import digest

        actual = digest(content)
        if not content.strip() or actual != entry["digest"]:
            raise ValueError(f"Prompt content is not registered: {version}")
        return Prompt(self.key, version, content, actual, entry["status"])

    def versions(self):
        return [dict(self._entries[key]) for key in sorted(self._entries)]
