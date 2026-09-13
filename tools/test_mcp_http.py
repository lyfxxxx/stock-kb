"""HTTP MCP 端到端测试：连接 streamable HTTP 服务并调用工具。

环境变量：
    STOCK_KB_MCP_URL   服务地址，默认 http://127.0.0.1:8931/mcp
    STOCK_KB_TOKEN     Bearer token（可选）
"""

from __future__ import annotations

import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    url = os.environ.get("STOCK_KB_MCP_URL", "http://127.0.0.1:8931/mcp")
    token = os.environ.get("STOCK_KB_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    print("connect:", url)
    # 默认 5s 超时对冷启动的 initialize/工具调用过紧（首次要加载 sqlite-vec 扩展）；
    # trust_env=False 防止系统代理把 127.0.0.1 劫持到 HTTP_PROXY。
    async with httpx.AsyncClient(
        headers=headers, timeout=30.0, trust_env=False
    ) as http_client:
        async with streamable_http_client(
            url, http_client=http_client
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print("tools:", [t.name for t in tools.tools])
                res = await session.call_tool("list_companies", {})
                print("list_companies:", res.content[0].text)
                res2 = await session.call_tool(
                    "get_financial_statements",
                    {
                        "company": "海底捞",
                        "statement_type": "income",
                        "year": 2025,
                        "limit": 2,
                    },
                )
                print("income2025:", res2.content[0].text[:500])


if __name__ == "__main__":
    asyncio.run(main())
