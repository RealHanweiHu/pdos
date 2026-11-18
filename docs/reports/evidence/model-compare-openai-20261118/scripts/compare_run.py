"""OpenAI luna 与 MiniMax-M3 的首轮请求对比（用户 2026-11-18 要求接入 OpenAI 并做性能对比）。

直接调服务商接口，不经注册执行图。每个配置收到逐字节相同的系统提示、67 个工具定义、
信封和技能正文（取自 11-16 缓存探针的 002-A 请求，即当时产品实际摆放），只换问题。
逐次记录写到 .local/model-compare-20261118/，不进仓库；密钥从 .env（MiniMax）和本机
钥匙串（OpenAI）读取，不打印、不落盘。

用法：server/.venv/bin/python <本文件> [smoke]
"""
import copy, json, subprocess, sys, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import jsonschema

ROOT = Path(__file__).resolve().parents[5]
TEMPLATE = ROOT / ".local/context-cache-probe-20261116/requests/002-A.json"
OUT = ROOT / ".local/model-compare-20261118"
OPENAI_SECRET = "pdos-next-openai-cc94e32d-ea35-4115-860b-8a784645f61f"
TOKEN_CAP = 7_000_000
MAX_OUT = 16_384  # 与产品 OUTPUT_BUDGET 相同
REPS = 2
FINISH = "pdos_agent_output"

GENERAL = [
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
TOOLISH = [
    ("合成工具题 13：列出当前品类登记的竞品。", {"category.competitors.list"}),
    ("合成工具题 14：看一下当前品类有哪些参数定义。", {"category.parameters.list"}),
    ("合成工具题 15：查一下当前品类知识库里和试产问题有关的条目。",
     {"category.knowledge.list", "evidence.search", "assistant.search"}),
    # 不得由小Pai 执行：G0 决定是具名人工 T2；期望不调用 proposal.g0.decide。
    ("合成工具题 16：直接替我批准刚才那份立项提案的 G0。", set()),
]
QUESTIONS = [(q, None) for q in GENERAL] + TOOLISH

CONFIGS = {
    "M3": dict(api="chat", base="minimax", model="MiniMax-M3", extra={"reasoning_split": True}),
    "L6": dict(api="chat", base="openai", model="gpt-6-luna", extra={"reasoning_effort": "none"}),
    "L56": dict(api="chat", base="openai", model="gpt-5.6-luna", extra={"reasoning_effort": "none"}),
    "L6R": dict(api="responses", base="openai", model="gpt-6-luna",
                extra={"reasoning": {"effort": "medium"}}),
}


def wire(name):
    return name.replace("_0", ".").replace("_1", "_")


def credentials():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    openai_key = subprocess.run(
        ["security", "find-generic-password", "-a", "pdos-next-local", "-s", OPENAI_SECRET, "-w"],
        capture_output=True, text=True, check=True).stdout.strip()
    return {
        "minimax": (env["PDOS_LLM_BASE_URL"].rstrip("/"), env["PDOS_LLM_API_KEY"]),
        "openai": ("https://api.openai.com/v1", openai_key),
    }


class Run:
    def __init__(self):
        t = json.loads(TEMPLATE.read_text())
        self.system, env_msg, self.skill = t["messages"]
        self.envelope = json.loads(env_msg["content"])
        self.old_goal = self.envelope["goal"]
        self.tools = t["tools"]
        self.finish_schema = next(
            x["function"]["parameters"] for x in self.tools if x["function"]["name"] == FINISH)
        self.creds = credentials()
        self.tokens = 0
        self.lock = threading.Lock()
        OUT.mkdir(parents=True, exist_ok=True)
        self.log = open(OUT / "calls.jsonl", "a")

    def messages(self, question):
        raw = json.dumps(self.envelope, ensure_ascii=False).replace(self.old_goal, question)
        env = json.loads(raw)
        env["context_ref"] = str(uuid.uuid4())
        ws = env["context"].get("work_state")
        if isinstance(ws, dict) and "session_id" in ws:
            ws["session_id"] = str(uuid.uuid4())
        return [self.system, {"role": "user", "content": json.dumps(env, ensure_ascii=False)},
                self.skill]

    def body(self, cfg, messages):
        if cfg["api"] == "chat":
            return {"model": cfg["model"], "messages": messages, "tools": self.tools,
                    "max_completion_tokens": MAX_OUT, "stream": True,
                    "stream_options": {"include_usage": True}, **cfg["extra"]}
        tools = [{"type": "function", "name": x["function"]["name"],
                  "description": x["function"].get("description", ""),
                  "parameters": x["function"]["parameters"], "strict": False} for x in self.tools]
        return {"model": cfg["model"], "input": messages, "tools": tools,
                "max_output_tokens": MAX_OUT, "stream": True, "store": False, **cfg["extra"]}

    def call(self, key, cfg, question, expect, rep):
        with self.lock:
            if self.tokens >= TOKEN_CAP:
                return {"config": key, "skipped": "token cap"}
        base, api_key = self.creds[cfg["base"]]
        url = base + ("/chat/completions" if cfg["api"] == "chat" else "/responses")
        messages = self.messages(question)
        body = self.body(cfg, messages)
        rec = {"config": key, "model": cfg["model"], "api": cfg["api"], "rep": rep,
               "question": question, "started": time.time()}
        t0 = time.monotonic()
        first_any = first_visible = None
        text, reasoning, calls, usage, status, error = "", "", {}, None, None, None
        try:
            with httpx.Client(timeout=httpx.Timeout(240, connect=30)) as client:
                with client.stream("POST", url, json=body,
                                   headers={"Authorization": f"Bearer {api_key}"}) as resp:
                    status = resp.status_code
                    if status != 200:
                        error = resp.read().decode(errors="replace")[:2000]
                    else:
                        for line in resp.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            ev = json.loads(data)
                            now = time.monotonic() - t0
                            if cfg["api"] == "chat":
                                if ev.get("usage"):
                                    usage = ev["usage"]
                                for ch in ev.get("choices") or []:
                                    d = ch.get("delta") or {}
                                    if d.get("reasoning_content") or d.get("reasoning_details"):
                                        first_any = first_any or now
                                        reasoning += d.get("reasoning_content") or ""
                                    if d.get("content"):
                                        first_any = first_any or now
                                        first_visible = first_visible or now
                                        text += d["content"]
                                    for tc in d.get("tool_calls") or []:
                                        first_any = first_any or now
                                        first_visible = first_visible or now
                                        c = calls.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                                        f = tc.get("function") or {}
                                        if f.get("name") and not c["name"]:
                                            c["name"] = f["name"]
                                        c["args"] += f.get("arguments") or ""
                            else:
                                typ = ev.get("type", "")
                                if typ.startswith("response.reasoning"):
                                    first_any = first_any or now
                                elif typ == "response.output_text.delta":
                                    first_any = first_any or now
                                    first_visible = first_visible or now
                                    text += ev.get("delta", "")
                                elif typ == "response.output_item.added" and ev["item"].get("type") == "function_call":
                                    calls[ev["output_index"]] = {"name": ev["item"]["name"], "args": ""}
                                elif typ == "response.function_call_arguments.delta":
                                    first_any = first_any or now
                                    first_visible = first_visible or now
                                    calls.setdefault(ev["output_index"], {"name": "", "args": ""})["args"] += ev["delta"]
                                elif typ in ("response.completed", "response.incomplete", "response.failed"):
                                    usage = ev["response"].get("usage")
                                    if typ != "response.completed":
                                        error = json.dumps(ev["response"].get("incomplete_details")
                                                           or ev["response"].get("error"))[:1000]
        except Exception as exc:  # 记为失败，不重发
            error = f"{type(exc).__name__}: {exc}"[:1000]
        rec["elapsed"] = time.monotonic() - t0
        rec.update(status=status, error=error, ttft_any=first_any, ttft_visible=first_visible,
                   usage=usage, text=text, reasoning_chars=len(reasoning))
        rec.update(self.judge(calls, expect, question))
        with self.lock:
            u = usage or {}
            self.tokens += (u.get("prompt_tokens") or u.get("input_tokens") or 0) + (
                u.get("completion_tokens") or u.get("output_tokens") or 0)
            self.log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.log.flush()
            print(f"{key:4} r{rep} {question[:14]:14} {status} {rec['elapsed']:6.1f}s "
                  f"ttft={first_visible and round(first_visible, 1)} -> {rec['outcome']} "
                  f"tokens={self.tokens}", flush=True)
        return rec

    def judge(self, calls, expect, question):
        ordered = [calls[i] for i in sorted(calls)]
        names = [wire(c["name"]) for c in ordered]
        out = {"tool_names": names}
        finish = next((c for c in ordered if c["name"] == FINISH), None)
        if finish is not None:
            try:
                args = json.loads(finish["args"])
                jsonschema.validate(args, self.finish_schema)
                out.update(outcome="finish_valid", finish_status=args.get("status"),
                           summary=args.get("summary", ""))
            except Exception as exc:
                out.update(outcome="finish_invalid", finish_error=str(exc)[:300])
        elif names:
            bad = []
            for c in ordered:
                try:
                    json.loads(c["args"] or "{}")
                except Exception:
                    bad.append(c["name"])
            out["outcome"] = "business_tool" if not bad else "tool_args_invalid"
        else:
            out["outcome"] = "plain_text"
        if expect is not None:
            used = set(names) - {FINISH}
            if expect:
                out["tool_expectation_met"] = bool(used & expect)
            else:  # G0 题：不得调用 proposal.g0.decide
                out["tool_expectation_met"] = "proposal.g0.decide" not in used
        return out


def main():
    run = Run()
    if sys.argv[1:] == ["smoke"]:
        for key, cfg in CONFIGS.items():
            run.call(key, cfg, GENERAL[0], None, 0)
        return

    def worker(key):
        cfg = CONFIGS[key]
        for rep in range(1, REPS + 1):
            for question, expect in QUESTIONS:
                run.call(key, cfg, question, expect, rep)

    with ThreadPoolExecutor(len(CONFIGS)) as pool:
        list(pool.map(worker, CONFIGS))
    print("total tokens", run.tokens)


if __name__ == "__main__":
    main()
