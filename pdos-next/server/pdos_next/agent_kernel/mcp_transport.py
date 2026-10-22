"""Official SDK Streamable HTTP transport; never follows server-supplied actions."""

import asyncio
import json
from datetime import timedelta

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr

from pdos_next.errors import DomainError

from .mcp_binding import redact_credential

MAX_RESULT_BYTES = 2_097_152


class StreamableMcpTransport:
    def __init__(self, *, client_factory=None, timeout=60):
        self.client_factory, self.timeout = client_factory, timeout

    async def invoke(self, endpoint, credential, tool, arguments):
        # No ambient proxy, cookies, roots, sampling, elicitation or automatic OAuth.
        factory = self.client_factory or httpx.AsyncClient
        value = credential.get_secret_value() if isinstance(credential, SecretStr) else credential
        async with factory(
            headers={"Authorization": "Bearer " + value},
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with streamable_http_client(endpoint, http_client=client) as (read, write, _):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=self.timeout)
                ) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
                    if result.isError:
                        raise DomainError("SOURCE_UNAVAILABLE", "连接器未成功完成此工具调用。")
                    value = {
                        "content": [
                            {"type": "text", "text": item.text}
                            for item in result.content
                            if item.type == "text"
                        ],
                        "structured_content": result.structuredContent,
                        "unsupported_content": [
                            item.type for item in result.content if item.type != "text"
                        ],
                    }
                    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
                        raise DomainError("SOURCE_UNAVAILABLE", "连接器结果超出单次读取上限。")
                    return redact_credential(value, credential)

    def __call__(self, endpoint, credential, tool, arguments):
        try:
            return asyncio.run(self.invoke(endpoint, credential, tool, arguments))
        except Exception:
            # SDK/HTTP exception text may contain authorization headers or remote bodies.
            raise DomainError(
                "SOURCE_UNAVAILABLE", "MCP 服务响应暂不可用，请核对原调用。"
            ) from None
