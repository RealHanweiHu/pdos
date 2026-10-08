"""Source snapshot frontend with isolated build output and no local dotenv."""
import hashlib
import json
import shutil
from pathlib import Path

preview = Path(__file__).resolve().parent
repository = preview.parents[4]
frontend = preview / "frontend"
frontend.mkdir(exist_ok=True)
web = repository / "web"
source_web = Path("/private/tmp/pdos-role-scenario-ui-20261001-_npy8ks1/web")
if not (source_web / "src").is_dir():
    raise SystemExit("The root's verified frozen source snapshot is missing; no source fallback.")
source_copy = frontend / "src"
if source_copy.is_symlink():
    source_copy.unlink()
if not source_copy.exists():
    shutil.copytree(source_web / "src", source_copy, ignore=shutil.ignore_patterns(".env*"))
manifest = [{"path": str(path.relative_to(source_web)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted((source_web / "src").rglob("*")) if path.is_file() and not path.name.startswith(".env")]
(preview / "source-snapshot.json").write_text(json.dumps({"source_web": str(source_web), "files": manifest}, ensure_ascii=False, indent=2)+"\n")
for name in ("public", "node_modules"):
    source = web / name
    target = frontend / name
    if source.exists() and not target.exists():
        target.symlink_to(source, target_is_directory=True)
for name in ("package.json", "next.config.ts", "postcss.config.mjs"):
    source = web / name
    if source.exists():
        shutil.copy2(source, frontend / name)
config = json.loads((web / "tsconfig.json").read_text())
config["include"] = ["next-env.d.ts", "src/**/*.ts", "src/**/*.tsx", "src/**/*.mts", ".next/types/**/*.ts", ".next/dev/types/**/*.ts"]
(frontend / "tsconfig.json").write_text(json.dumps(config, indent=2)+"\n")
print(frontend)
