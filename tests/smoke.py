"""链路冒烟测试：初始化 → 工具列表 → 门店 → 菜单 → 套餐拆解 → 核价。

运行：  python tests/smoke.py
需要：  环境变量 MCD_MCP_TOKEN（未设置时自动从 ~/.workbuddy/mcp.json 读取）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from mcd_client import McdClient, McpError  # noqa: E402

STORE = "3500158"          # 麦当劳合肥之心城餐厅
COMBO = "9900005462"       # 板烧鸡腿堡三件套


def load_token() -> str:
    if os.environ.get("MCD_MCP_TOKEN"):
        return os.environ["MCD_MCP_TOKEN"].strip()
    cfg = Path.home() / ".workbuddy" / "mcp.json"
    if cfg.exists():
        data = json.loads(cfg.read_text(encoding="utf-8"))
        node = data.get("mcpServers", {}).get("mcd-mcp", {})
        headers = node.get("headers", {})
        auth = headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
    return ""


def main() -> int:
    token = load_token()
    if not token:
        print("未找到 MCP Token，请先设置 MCD_MCP_TOKEN")
        return 1

    client = McdClient(token=token)
    ok = 0

    print("== 1. initialize ==")
    try:
        info = client.initialize()
        name = info.get("serverInfo", {}).get("name", "?")
        print(f"   OK  服务端: {name}  session: {'已建立' if client.session_id else '无'}")
        ok += 1
    except McpError as e:
        print(f"   FAIL {e}")
        return 1

    print("== 2. tools/list ==")
    try:
        tools = client.list_tools()
        print(f"   OK  工具数: {len(tools)}")
        ok += 1
    except McpError as e:
        print(f"   FAIL {e}")
        tools = []

    print("== 3. query-nearby-stores ==")
    try:
        stores = client.call("query-nearby-stores",
                             {"beType": 1, "searchType": 2, "city": "合肥", "keyword": "之心城"})
        first = stores[0] if isinstance(stores, list) and stores else stores
        print(f"   OK  {first.get('storeName')} / {first.get('storeCode')}")
        ok += 1
    except McpError as e:
        print(f"   FAIL {e}")
        return 1

    print("== 4. query-meals ==")
    try:
        meals = client.call("query-meals", {"storeCode": STORE, "orderType": 1, "beType": 1})
        menu = meals.get("meals", {}) if isinstance(meals, dict) else {}
        cats = meals.get("categories", []) if isinstance(meals, dict) else []
        print(f"   OK  分类 {len(cats)} 个，餐品 {len(menu)} 个")
        ok += 1
    except McpError as e:
        print(f"   FAIL {e}")
        menu = {}

    print("== 5. query-meal-detail（套餐拆解，本项目核心）==")
    try:
        detail = client.call("query-meal-detail",
                             {"storeCode": STORE, "orderType": 1, "beType": 1, "code": COMBO})
        rounds = detail.get("rounds", []) if isinstance(detail, dict) else []
        print(f"   OK  {detail.get('name')} 共 {len(rounds)} 个选配轮次")
        for r in rounds:
            defaults = [c["name"] for c in r.get("choices", []) if c.get("isDefault") == 1]
            print(f"       round{r.get('id')} {r.get('name')}: 默认 {defaults} "
                  f"（可选 {len(r.get('choices', []))} 项）")
        ok += 1
    except McpError as e:
        print(f"   FAIL {e}")
        return 1

    print("== 6. calculate-price ==")
    try:
        price = client.call("calculate-price", {
            "storeCode": STORE, "orderType": 1, "beType": 1,
            "items": [{"productCode": COMBO, "quantity": 1},
                      {"productCode": "515837", "quantity": 2}],
        })
        print(f"   OK  原价 {price.get('originalPrice')} 分 / 实付 {price.get('price')} 分 "
              f"/ 优惠 {price.get('discount')} 分")
        for it in price.get("productList", []):
            print(f"       {it.get('productName')} x{it.get('quantity')}: {it.get('subtotal')} 分")
        ok += 1
    except McpError as e:
        print(f"   FAIL {e}")
        return 1

    print("== 7. list-nutrition-foods（自定义表格格式）==")
    try:
        nut = client.call("list-nutrition-foods", {})
        n = len(nut) if isinstance(nut, list) else 0
        sample = nut[0] if n else {}
        print(f"   OK  营养条目 {n} 条，样例字段: {list(sample.keys())[:6]}")
        ok += 1
    except McpError as e:
        print(f"   FAIL {e}")

    print(f"\n通过 {ok}/7 项")
    return 0 if ok >= 6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
