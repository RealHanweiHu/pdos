"""Native assistant continuation and the documented MiniMax function interface.

Continuation is private protocol data, never a business instruction or authority.
The format is selected from the server route, not from model output.
"""

import json
import re
from copy import deepcopy
from urllib.parse import urlsplit

from pdos_next.errors import DomainError

from .client import json_value

MINIMAX_CODEC = "minimax-functions/v1"
FUNCTIONS_CODEC = "openai-functions/v1"
FUNCTION_CODECS = {MINIMAX_CODEC, FUNCTIONS_CODEC}
FINISH_TOOL = "pdos_agent_output"


def response_codec(protocol, base_url, mode="auto"):
    if mode not in {"auto", "tools"}:
        return "native-schema/v1"
    target = urlsplit(base_url)
    return (
        MINIMAX_CODEC
        if (
            protocol == "openai-compatible"
            and target.scheme == "https"
            and target.port in {None, 443}
            and target.hostname in {"api.minimax.cn", "api.minimax.io"}
            and target.path.rstrip("/") == "/v1"
        )
        else FUNCTIONS_CODEC if mode == "tools" else "native-schema/v1"
    )


def tool_name(name):
    return name.replace("_", "_1").replace(".", "_0")


def business_name(name):
    return re.sub(r"_([01])", lambda match: "." if match[1] == "0" else "_", name)


def business_arguments(route, name, arguments):
    """Read MiniMax-M3's explicit proposal array envelopes before domain validation."""
    if (
        route.agent_response_codec != MINIMAX_CODEC
        or route.model != "MiniMax-M3"
        or name != "proposal.create"
        or not isinstance(arguments, dict)
    ):
        return arguments

    groups = _json_container(arguments.get("groups"), dict)
    if not isinstance(groups, dict):
        return arguments

    groups = dict(groups)
    if "items" in groups:
        items = _proposal_list(groups["items"])
        if isinstance(items, list):
            items = [
                {**item, "source_refs": _proposal_list(item["source_refs"], empty_string=True)}
                if isinstance(item, dict) and "source_refs" in item else item
                for item in items
            ]
        groups["items"] = items
    if "questions" in groups:
        groups["questions"] = _proposal_list(groups["questions"], empty_string=True)
    return {**arguments, "groups": groups}


def _json_container(value, expected):
    if isinstance(value, str):
        try:
            decoded = json_value(value)
        except (ValueError, RecursionError):
            return value
        if isinstance(decoded, expected):
            return decoded
    return value


def _proposal_list(value, *, empty_string=False):
    # The envelope names the array element. A bare object is still invalid.
    if isinstance(value, dict) and value.keys() == {"item"}:
        item = value["item"]
        if isinstance(item, dict):
            return [item]
        if isinstance(item, list):
            return item
    if empty_string and value == "":
        return []
    return _json_container(value, list)


def finish_tool(schema):
    return {
        "type": "function",
        "function": {
            "name": FINISH_TOOL,
            "description": "Return the structured response for this turn, including questions or "
            "unfinished work. This reports model output only; it never executes or approves a "
            "business action. Use business tools first when the goal needs actual work.",
            "parameters": schema,
        },
    }


def public_text(content):
    if content is None:
        return ""
    if not isinstance(content, str):
        raise ValueError("Text content required")
    value = content
    while value.lstrip().startswith("<think>"):
        text = value.lstrip()[len("<think>") :]
        if "</think>" not in text:
            raise ValueError("Incomplete reasoning envelope")
        value = text.split("</think>", 1)[1]
    return value


def private_continuation(route, message):
    # Response-only names/audio/diagnostics are not request messages. Preserve the
    # complete supported text, thinking and native tool-call fields byte-for-byte.
    fields = {
        key: deepcopy(message[key])
        for key in ("role", "content", "reasoning_content", "tool_calls")
        if key in message and (key != "reasoning_content" or message[key] is not None)
    }
    if fields.get("role") != "assistant" or not isinstance(fields.get("content") or "", str):
        raise ValueError("Assistant text required")
    if "reasoning_content" in fields and not isinstance(fields["reasoning_content"], str):
        raise ValueError("Reasoning continuation must be text")
    return {"protocol": route.protocol, "route_digest": route.digest, "message": fields}


def restore_assistant(route, message):
    saved = message.get("provider_continuation")
    if saved is None:
        return None
    try:
        if (
            set(saved) != {"protocol", "route_digest", "message"}
            or saved["protocol"] != route.protocol
            or saved["route_digest"] != route.digest
            or route.protocol != "openai-compatible"
            or message["role"] != "assistant"
        ):
            raise ValueError
        native = saved["message"]
        if set(native) - {"role", "content", "reasoning_content", "tool_calls"}:
            raise ValueError
        if native.get("role") != "assistant":
            raise ValueError
        text = (
            public_text(native.get("content"))
            if route.agent_response_codec == MINIMAX_CODEC
            else (native.get("content") or "")
        )
        if text != message.get("content", ""):
            raise ValueError
        if "reasoning_content" in native and not isinstance(native["reasoning_content"], str):
            raise ValueError
        normal, finish_ids = [], []
        for call in native.get("tool_calls") or []:
            if call["type"] != "function" or not isinstance(call["function"]["arguments"], str):
                raise ValueError
            if call["function"]["name"] == FINISH_TOOL:
                if route.agent_response_codec not in FUNCTION_CODECS:
                    raise ValueError
                finish_ids.append(call["id"])
            else:
                normal.append(
                    {
                        "id": call["id"],
                        "name": business_name(call["function"]["name"]),
                        "arguments": json_value(call["function"]["arguments"]),
                    }
                )
        saved_calls = message.get("tool_calls", [])
        # Old histories recorded the raw arguments. New histories record the
        # decoded arguments, but still send MiniMax its original native message.
        if normal != saved_calls and [
            {**call, "arguments": business_arguments(route, call["name"], call["arguments"])}
            for call in normal
        ] != saved_calls:
            raise ValueError
        if (
            finish_ids and (normal or len(finish_ids) != 1 or len(native["tool_calls"]) != 1)
        ):
            raise ValueError
        messages = [deepcopy(native)]
        if finish_ids:
            # The function records output only. Acknowledge receipt before a later
            # user answer; this is not a domain receipt or approval.
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": finish_ids[0],
                    "content": json.dumps({"response_received": True}),
                }
            )
        return messages
    except (ValueError, TypeError, KeyError, AttributeError):
        raise DomainError("VERSION_CONFLICT", "原模型协议续接与当前消息或路由不一致。") from None
