"""D577 对照组：稳定命中是不是因为请求里有一条助手消息。

probe-results.md §2 的推断是“服务商对含有助手消息的对话更稳定地复用它之前的前缀”。
C 组用的是同一句固定回复，分不清起作用的是“有助手消息”还是“这句回复发过”。这里每轮
换一句从没发过的助手回复（E 组），与结构相同但没有助手消息的 B 组交替发送：

- E 组与以前任何请求的共同前缀只有系统提示、工具定义和技能正文，和 B 组一样；
- 如果 E 稳定命中而 B 不稳定，起作用的就是助手消息本身。

规模：预热 1 次，B、E 各 5 轮，共 11 次，另加开头 1 次很小的探活请求（服务商过载时等两分钟
再探一次，仍过载就不开始）。第一次运行（11-17，序号 63–74）在 11-16 批准的 74 次内，当时
还补了 1 次原 C 组；补跑由用户 11-17 另行批准约 12 次。序号和累计 token 接着往下记，累计
输入不超过 400 万 token。

用法：server/.venv/bin/python <本文件> <模板请求体路径>
模板可用 .local/context-cache-probe-20261116/requests/001-A.json。
"""
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_run import OUT, Probe  # noqa: E402

QUESTIONS = [
    "合成对照题 01：会议纪要一般分哪几个部分？只列类别。",
    "合成对照题 02：怎样判断一个任务的完成标准写得够不够清楚？",
    "合成对照题 03：样品签收时通常要核对哪些信息？",
    "合成对照题 04：进度落后时，更新计划前先确认哪三件事？",
    "合成对照题 05：一份测试报告的结论部分怎么写更容易被读懂？",
]
ROUNDS = 5
PHASE = "control_rerun"  # 第一次运行记的是 control。
CALLS = 2 * ROUNDS + 1  # 预热加两组各五轮，不含探活。


def previous():
    """Calls and prompt tokens already spent by the first probe."""
    rows = [json.loads(line) for line in (OUT / "calls.jsonl").read_text().splitlines() if line]
    return len(rows), max((row.get("cumulative_prompt_tokens") or 0) for row in rows)


def alive(probe):
    """One tiny request without tools: is the provider answering at all right now?"""
    try:
        response = httpx.post(
            f"{probe.base_url}/chat/completions", timeout=httpx.Timeout(60, connect=20),
            headers={"Authorization": f"Bearer {probe.key}"},
            json={"model": probe.model, "max_completion_tokens": 8,
                  "messages": [{"role": "user", "content": "合成探活：请回复“在”。"}]})
    except httpx.HTTPError as error:
        print("alive check failed:", type(error).__name__, flush=True)
        return False
    print("alive check status", response.status_code, flush=True)
    return response.status_code == 200


def main():
    calls, tokens = previous()
    assert tokens + CALLS * 45_000 <= 4_000_000, f"token budget: {tokens} already used"
    probe = Probe(sys.argv[1])
    probe.seq, probe.tokens = calls, tokens
    if not alive(probe):
        time.sleep(120)
        if not alive(probe):
            raise SystemExit("provider still overloaded; nothing was started")

    def with_reply(question, reply):
        messages = probe.messages("C", question)
        assert messages[2]["role"] == "assistant"
        messages[2] = {"role": "assistant", "content": reply}
        return messages

    probe.send("C0", probe.messages("C0", None), phase=PHASE + "_preheat",
               note="对照组预热，只含系统提示、工具、技能正文")
    time.sleep(10)
    for index in range(ROUNDS):
        question = QUESTIONS[index]
        reply = f"好的，说明已收到（对照 {index + 1}，{uuid.uuid4()}）。请给出本轮的问题。"
        order = "BE" if index % 2 == 0 else "EB"
        for position, group in enumerate(order):
            messages = (probe.messages("B", question) if group == "B"
                        else with_reply(question, reply))
            probe.send(group, messages, phase=PHASE, round_no=index + 1,
                       question=index + 1, fresh=True,
                       note="每轮一句没发过的助手回复" if group == "E" else None)
            if position == 0:
                time.sleep(10)
        time.sleep(30)
    print("done; cumulative prompt tokens", probe.tokens, "calls", probe.seq)


if __name__ == "__main__":
    main()
