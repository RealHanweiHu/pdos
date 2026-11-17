"""D577/D578 真实缓存探针（用户 11-16 同意运行）。

直接调服务商的 OpenAI 兼容接口，不经注册执行图；只发系统提示、工具定义、技能正文和合成题。
请求体与逐次记录写到 .local/context-cache-probe-20261116/，不进仓库。

用法：server/.venv/bin/python <本文件> <模板请求体路径>
"""
import copy, hashlib, json, os, sys, threading, time, uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / ".local" / "context-cache-probe-20261116"
TOKEN_CAP = 4_000_000
MAX_OUT = 64
GROUPS = "ABCD"
LATIN = ["ABCD", "BCDA", "CDAB", "DABC"]
QUESTIONS = [
    "合成题 01：请用三句话说明试验复盘通常包含哪些部分。",
    "合成题 02：一个样机验证计划里，风险清单一般怎么排序？",
    "合成题 03：评审会前需要准备哪些材料？只列类别。",
    "合成题 04：如何区分设计变更和工艺变更？简单说明。",
    "合成题 05：项目周报里“本周完成”和“下周计划”怎么写更清楚？",
    "合成题 06：供应商样件延期时，项目经理通常先做哪三件事？",
    "合成题 07：请解释什么是关键路径，用一个通用例子。",
    "合成题 08：试产问题记录表应该有哪些字段？",
    "合成题 09：怎样把一个大任务拆成可以分配的子任务？",
    "合成题 10：客户需求不清楚时，立项前可以怎么确认？",
    "合成题 11：BOM 版本之间的差异一般从哪几方面核对？",
    "合成题 12：项目收尾时要归档哪些东西？只列类别。",
]
CONCURRENT_QUESTIONS = [f"合成并发题 {i}：请简单介绍你能做什么。" for i in range(1, 5)]
FIXED_REPLY = "好的，我已读取上述说明。请给出本轮的问题。"
STABLE_KEYS = ("sources", "category", "personal_preferences", "assistant_depth")


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    return env["PDOS_LLM_BASE_URL"].rstrip("/"), env["PDOS_LLM_API_KEY"], env.get("PDOS_LLM_MODEL", "MiniMax-M3")


class Probe:
    def __init__(self, template_path):
        t = json.loads(Path(template_path).read_text())
        assert t["messages"][0]["role"] == "system"
        self.system = t["messages"][0]
        self.tools = t["tools"]
        self.envelope = json.loads(t["messages"][1]["content"])
        self.skill = t["messages"][2]
        assert self.skill["role"] == "user" and self.skill["content"].startswith("# ")
        self.old_goal = self.envelope["goal"]
        self.base_url, self.key, self.model = load_env()
        self.shared = None
        self.tokens = 0
        self.seq = 0
        self.last = {}
        self.lock = threading.Lock()
        OUT.mkdir(parents=True, exist_ok=True)
        self.log = open(OUT / "calls.jsonl", "a")

    def envelope_for(self, question):
        raw = json.dumps(self.envelope, ensure_ascii=False).replace(self.old_goal, question)
        env = json.loads(raw)
        env["context_ref"] = str(uuid.uuid4())
        ws = env["context"].get("work_state")
        if isinstance(ws, dict) and "session_id" in ws:
            ws["session_id"] = str(uuid.uuid4())
        return env

    def messages(self, group, question):
        if group == "C0":
            return [self.system, self.skill]
        env = self.envelope_for(question)
        dumps = lambda o: json.dumps(o, ensure_ascii=False)
        if group == "A":
            return [self.system, {"role": "user", "content": dumps(env)}, self.skill]
        if group == "B":
            return [self.system, self.skill, {"role": "user", "content": dumps(env)}]
        if group == "C":
            return [self.system, self.skill, {"role": "assistant", "content": FIXED_REPLY},
                    {"role": "user", "content": dumps(env)}]
        if group == "D":
            ctx = env["context"]
            stable = {"context": {k: ctx[k] for k in STABLE_KEYS if k in ctx}, "omitted_fields": env.get("omitted_fields", [])}
            dynamic = {"goal": env["goal"], "context": {k: v for k, v in ctx.items() if k not in STABLE_KEYS},
                       "context_ref": env["context_ref"]}
            return [self.system, self.skill, {"role": "user", "content": dumps(stable)},
                    {"role": "user", "content": dumps(dynamic)}]
        if group == "C0":
            return [self.system, self.skill]
        raise ValueError(group)

    @staticmethod
    def serial(messages, tools):
        # 服务商文档的匹配顺序：系统提示 → 工具定义 → 历史对话
        return (json.dumps(messages[0], ensure_ascii=False) + json.dumps(tools, ensure_ascii=False)
                + json.dumps(messages[1:], ensure_ascii=False)).encode()

    def send(self, group, messages, *, phase, round_no=None, question=None, fresh=True, note=None):
        with self.lock:
            if self.tokens >= TOKEN_CAP:
                raise SystemExit(f"token cap reached: {self.tokens}")
            self.seq += 1
            seq = self.seq
        body = {"model": self.model, "messages": messages, "tools": self.tools,
                "max_completion_tokens": MAX_OUT, "stream": True,
                "stream_options": {"include_usage": True}, "reasoning_split": True}
        ser = self.serial(messages, self.tools)
        prev = self.last.get(group)
        common = 0
        if prev is not None:
            n = min(len(prev), len(ser))
            while common < n and prev[common] == ser[common]:
                common += 1
        if phase in ("round", "retention"):
            self.last[group] = ser
        digest = hashlib.sha256(ser).hexdigest()
        (OUT / "requests").mkdir(exist_ok=True)
        (OUT / "requests" / f"{seq:03d}-{group}.json").write_text(json.dumps(body, ensure_ascii=False))
        client = httpx.Client(timeout=httpx.Timeout(120, connect=20)) if fresh else self.shared
        rec = {"seq": seq, "group": group, "phase": phase, "round": round_no, "question": question,
               "fresh_connection": fresh, "note": note, "request_sha256": digest, "request_bytes": len(ser),
               "common_prefix_bytes_vs_prev_same_group": common if prev is not None else None,
               "sent_at": time.time()}
        t0 = time.perf_counter()
        try:
            with client.stream("POST", f"{self.base_url}/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {self.key}"}) as r:
                rec["http_status"] = r.status_code
                if r.status_code != 200:
                    rec["error"] = r.read().decode(errors="replace")[:500]
                else:
                    usage = None
                    for line in r.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        ch = chunk.get("choices") or []
                        if ch and "ttft_ms" not in rec:
                            delta = ch[0].get("delta") or {}
                            if any(delta.get(k) for k in ("content", "reasoning_content", "reasoning_details", "tool_calls")):
                                rec["ttft_ms"] = round((time.perf_counter() - t0) * 1000)
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                    rec["usage"] = usage
        except Exception as exc:  # 记录后继续，不重试
            rec["error"] = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            if fresh:
                client.close()
        rec["total_ms"] = round((time.perf_counter() - t0) * 1000)
        u = rec.get("usage") or {}
        rec["prompt_tokens"] = u.get("prompt_tokens")
        rec["cached_tokens"] = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        with self.lock:
            self.tokens += u.get("prompt_tokens") or 0
            rec["cumulative_prompt_tokens"] = self.tokens
            self.log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.log.flush()
        print(f"#{seq:03d} {phase:9s} r={round_no} {group:2s} fresh={int(fresh)} prompt={rec['prompt_tokens']} "
              f"cached={rec['cached_tokens']} ttft={rec.get('ttft_ms')} total={rec['total_ms']} "
              f"err={rec.get('error', '')[:80]}", flush=True)
        return rec


def main():
    p = Probe(sys.argv[1])
    p.shared = httpx.Client(timeout=httpx.Timeout(120, connect=20))
    if sys.argv[2:] == ["smoke"]:
        p.send("A", p.messages("A", "合成冒烟题：你好。"), phase="smoke")
        return
    # C 组预热：只含固定说明
    p.send("C0", p.messages("C0", None), phase="preheat", note="C 组预热，只含系统提示、工具、技能正文")
    time.sleep(10)
    last_bodies = {}
    for r in range(12):
        fresh = r < 6
        order = LATIN[r % 4]
        for i, g in enumerate(order):
            msgs = p.messages(g, QUESTIONS[r])
            last_bodies[g] = msgs
            p.send(g, msgs, phase="round", round_no=r + 1, question=r + 1, fresh=fresh)
            if i < 3:
                time.sleep(10)
        time.sleep(30)
    # 留存：A、C 两组重发第 12 轮的同一请求
    start = time.time()
    for minute in (1, 5, 10, 20):
        time.sleep(max(0, start + minute * 60 - time.time()))
        for g in "AC":
            p.send(g, last_bodies[g], phase="retention", round_no=12, fresh=False, note=f"{minute} 分钟后重发")
    # 并发：4 个 A 组请求同时发出
    time.sleep(30)
    threads = [threading.Thread(target=p.send, args=("A", p.messages("A", q)),
                                kwargs={"phase": "concurrent", "fresh": True, "note": f"并发 {i + 1}/4"})
               for i, q in enumerate(CONCURRENT_QUESTIONS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    p.shared.close()
    print("done; cumulative prompt tokens", p.tokens)


if __name__ == "__main__":
    main()
