"""从麦当劳 MCP 预拉取数据快照，供零门槛 Demo 与离线模式使用。

运行： python scripts/snapshot.py [--city 合肥] [--keyword 之心城] [--out data/snapshot.json]

产出结构：
{
  "store_code": "3500158",
  "store_name": "麦当劳合肥之心城餐厅",
  "generated_at": "...",
  "meals":     {code: {name, current_price, original_price, image}},
  "nutrition": [{productName, energyKcal, ...}],
  "combos":    {code: {name, current_price, children: [{code, name, unit_price, price_src, diff_price, round_name}]}}
}
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from expand import expand_combo  # noqa: E402
from menu import menu_from_mcp, nutrition_index  # noqa: E402
from mcd_client import McdClient, McpError  # noqa: E402
from plan import looks_like_combo  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="合肥")
    ap.add_argument("--keyword", default="之心城")
    ap.add_argument("--store", default="", help="直接指定 storeCode")
    ap.add_argument("--out", default=str(ROOT / "data" / "snapshot.json"))
    args = ap.parse_args()

    client = McdClient()

    if args.store:
        store = {"storeCode": args.store, "storeName": f"门店 {args.store}"}
    else:
        stores = client.call("query-nearby-stores", {
            "beType": 1, "searchType": 2, "city": args.city, "keyword": args.keyword,
        })
        store = stores[0] if isinstance(stores, list) and stores else stores
    store_code = str(store.get("storeCode"))
    store_name = store.get("storeName", "")
    print(f"门店：{store_name} ({store_code})")

    raw_menu = client.call("query-meals",
                           {"storeCode": store_code, "orderType": 1, "beType": 1})
    menu = menu_from_mcp(raw_menu, store_code, store_name)
    print(f"菜单：{len(menu.meals)} 个餐品")

    nut_rows = client.call("list-nutrition-foods", {})
    nut_idx = nutrition_index(nut_rows)
    print(f"营养：{len(nut_rows)} 条")

    # 对疑似套餐逐个拉详情并预展开
    combos = {}
    combo_codes = [code for code, m in menu.meals.items()
                   if looks_like_combo(m.name, []) and m.name]
    print(f"疑似套餐 {len(combo_codes)} 个，逐个拆解…")
    for i, code in enumerate(combo_codes, 1):
        try:
            detail = client.call("query-meal-detail", {
                "storeCode": store_code, "orderType": 1, "beType": 1, "code": code,
            })
        except McpError as e:
            print(f"  [{i}/{len(combo_codes)}] {code} 失败：{e}")
            continue
        rounds = detail.get("rounds") if isinstance(detail, dict) else None
        if not rounds:
            continue
        combo = expand_combo(detail, menu)
        meal = menu.get(code)
        combos[str(code)] = {
            "name": combo.name,
            "current_price": meal.current_price if meal else 0.0,
            "original_price": meal.original_price if meal else 0.0,
            "children": [
                {"code": c.code, "name": c.name, "unit_price": c.unit_price,
                 "price_src": c.price_src, "diff_price": c.diff_price,
                 "round_name": c.round_name}
                for c in combo.children
            ],
        }
        print(f"  [{i}/{len(combo_codes)}] {combo.name} → {len(combo.children)} 个子项")

    snap = {
        "store_code": store_code,
        "store_name": store_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meals": {
            code: {"name": m.name, "current_price": m.current_price,
                   "original_price": m.original_price, "image": m.image}
            for code, m in menu.meals.items()
        },
        "nutrition": nut_rows,
        "combos": combos,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n快照已保存：{out}（{out.stat().st_size/1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
