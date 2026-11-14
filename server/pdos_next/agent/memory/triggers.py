"""Fixed, reviewed expressions in the owner's own words (P121 第 8、9 项; P84 第 7 项).

Everything here is deterministic text matching on the part of a message the
owner typed (page material removed by the caller). No model call, no learning:
the lists change only by code review, and each change is re-measured on the
labelled replay set (``docs/evaluations/xiaopai-memory-v0/proposal-triggers.json``,
``tools/xiaopai_memory_proposal_replay.py``).

Four fixed lists:

* ``remember``: 面向小Pai 今后行为的明确说法 ("记住……", "以后都……", "以后给我……",
  "每次都……"). Ordinary statements such as "我一般……" or "我习惯……" are not in
  it (P121 第 9 项). A question, a negated or third-person use ("不用记住",
  "我记住了", "供应商以后都……") does not count.
* ``alias``: the owner naming something ("我说的 X 就是 Y"). Only opens a proposal
  of kind ``alias``.
* ``correction``: the owner correcting 小Pai ("不对", "应该是……"). A proactive
  proposal must quote at least two of these from different Runs of the Session.
* ``discussion``: "这只是讨论，不算决定". Voids the Session's pending candidates and
  keeps what was said so far from being proposed again.

The lists are a necessary condition, never a sufficient one: the model must
still propose and the owner must still confirm.
"""

import re

VERSION = "memory-proposal-triggers/v3"

_STOP = "，。；！？,.;!?\n"
_FULL_STOP = "。；！？.;!?\n"
_CLAUSE = f"[^{_STOP}]"
_SENTENCE = f"[^{_FULL_STOP}]"  # may cross a comma
# An instruction to 小Pai starts its clause, or follows only an address or a filler.
_LEAD = (r"(?:^|(?<=[，。；！？,.;!?\n：:\s]))"
         r"(?:那就?|所以|好的?|嗯|另外|还有|对了|我再说一次，?|请|麻烦|你)*")
_NEGATION = re.compile(r"不要|不用|不必|无需|不需要|没必要|千万别|别|甭")
_OTHER_SUBJECT = re.compile(
    r"(?<![给帮替])(?:我|我们|他|她|他们|她们|大家|客户|对方)"
    r"(?:会|已经|已|都|也|要|得|早就|一直|还|没|没有)*$"
)
_QUESTION = re.compile(r"[?？]|吗|是不是|会不会|要不要|有什么|什么区别|怎么|如何|能不能|可不可以")

_FUTURE = r"(?:以后|今后|往后|从今往后|下次|下回)"
_NOT_PLAN = r"(?!再|可能|也许|或许|可以|看情况|有空|有机会|有时间|会不会|万一|会)"
_RULE = (r"(?:都(?!会|是|有|没)|一律|统一|默认|请|给我|帮我|替我|不要|别|不用|只|按|用|"
         r"记得|先|把|要|叫我|提醒我|控制)")
_VERBS = r"记住|记一下|记下来|帮我记|记一条|牢记|(?:你要|你得|务必)记得|记得(?=以后)"

REMEMBER = tuple(re.compile(pattern) for pattern in (
    _VERBS,
    # “以后/今后/下次……” opening a clause and followed, within the sentence, by a
    # word that makes it a rule or an instruction. “以后再说”“以后可能会变” are not.
    _LEAD + _FUTURE + _NOT_PLAN + _SENTENCE + r"{0,24}?" + _RULE,
    _LEAD + r"(?:每次|每回)" + _CLAUSE
    + r"{0,10}?(?:都(?!会|是|有|没|要)|先|给我|帮我|请|必须|记得)",
    _LEAD + r"从(?:现在|今天|明天|今|此|下次|下周|下个月)(?:起|开始|以后|往后)",
    _LEAD + r"下次起",
))
_VERB = re.compile(_VERBS)

ALIAS = tuple(re.compile(pattern) for pattern in (
    r"我(?:们|们组|们这边)?(?:所)?(?:说|讲|叫|提|口中|嘴里)的?(?!不|过)" + _SENTENCE
    + r"{1,40}?(?:就是|是指|指的是|指的就是|都是指|其实是|意思是|"
    r"指(?!标|出|定|导|示|向|望|数|引|挥))",
    r"我把" + _CLAUSE + r"{1,30}?(?:叫做|叫作|称为|称作|叫)",
    r"在我这(?:儿|里|边)?(?:就是|是)指?",
    r"是我对" + _CLAUSE + r"{1,20}?的(?:叫法|说法|称呼)",
))

_START = (r"(?:^|(?<=[，。；！？,.;!?\n：:\s]))"
          r"(?:你|这|这个|这里|这样|那|刚才|还是|又|都|也)*")
CORRECTION = tuple(re.compile(pattern) for pattern in (
    _START + r"不对(?!劲|称|等|齐|外|应|口)",
    _START + r"错了(?!就)",
    _START + r"(?:搞|弄|写|看|记|算|理解)(?:错|混|偏|反)",
    _START + r"(?:有误|纠正|更正|漏了)",
    r"应该(?:是|用|按|写|叫|为)",
    r"改成|改为|换成",
    r"我(?:说|要|指)的是",
    r"说过",
    r"(?<!是)不是(?!很|太|特别|不|说|我|所有|每|都)",
))

_ONLY = (r"(?<!不)(?:只是|仅是|仅仅是|只不过是|纯属|算是)(?:在|我)?(?:初步)?"
         r"(?:讨论|探讨|闲聊|聊聊|随便聊聊|随便说说|随口一说|随口说的|想法|头脑风暴|试探|设想)")
_DECISION = r"(?:最终|正式)?(?:的)?(?:决定|决议|决策|定论|结论|拍板)(?!性|因素|权)"
DISCUSSION = tuple(re.compile(pattern) for pattern in (
    _ONLY,
    r"仅供讨论|不作数",
    r"(?<!是)(?:不算|不作为|不是|不能算|不当作)" + _DECISION,
    r"(?:别|不要|请勿)" + _CLAUSE + r"{0,12}?(?:当成?|当作|记成|记录为|算作)" + _DECISION,
))


def _spans(patterns, text):
    for pattern in patterns:
        yield from pattern.finditer(text)


def _around(message, start, end, stops):
    """(text before the match, whole unit) between the nearest ``stops``."""
    left = max((message.rfind(stop, 0, start) for stop in stops), default=-1) + 1
    rights = [index for index in (message.find(stop, end) for stop in stops) if index >= 0]
    return message[left:start], message[left:min(rights) + 1 if rights else len(message)]


def _matches(patterns, message, quote):
    """Matches of ``patterns`` that lie inside an occurrence of ``quote`` in ``message``."""
    start = message.find(quote)
    while quote and start >= 0:
        for match in _spans(patterns, message):
            if match.start() >= start and match.end() <= start + len(quote):
                yield match
        start = message.find(quote, start + 1)


def remember(message, quote):
    """True when ``quote`` (a verbatim part of ``message``) holds a remember expression."""
    for match in _matches(REMEMBER, message, quote):
        if _QUESTION.search(_around(message, match.start(), match.end(), _FULL_STOP)[1]):
            continue  # Asking about it is not telling 小Pai to do it.
        before = _around(message, match.start(), match.end(), _STOP)[0]
        if _VERB.fullmatch(match.group(0)) and (
            _NEGATION.search(before) or _OTHER_SUBJECT.search(before)
        ):
            continue
        return True
    return False


def alias(message, quote):
    return any(
        not _QUESTION.search(_around(message, match.start(), match.end(), _FULL_STOP)[1])
        for match in _matches(ALIAS, message, quote))


def correction(quote):
    return any(True for _match in _spans(CORRECTION, quote))


def discussion(message):
    return any(True for _match in _spans(DISCUSSION, message))
