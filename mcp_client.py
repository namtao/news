"""Client tối giản cho MCP server chạy streamable HTTP (JSON-RPC over SSE)."""

import json

import httpx

from config import MCP_TIMEOUT, MCP_URL

_ACCEPT = "application/json, text/event-stream"
_CLIENT_INFO = {"name": "ban-tin-tong-hop", "version": "1.0"}


def _parse_body(body: str):
    """Đọc payload JSON-RPC từ luồng SSE (bỏ dòng ping) hoặc từ JSON thuần."""
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


async def call_tool(name: str, arguments: dict, timeout: float = MCP_TIMEOUT):
    """Gọi một tool MCP và trả về nội dung text đã parse JSON, None nếu lỗi."""
    if not MCP_URL:
        return None
    headers = {"Content-Type": "application/json", "Accept": _ACCEPT}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            init = await client.post(
                MCP_URL,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": _CLIENT_INFO,
                    },
                },
            )
            init.raise_for_status()
            session = init.headers.get("mcp-session-id")
            if session:
                headers["mcp-session-id"] = session
            await client.post(
                MCP_URL,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            resp = await client.post(
                MCP_URL,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"  ⚠ MCP {name}: {e}")
        return None

    payload = _parse_body(resp.text)
    if not payload or "result" not in payload:
        print(f"  ⚠ MCP {name}: {payload.get('error') if payload else 'no payload'}")
        return None
    content = payload["result"].get("content") or []
    if not content:
        return None
    try:
        return json.loads(content[0].get("text", ""))
    except json.JSONDecodeError:
        return content[0].get("text", "")
