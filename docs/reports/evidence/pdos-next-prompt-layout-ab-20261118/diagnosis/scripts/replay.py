"""Replay captured failing request bodies straight at the provider (synthetic content only)."""
import json, sys, glob, time, copy
import httpx
from pathlib import Path

# The provider address and key are read from the repository .env by the cache probe helper.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "context-cache-layout-20261116/scripts"))
from probe_run import load_env
base, key, model = load_env()

def call(body, stream):
    body = copy.deepcopy(body); body["stream"] = stream
    if stream: body.setdefault("stream_options", body.get("stream_options") or {})
    t = time.time()
    r = httpx.post(f"{base}/chat/completions", timeout=httpx.Timeout(120, connect=20),
                   headers={"Authorization": f"Bearer {key}", "Accept-Encoding": "identity"}, json=body)
    out = {"status": r.status_code, "s": round(time.time() - t, 1)}
    if r.status_code != 200:
        out["body"] = r.text[:200]; return out
    calls = {}; usage = None; fin = None; content = ""
    if stream:
        for packet in r.text.replace("\r\n", "\n").split("\n\n"):
            for line in packet.splitlines():
                if not line.startswith("data:") or line[5:].strip() == "[DONE]": continue
                c = json.loads(line[5:]); usage = c.get("usage") or usage
                for ch in c.get("choices", []):
                    d = ch.get("delta", {}); content += d.get("content") or ""
                    for tc in d.get("tool_calls") or []:
                        k = calls.setdefault(tc["index"], {"name": "", "arguments": ""})
                        k["name"] += tc.get("function", {}).get("name", "") or ""
                        k["arguments"] += tc.get("function", {}).get("arguments", "") or ""
                    fin = ch.get("finish_reason") or fin
    else:
        c = r.json(); usage = c.get("usage"); ch = c["choices"][0]; fin = ch["finish_reason"]
        content = ch["message"].get("content") or ""
        for i, tc in enumerate(ch["message"].get("tool_calls") or []):
            calls[i] = {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
    out.update(finish=fin, out_tokens=usage and usage.get("completion_tokens"), tools=[])
    for _, k in sorted(calls.items()):
        try:
            v = json.loads(k["arguments"]); ok = "ok"
            qs = v.get("questions") if isinstance(v, dict) else None
            shape = [type(q.get("options")).__name__ + (":" + ",".join(q["options"].keys()) if isinstance(q.get("options"), dict) else "")
                     for q in qs or [] if isinstance(q, dict)]
        except Exception:
            ok = "BAD@%d" % len(k["arguments"]); shape = k["arguments"][-90:]
        out["tools"].append([k["name"], ok, shape])
    return out

if __name__ == "__main__":
    files = sorted(glob.glob(sys.argv[1])); modes = sys.argv[2].split(","); n = int(sys.argv[3])
    for f in files:
        body = json.load(open(f))["request"]
        for mode in modes:
            for i in range(n):
                print(f.split("/")[-1][:20], mode, json.dumps(call(body, mode == "stream"), ensure_ascii=False), flush=True)
