"""Fixed, reviewed expressions in the owner's own words (P121 第 8、9 项; P84 第 7 项).

Everything here is deterministic text matching on the part of a message the
owner typed (page material removed by the caller). No model call, no learning:
the lists change only by code review, and each change is re-measured on the
labelled replay set (``docs/evaluations/xiaopai-memory-v0/proposal-triggers.json``,
``tools/xiaopai_memory_proposal_replay.py``).

Four fixed lists:

* ``remember``: 面向小Pai 今后行为的明确说法 ("记住……", "以后都……", "以后给我……",
  "每次都……"). Ordinary statements such as "我一般……" or "我习惯……" are not in
  it (P121 第 9 项), and a negated or third-person use ("不用记住", "我记住了") does
  not count.
* ``alias``: the owner naming something ("我说的 X 就是 Y"). Only opens a proposal
  of kind ``alias``.
* ``correction``: the owner correcting 小Pai ("不对", "应该是……"). A proactive
  proposal must quote at least two of these from different Runs of the Session.
* ``discussion``: "这只是讨论，不算决定". Voids the Session's pending candidates and
  keeps what was said so far from being proposed again.
"""

import re

VERSION = "memory-proposal-triggers/v2"

_CLAUSE = r"[^，。；！？,.;!?\n]"
# A match is ignored when the words just before it negate it or make someone
# other than 小Pai its subject: "不用记住", "要不要记住", "我已经记住了".
_NEGATED = re.compile(
    r"(?:不要|不用|不必|无需|不需要|没必要|别|甭|不)(?:再|帮我|给我|替我|特意|专门|刻意|急着)*$"
)
_OTHER_SUBJECT = re.compile(
    r"(?:我|我们|他|她|他们|她们|大家|客户|对方)(?:会|已经|已|都|也|要|得|早就|一直|还|没|没有)*$"
)

REMEMBER = tuple(re.compile(pattern) for pattern in (
    r"记住",
    r"记一下",
    r"记下来",
    r"帮我记",
    # “以后/今后……” followed in the same clause by a word that makes it a rule
    # or an instruction. “以后再说”“以后可能会变” are not instructions.
    r"(?:以后|今后|往后)(?!再|可能|也许|或许|可以|看情况|有空|有机会|有时间|会不会|万一)"
    + _CLAUSE + r"{0,16}?(?:都|一律|统一|默认|请|给我|帮我|替我|不要|别|不用|只|按|用|记得|先)",
    r"每次" + _CLAUSE + r"{0,10}?(?:都|先|给我|帮我|请|必须|记得)",
    r"从现在起|从现在开始|从今以后|从今天起|从此以后|下次起|从下次起|从下次开始",
))
_VERB = frozenset({"记住", "记一下", "记下来", "帮我记"})

ALIAS = (re.compile(
    r"我们?(?:说|讲|叫|提)的?(?!不)" + _CLAUSE + r"{1,40}?(?:就是|是指|指的是|指的就是|都是指|指)"
),)

CORRECTION = tuple(re.compile(pattern) for pattern in (
    r"不对",
    r"错了",
    r"[搞弄写看记]错",
    r"应该(?:是|用|按|写|叫)",
    r"改成|改为|换成",
    r"我(?:说|要|指)的是",
    r"说过",
    r"(?<!是)不是(?!很|太|特别|不|说)",
))

DISCUSSION = tuple(re.compile(pattern) for pattern in (
    r"(?<!不)(?:只是|仅是|仅仅是|只不过是|纯属)(?:在)?(?:讨论|探讨|闲聊|随便聊聊|随便说说|随口一说)",
    r"仅供讨论",
    r"(?<!是)(?:不算|不作为|不是|不能算|不当作|别当成|不要当成)(?:最终|正式)?(?:的)?决定(?!性|因素|权)",
))


def _spans(patterns, text):
    for pattern in patterns:
        yield from pattern.finditer(text)


def remember(message, quote):
    """True when ``quote`` (a verbatim part of ``message``) holds a remember expression."""
    return _within(REMEMBER, message, quote, guarded=True)


def alias(message, quote):
    return _within(ALIAS, message, quote, guarded=False)


def _within(patterns, message, quote, *, guarded):
    start = message.find(quote)
    while quote and start >= 0:
        end = start + len(quote)
        for match in _spans(patterns, message):
            if match.start() < start or match.end() > end:
                continue
            before = message[:match.start()]
            if guarded and match.group(0) in _VERB and (
                _NEGATED.search(before) or _OTHER_SUBJECT.search(before)
            ):
                continue
            return True
        start = message.find(quote, start + 1)
    return False


def correction(quote):
    return any(True for _match in _spans(CORRECTION, quote))


def discussion(message):
    return any(True for _match in _spans(DISCUSSION, message))
