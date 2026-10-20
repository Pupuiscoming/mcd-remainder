"""端到端测试：用真实 MCP 数据跑一次完整的拼单清算。

运行： python tests/e2e.py
场景：三个人拼一个板烧鸡腿堡三件套 + 两个圆筒冰淇淋
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from mcd_client import McdClient  # noqa: E402
from plan import ItemSpec, PlanSpec, build_bill  # noqa: E402
from allocate import fmt  # noqa: E402


def load_token() -> str:
    import os
    if os.environ.get("MCD_MCP_TOKEN"):
        return os.environ["MCD_MCP_TOKEN"].strip()
    cfg = Path.home() / ".workbuddy" / "mcp.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    return data["mcpServers"]["mcd-mcp"]["headers"]["Authorization"][7:].strip()


def main() -> int:
    spec = PlanSpec(
        people=["阿强", "小美", "老张"],
        city="合肥",
        keyword="之心城",
        payer="阿强",
        items=[
            ItemSpec(
                code="9900005462",          # 板烧鸡腿堡三件套
                qty=1,
                share=[
                    {"person": "阿强", "part": "板烧鸡腿堡"},
                    {"person": "小美", "part": "中薯条"},
                    {"person": "老张", "part": "可乐"},
                ],
            ),
            ItemSpec(
                code="515837",              # 圆筒冰淇淋
                qty=2,
                share=[
                    {"person": "小美", "qty": 1},
                    {"person": "老张", "qty": 1},
                ],
            ),
        ],
    )

    client = McdClient(token=load_token())
    bill = build_bill(client, spec)

    print(f"门店：{bill.store_name}")
    print(f"实付合计：{fmt(bill.payable)}（商品 {fmt(bill.subtotal)}"
          f" + 打包 {fmt(bill.packing)} + 配送 {fmt(bill.delivery)}"
          f" + 餐具 {fmt(bill.tableware)} - 优惠 {fmt(bill.discount)}）")
    print()

    for line in bill.lines:
        tag = "套餐" if line.is_combo else "单品"
        print(f"[{tag}] {line.product_name} x{line.quantity}  {fmt(line.subtotal)}")
        for u in line.units:
            print(f"        {u.person:4s} {u.label:12s} 权重 ¥{u.basis:>6.2f}  [{u.price_src}]")
    print()

    print("== 每人账单 ==")
    for p in bill.people:
        b = bill.bills[p]
        print(f"{p:4s}  食物 {fmt(b.food):>8s}  公共 {fmt(b.shared):>7s}"
              f"  优惠 -{fmt(b.discount):>7s}  应付 {fmt(b.total):>8s}"
              f"  已付 {fmt(b.paid):>8s}  {b.kcal:>6.0f} kcal")
    print()

    total = sum(bill.bills[p].total for p in bill.people)
    print(f"校验：各人应付合计 {fmt(total)} vs 实付 {fmt(bill.payable)}"
          f"  {'OK' if total == bill.payable else 'MISMATCH'}")
    print()

    print("== 转账方案（最少笔数）==")
    for payer, payee, cents in bill.transfers:
        print(f"  {payer} → {payee}  {fmt(cents)}")
    if not bill.transfers:
        print("  无需转账")

    ok = (total == bill.payable)
    print(f"\n{'端到端通过' if ok else '端到端失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
