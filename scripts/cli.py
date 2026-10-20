"""McRemainder（AA 除不尽）命令行入口。

用法：
    python scripts/cli.py --demo                      # 在线跑内置示例
    python scripts/cli.py --spec plan.json            # 按自己的拼单方案清算
    python scripts/cli.py --demo --card card.html     # 额外生成可分享的清算卡
    python scripts/cli.py --demo --json out.json      # 导出结构化结果

需要环境变量 MCD_MCP_TOKEN（未设置时自动读取 ~/.workbuddy/mcp.json）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from allocate import fmt  # noqa: E402
from card import render_card  # noqa: E402
from plan import ItemSpec, PlanSpec, build_bill  # noqa: E402
from mcd_client import McdClient, McpError  # noqa: E402

DEMO_SPEC = {
    "city": "合肥",
    "keyword": "之心城",
    "people": ["阿强", "小美", "老张"],
    "payer": "阿强",
    "shared_rule": "by_amount",
    "items": [
        {
            "code": "9900005462",
            "qty": 1,
            "share": [
                {"person": "阿强", "part": "板烧鸡腿堡"},
                {"person": "小美", "part": "中薯条"},
                {"person": "老张", "part": "可乐"},
            ],
        },
        {
            "code": "515837",
            "qty": 2,
            "share": [
                {"person": "小美", "qty": 1},
                {"person": "老张", "qty": 1},
            ],
        },
    ],
}


def spec_from_dict(d: dict) -> PlanSpec:
    items = [ItemSpec(code=str(i["code"]), qty=int(i.get("qty", 1)),
                      share=i.get("share", []), selections=i.get("selections", {}))
             for i in d.get("items", [])]
    return PlanSpec(
        people=d.get("people", []),
        items=items,
        city=d.get("city", ""),
        keyword=d.get("keyword", ""),
        store_code=str(d.get("store_code", "")),
        shared_rule=d.get("shared_rule", "by_amount"),
        payer=d.get("payer", ""),
    )


def print_bill(bill) -> None:
    print(f"\n门店：{bill.store_name}")
    print(f"实付：{fmt(bill.payable)}"
          f"（商品 {fmt(bill.subtotal)} + 打包 {fmt(bill.packing)}"
          f" + 配送 {fmt(bill.delivery)} + 餐具 {fmt(bill.tableware)}"
          f" - 优惠 {fmt(bill.discount)}）\n")

    for line in bill.lines:
        tag = "套餐" if line.is_combo else "单品"
        print(f"  [{tag}] {line.product_name} ×{line.quantity}  {fmt(line.subtotal)}")
        for u in line.units:
            flag = "" if u.price_src in ("menu_code", "menu_name", "menu") else "  ⚠ 估价"
            print(f"        {u.person:<6s}{u.label:<14s}权重 ¥{u.basis:>6.2f}{flag}")
    print()

    print(f"  {'成员':<8s}{'食物':>9s}{'公共':>9s}{'优惠':>9s}{'应付':>10s}{'热量':>10s}")
    for p in bill.people:
        b = bill.bills[p]
        print(f"  {p:<8s}{fmt(b.food):>9s}{fmt(b.shared):>9s}"
              f"{'-' + fmt(b.discount):>9s}{fmt(b.total):>10s}{b.kcal:>8.0f} kcal")

    total = sum(bill.bills[p].total for p in bill.people)
    print(f"\n  校验：{fmt(total)} vs 实付 {fmt(bill.payable)}"
          f"  {'✓ 分毫不差' if total == bill.payable else '✗ 不一致'}")

    print(f"\n  结算方案（{len(bill.transfers)} 笔转账）：")
    for a, b, c in bill.transfers:
        print(f"    {a} → {b}  {fmt(c)}")
    if not bill.transfers:
        print("    无需转账")


def bill_to_dict(bill) -> dict:
    return {
        "store": bill.store_name,
        "payable_cents": bill.payable,
        "discount_cents": bill.discount,
        "lines": [
            {
                "product_code": l.product_code,
                "product_name": l.product_name,
                "quantity": l.quantity,
                "is_combo": l.is_combo,
                "subtotal_cents": l.subtotal,
                "units": [{"person": u.person, "label": u.label,
                           "qty": u.qty, "basis": u.basis,
                           "price_src": u.price_src, "amount_cents": u.amount}
                          for u in l.units],
            }
            for l in bill.lines
        ],
        "people": [
            {"name": p, "food_cents": bill.bills[p].food,
             "shared_cents": bill.bills[p].shared,
             "discount_cents": bill.bills[p].discount,
             "total_cents": bill.bills[p].total,
             "paid_cents": bill.bills[p].paid,
             "kcal": bill.bills[p].kcal}
            for p in bill.people
        ],
        "transfers": [{"from": a, "to": b, "cents": c} for a, b, c in bill.transfers],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="McRemainder · AA 除不尽：麦当劳拼单清算")
    ap.add_argument("--spec", help="拼单方案 JSON 文件")
    ap.add_argument("--demo", action="store_true", help="使用内置示例（在线调 MCP）")
    ap.add_argument("--card", help="生成 HTML 清算卡到指定路径")
    ap.add_argument("--json", dest="json_out", help="导出结构化结果 JSON")
    ap.add_argument("--repo", default="", help="清算卡底部展示的仓库地址")
    args = ap.parse_args()

    if args.spec:
        spec = spec_from_dict(json.loads(Path(args.spec).read_text(encoding="utf-8")))
    elif args.demo:
        spec = spec_from_dict(DEMO_SPEC)
    else:
        ap.print_help()
        return 1

    try:
        client = McdClient()
    except McpError as e:
        print(f"错误：{e}")
        return 1

    try:
        bill = build_bill(client, spec)
    except McpError as e:
        print(f"MCP 调用失败：{e}")
        return 1

    print_bill(bill)

    if args.card:
        out = Path(args.card)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_card(bill, repo_url=args.repo), encoding="utf-8")
        print(f"\n清算卡已生成：{out}")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bill_to_dict(bill), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"结构化结果已导出：{out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
