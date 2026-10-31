"""Pinned jieba search tokens, versioned OR queries and an independent identifier channel."""

import hashlib
import importlib.metadata
import logging
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

import jieba

ROOT = Path(__file__).parent
CODE_RULE = "enterprise-codes/v2"
CHUNKER = "located-lines/v1"
RANKING = "bm25-title-2.5-k1-1.2-b0.75-freshness180-native-id-onehop20/v3"
CODE = re.compile(
    r"(?<![A-Z0-9])(?:"
    r"(?:GB/T|GB|IEC|ISO|EN|ASTM)\s*\d{2,8}(?:\.\d+)*(?:[-/]\d+)?"
    # Separated letter prefixes are identifiers too (FA-2026-029, TR-A7-006).
    # Require a digit so ordinary hyphenated words do not become codes.
    r"|[A-Z]{1,12}(?=[A-Z0-9./-]*\d)"
    r"(?:\d+[A-Z0-9]*|[-/.][A-Z0-9]+)(?:[-/.][A-Z0-9]+)*)(?![A-Z0-9])"
)
QUERY_RULE = "query-function-words/v1"
QUERY_FUNCTION_WORDS = frozenset(
    "我 我们 你 你们 您 这 这个 这些 那 那个 那些 把 对 按 先 再 别 是不是 不是".split()
)
QUERY_POLICY_VERSION = QUERY_RULE + "/" + hashlib.sha256(
    "\n".join(sorted(QUERY_FUNCTION_WORDS)).encode()
).hexdigest()
DASHES = str.maketrans({c: "-" for c in "‐‑‒–—−﹣"})


def normalize(value):
    return unicodedata.normalize("NFKC", value).translate(DASHES)


def codes(value):
    exact = sorted({re.sub(r"\s+", "", m.group()) for m in CODE.finditer(normalize(value).upper())})
    families = sorted({code.split("-", 1)[0] for code in exact if "-" in code})
    return exact, families


@lru_cache(maxsize=1)
def tokenizer():
    if importlib.metadata.version("jieba") != "0.42.1":
        raise RuntimeError("Enterprise projection requires pinned jieba 0.42.1")
    instance = jieba.Tokenizer()
    jieba.setLogLevel(logging.WARNING)
    instance.initialize()
    instance.load_userdict(str(ROOT / "terms.txt"))
    dictionary = Path(jieba.__file__).parent / "dict.txt"
    digest = hashlib.sha256(
        dictionary.read_bytes()
        + (ROOT / "terms.txt").read_bytes()
        + (ROOT / "stopwords.txt").read_bytes()
    ).hexdigest()
    return instance, frozenset((ROOT / "stopwords.txt").read_text().splitlines()), digest


def version():
    return "jieba-0.42.1-HMM-off/search/" + tokenizer()[2]


def analyze(value):
    instance, stopwords, _ = tokenizer()
    words, removed = [], set()
    for word in instance.cut_for_search(normalize(value).casefold(), HMM=False):
        if word in stopwords:
            removed.add(word)
        elif word and re.fullmatch(r"[\w]+", word, flags=re.UNICODE) and word != "_":
            words.append(word)
    exact, families = codes(value)
    return {
        "terms": sorted(set(words)),
        "counts": dict(Counter(words)),
        "length": len(words),
        "removed": sorted(removed),
        "codes": exact,
        "families": families,
        "tokenizer_version": version(),
        "code_rule_version": CODE_RULE,
    }


def analyze_query(value):
    """Remove request grammar only; retain raw text, IDs and the index vocabulary."""
    parsed = analyze(value)
    removed = set(parsed["terms"]) & QUERY_FUNCTION_WORDS
    return {
        **parsed,
        "terms": [term for term in parsed["terms"] if term not in QUERY_FUNCTION_WORDS],
        "counts": {
            term: count for term, count in parsed["counts"].items()
            if term not in QUERY_FUNCTION_WORDS
        },
        "length": parsed["length"] - sum(parsed["counts"].get(term, 0) for term in removed),
        "removed": sorted(set(parsed["removed"]) | removed),
        "query_policy_version": QUERY_POLICY_VERSION,
    }


def or_query(terms):
    # Only normalized word tokens enter tsquery syntax, never caller-supplied operators.
    if any(not re.fullmatch(r"\w+", term, flags=re.UNICODE) for term in terms):
        raise ValueError("Unsafe token in enterprise tsquery")
    return " | ".join("'" + term + "'" for term in terms)
