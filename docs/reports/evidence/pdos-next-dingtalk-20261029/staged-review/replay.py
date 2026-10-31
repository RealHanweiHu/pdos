"""Strict manifest-only replay. Defaults to verification, never modifies live implicitly."""

import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    stage = Path(__file__).resolve().parent
    manifest = json.loads((stage / "integration-manifest.json").read_text())
    target = args.target.resolve(strict=True)
    for item in manifest["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Invalid manifest path: {relative}")
        source, destination = stage / relative, target / relative
        if sha(source) != item["staged_sha256"]:
            raise RuntimeError(f"Staged file changed: {relative}")
        if sha(destination) != item["base_sha256"]:
            raise RuntimeError(f"Target base differs: {relative}")
    if args.apply:
        for item in manifest["files"]:
            relative = Path(item["path"])
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((stage / relative).read_bytes())
        for item in manifest["files"]:
            assert sha(target / item["path"]) == item["staged_sha256"]
    print(json.dumps({"checked": len(manifest["files"]), "applied": args.apply}))


if __name__ == "__main__":
    main()
