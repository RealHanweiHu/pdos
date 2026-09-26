"""Deterministic full-part-number clues with exact immutable source offsets."""

import re
from bisect import bisect_left, bisect_right
from html.parser import HTMLParser
from typing import Any

POLICY = "supplier-notice-literal-v1"
LIMIT = 50
MARKER = re.compile(
    r"(?<![A-Za-z])(?:EOL|PCN)(?![A-Za-z])|end[\s-]+of[\s-]+life|"
    r"product[\s-]+(?:change|discontinuance)[\s-]+(?:notice|notification)|停产|产品变更通知",
    re.IGNORECASE | re.ASCII,
)


class VisibleSegments(HTMLParser):
    def __init__(self, body: str):
        super().__init__(convert_charrefs=False)
        self.offsets = [0]
        for match in re.finditer("\n", body):
            self.offsets.append(match.end())
        self.hidden: list[str] = []
        self.segments: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            line, column = self.getpos()
            self.segments.append((self.offsets[line - 1] + column, data))


def match_notices(body: str, part_number: str) -> dict[str, Any]:
    html = bool(re.search(r"<(?:html|body|div|p|table|span)\b", body, re.IGNORECASE))
    if html:
        parser = VisibleSegments(body)
        parser.feed(body)
        parser.close()
        segments = parser.segments
    else:
        segments = [(m.start(), m.group()) for m in re.finditer(r"[^\r\n]+", body)]
    part = re.compile(
        r"(?<![A-Za-z0-9_./-])" + re.escape(part_number) + r"(?![A-Za-z0-9_./-])",
        re.IGNORECASE | re.ASCII,
    )
    markers = [
        (offset + m.start(), index, m.start(), m.end())
        for index, (offset, content) in enumerate(segments)
        for m in MARKER.finditer(content)
    ]
    positions = [m[0] for m in markers]
    found: list[dict[str, Any]] = []
    full_part_hits = 0
    for index, (offset, content) in enumerate(segments):
        for hit in part.finditer(content):
            full_part_hits += 1
            if full_part_hits > 10000:
                return {
                    "matches": found,
                    "truncated": True,
                    "full_part_hits": full_part_hits - 1,
                    "coverage": coverage(html),
                }
            near = []
            position = offset + hit.start()
            for absolute, j, a, b in markers[
                bisect_left(positions, position - 1200) : bisect_right(positions, position + 1200)
            ]:
                if abs(j - index) > 2 or (j == index and a < hit.end() and b > hit.start()):
                    continue
                start, segment = segments[j]
                near.append((abs(absolute - position), start, segment, a, b))
            if not near:
                continue
            _, marker_offset, marker_segment, marker_start, marker_end = min(near)

            def quote(start: int, value: str, a: int, b: int) -> dict[str, Any]:
                left, right = max(0, a - 220), min(len(value), b + 320)
                return {"start": start + left, "end": start + right, "text": value[left:right]}

            quotes = [quote(offset, content, hit.start(), hit.end())]
            marker_quote = quote(marker_offset, marker_segment, marker_start, marker_end)
            if marker_quote != quotes[0]:
                quotes.append(marker_quote)
            found.append(
                {
                    "part": content[hit.start() : hit.end()],
                    "part_start": offset + hit.start(),
                    "part_end": offset + hit.end(),
                    "marker": marker_segment[marker_start:marker_end],
                    "marker_start": marker_offset + marker_start,
                    "marker_end": marker_offset + marker_end,
                    "quotes": quotes,
                }
            )
            if len(found) > LIMIT:
                return {
                    "matches": found[:LIMIT],
                    "truncated": True,
                    "full_part_hits": full_part_hits,
                    "coverage": coverage(html),
                }
    return {
        "matches": found,
        "truncated": False,
        "full_part_hits": full_part_hits,
        "coverage": coverage(html),
    }


def coverage(html: bool) -> str:
    return (
        "仅按完整料号及邻近通告词形成线索，未判定厂商真实发布、适用性或生效日期。"
        "不读取链接附件、图片、扫描件和脚本；不展开通配料号或料号范围。"
        + (
            "HTML仅匹配文本片段；跨标签/字符实体拆分的料号可能漏检。"
            if html
            else "仅覆盖本快照文字。"
        )
    )
