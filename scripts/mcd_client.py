"""麦当劳 MCP Streamable HTTP 客户端（零第三方依赖，仅用标准库 urllib）。

协议要点：
- 单次 POST 到 https://mcp.mcd.cn，JSON-RPC 2.0
- 首包携带 initialize，服务端在响应头回传 Mcp-Session-Id，后续请求必须带上
- 响应可能是 application/json，也可能是 text/event-stream（SSE），需要两种都解析
- 工具返回体可能是标准 JSON，也可能是官方自定义文本表格（如 list-nutrition-foods），
  由 parse_tool_text() 统一归一化
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

MCP_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """MCP 调用失败。"""


def token_from_workbuddy() -> str:
    """未设置环境变量时，自动读取 WorkBuddy 的 MCP 配置（~/.workbuddy/mcp.json）。"""
    try:
        cfg = Path.home() / ".workbuddy" / "mcp.json"
        if not cfg.exists():
            return ""
        data = json.loads(cfg.read_text(encoding="utf-8"))
        auth = data.get("mcpServers", {}).get("mcd-mcp", {}).get("headers", {}).get("Authorization", "")
        return auth[7:].strip() if auth.startswith("Bearer ") else ""
    except Exception:
        return ""


class McdClient:
    def __init__(self, token: str | None = None, url: str = MCP_URL, timeout: int = 40):
        self.token = (token or os.environ.get("MCD_MCP_TOKEN", "")
                      or token_from_workbuddy()).strip()
        if not self.token:
            raise McpError("缺少 MCP Token：请设置环境变量 MCD_MCP_TOKEN 或传入 token 参数")
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._req_id = 0
        self._initialized = False

    # ---------- 底层 ----------

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                ctype = (resp.headers.get("Content-Type") or "").lower()
                raw = resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:400]
            raise McpError(f"HTTP {e.code} {e.reason}: {detail}") from e
        except urllib.error.URLError as e:
            raise McpError(f"网络请求失败: {e.reason}") from e

        if "text/event-stream" in ctype:
            return self._parse_sse(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return self._parse_sse(raw)

    @staticmethod
    def _parse_sse(raw: str) -> dict:
        """从 SSE 文本里取出最后一个 data: 事件。"""
        last = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    last = payload
        if last is None:
            raise McpError(f"无法解析 SSE 响应：{raw[:200]}")
        try:
            return json.loads(last)
        except json.JSONDecodeError as e:
            raise McpError(f"SSE data 不是合法 JSON：{last[:200]}") from e

    # ---------- 协议 ----------

    def initialize(self) -> dict:
        resp = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcd-remainder", "version": "1.0.0"},
            },
        })
        if "error" in resp:
            raise McpError(f"initialize 失败: {resp['error']}")
        self._initialized = True
        # 通知服务端初始化完成（部分实现要求）
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        except McpError:
            pass
        return resp.get("result", {})

    def list_tools(self) -> list:
        resp = self._post({"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}})
        if "error" in resp:
            raise McpError(f"tools/list 失败: {resp['error']}")
        return resp.get("result", {}).get("tools", [])

    def call(self, name: str, arguments: dict | None = None) -> dict:
        """调用工具，返回归一化后的 dict（工具业务数据）。"""
        if not self._initialized:
            self.initialize()
        resp = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        if "error" in resp:
            raise McpError(f"{name} 调用失败: {resp['error']}")
        result = resp.get("result", {})
        if result.get("isError"):
            raise McpError(f"{name} 返回业务错误: {result}")
        return unwrap(result)


ORIGINAL_MARK = "## Original Response"


def unwrap(result: dict):
    """把 MCP tools/call 的 result 归一化成业务数据。

    官方返回的形态有三种，按可靠度依次尝试：
    1. structuredContent：干净的 JSON 对象（首选）
    2. content[].text 里的 "## Original Response" 之后的 JSON
    3. content[].text 里的自定义表格文本（如 list-nutrition-foods 的 [160]{...}）
    """
    sc = result.get("structuredContent")
    if isinstance(sc, dict) and sc:
        return normalize(sc.get("data", sc))

    content = result.get("content")
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        merged = "\n".join(t for t in texts if t).strip()
    elif isinstance(content, str):
        merged = content.strip()
    else:
        return {}

    if not merged:
        return {}

    # 优先取 Original Response 之后的整段 JSON
    pos = merged.find(ORIGINAL_MARK)
    if pos >= 0:
        tail = merged[pos + len(ORIGINAL_MARK):].strip()
        parsed = try_json(tail) or extract_json_block(tail)
        if parsed is not None:
            return normalize(parsed.get("data", parsed) if isinstance(parsed, dict) else parsed)

    parsed = try_json(merged)
    if parsed is not None:
        return normalize(parsed.get("data", parsed) if isinstance(parsed, dict) else parsed)

    candidate = extract_json_block(merged)
    if candidate is not None:
        return normalize(candidate.get("data", candidate) if isinstance(candidate, dict) else candidate)

    rows = parse_custom_table(merged)
    return rows if rows else {"_text": merged}


def normalize(data):
    """data 可能是 dict / list / 自定义表格字符串 / JSON 字符串，统一成 Python 对象。"""
    if isinstance(data, (dict, list)):
        return data
    if isinstance(data, str):
        s = data.strip()
        rows = parse_custom_table(s)
        if rows:
            return rows
        parsed = try_json(s)
        if parsed is not None:
            return parsed
        return {"_text": s}
    return data


def try_json(s: str):
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def extract_json_block(s: str):
    """从混杂文本里取出第一个完整的 JSON 对象。"""
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return try_json(s[start:i + 1])
    return None


def parse_custom_table(text: str) -> list:
    """解析官方自定义表格格式，形如：

    [160]{productName,energyKcal,protein,fat,carbohydrate,sodium,calcium}
    巨无霸,550,25.0,28.0,44.0,1020,150
    ...
    """
    head = re.search(r"\[(\d+)\]\{([^}]*)\}", text)
    if not head:
        return []
    fields = [f.strip() for f in head.group(2).split(",")]
    rows = []
    for line in text[head.end():].splitlines():
        line = line.strip()
        if not line or line.startswith("["):
            continue
        parts = line.split(",")
        if len(parts) < len(fields):
            continue
        row = {}
        for i, f in enumerate(fields):
            v = parts[i].strip()
            row[f] = to_number(v) if is_number(v) else v
        rows.append(row)
    return rows


def is_number(v: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(\.\d+)?", v))


def to_number(v: str):
    return float(v) if "." in v else int(v)
