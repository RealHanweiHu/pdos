"""Start one arm's probes directly (diagnostic; mirrors tools/xiaopai_prompt_ab.py run)."""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2]); arm = json.loads(sys.argv[3])
repeat = sys.argv[4]; probes = sys.argv[5].split(","); dump = sys.argv[6]
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "server"))
import local_environment as local
env = local.environment(local.verified(local.read_state()))
procs = []
for probe in probes:
    (OUT / arm["name"]).mkdir(exist_ok=True)
    log = (OUT / "logs" / f"{arm['name']}-r{repeat}-{probe}.log").open("a")
    procs.append((probe, subprocess.Popen(
        [sys.executable, "-m", "pytest", "tests/agent/kernel/test_eval_prompt_ab_real_pg.py",
         "-q", "-s", "-p", "no:cacheprovider"],
        cwd=ROOT / "server", stdout=log, stderr=subprocess.STDOUT,
        env={**env, "PYTHONUNBUFFERED": "1",
             "PDOS_PROMPT_AB_REAL": str(Path(os.environ["MODEL_RUNTIME"]).resolve()),
             "PDOS_PROMPT_AB_OUTPUT_DIR": str(OUT / arm["name"]),
             "PDOS_PROMPT_AB_ARM": json.dumps(arm, ensure_ascii=False),
             "PDOS_PROMPT_AB_REPEAT": repeat,
             "PDOS_PROMPT_AB_CASES": str(OUT / "cases.json"),
             "PDOS_PROMPT_AB_ONLY": probe,
             **({"PDOS_DEBUG_PROVIDER_DUMP": dump} if dump else {})})))
for probe, proc in procs:
    print(json.dumps({"probe": probe, "exit": proc.wait()}), flush=True)
