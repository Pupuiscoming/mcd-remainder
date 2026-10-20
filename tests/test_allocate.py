"""分摊引擎单元测试（无需网络、无需 Token）。

运行： python tests/test_allocate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from allocate import (  # noqa: E402
    Line, PersonBill, SplitBill, Unit, allocate, apportion, settle,
)

passed = failed = 0


def check(name: str, cond: bool, detail: str = ""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


def eq(name: str, got, want):
    check(name, got == want, f"got={got} want={want}")


print("== apportion：最大余额法 ==")
r = apportion(3450, [23.5, 14.0, 9.5])
eq("三件套 34.50 按权重拆分后合计精确", sum(r), 3450)
eq("吃堡的人 1725 分", r[0], 1725)
eq("吃薯条的人 1028 分", r[1], 1028)
eq("喝可乐的人  697 分", r[2], 697)

r = apportion(100, [1, 1, 1])
eq("100 分三人均分合计精确", sum(r), 100)
eq("余数只多给一人", sorted(r), [33, 33, 34])

eq("空列表返回空", apportion(100, []), [])
eq("总额为 0 返回全 0", apportion(0, [1, 2]), [0, 0])
eq("权重全 0 退化为均分", sum(apportion(100, [0, 0, 0])), 100)

for total in (1, 7, 99, 12345, 999999):
    for w in ([1, 2, 3], [0.1, 0.2, 0.7], [5, 5], [1, 1, 1, 1, 1, 1, 1]):
        got = apportion(total, w)
        assert sum(got) == total, f"apportion({total},{w}) -> {got}"  # noqa: S101
check("随机组合下合计恒等于总额（35 组）", True)

print("== allocate：三件套三人分 ==")
bill = SplitBill(
    store_name="麦当劳合肥之心城餐厅",
    people=["A", "B", "C"],
    lines=[
        Line(
            no=1,
            product_code="9900005462",
            product_name="板烧鸡腿堡三件套",
            quantity=1,
            subtotal=3450,
            original_subtotal=4750,
            is_combo=True,
            units=[
                Unit(person="A", label="板烧鸡腿堡", basis=23.5, line_no=1),
                Unit(person="B", label="中薯条", basis=14.0, line_no=1),
                Unit(person="C", label="可乐中杯", basis=9.5, line_no=1),
            ],
        )
    ],
    subtotal=3450,
    payable=3450,
)
allocate(bill)
eq("A 应付 17.25", bill.bills["A"].total, 1725)
eq("B 应付 10.28", bill.bills["B"].total, 1028)
eq("C 应付  6.97", bill.bills["C"].total, 697)
eq("三人合计精确等于实付", sum(bill.bills[p].total for p in bill.people), 3450)
check("相比人均 11.50，吃堡的多付 5.75",
      bill.bills["A"].total - 1150 == 575)

print("== allocate：公共费与优惠 ==")
bill2 = SplitBill(
    people=["A", "B"],
    lines=[
        Line(no=1, product_code="x", product_name="双人餐", quantity=1,
             subtotal=6000, original_subtotal=8000, is_combo=True,
             units=[
                 Unit(person="A", label="堡", basis=40.0, line_no=1),
                 Unit(person="B", label="小食", basis=20.0, line_no=1),
             ]),
    ],
    subtotal=6000,
    discount=1000,     # 整单优惠 10 元
    packing=300,       # 打包费 3 元
    payable=5300,
)
allocate(bill2)
eq("A 食物 40.00", bill2.bills["A"].food, 4000)
eq("B 食物 20.00", bill2.bills["B"].food, 2000)
eq("公共费按食物比例：A 2.00", bill2.bills["A"].shared, 200)
eq("公共费按食物比例：B 1.00", bill2.bills["B"].shared, 100)
eq("优惠回摊：A 减 6.67", bill2.bills["A"].discount, 667)
eq("A 应付 35.33", bill2.bills["A"].total, 3533)
eq("B 应付 17.67", bill2.bills["B"].total, 1767)
eq("合计 = 实付 53.00", sum(bill2.bills[p].total for p in bill2.people), 5300)

bill2.shared_rule = "by_head"
allocate(bill2)
eq("切换按人头后公共费 A 1.50", bill2.bills["A"].shared, 150)

print("== settle：债务最小化 ==")
bill3 = SplitBill(people=["A", "B", "C"])
bill3.bills = {
    "A": PersonBill(name="A", total=2000, paid=6000),   # 垫付 60，应付 20，应收 40
    "B": PersonBill(name="B", total=3000, paid=0),      # 应付 30
    "C": PersonBill(name="C", total=1000, paid=0),      # 应付 10
}
ts = settle(bill3)
eq("转账笔数 2（≤ 人数-1）", len(ts), 2)
eq("转账总额 = 40.00", sum(t[2] for t in ts), 4000)
check("每笔付款人都是债务人", all(t[0] in ("B", "C") for t in ts))
check("收款人都是 A", all(t[1] == "A" for t in ts))

bill4 = SplitBill(people=["A", "B"])
bill4.bills = {"A": PersonBill(name="A", total=5000, paid=0),
               "B": PersonBill(name="B", total=0, paid=5000)}
ts = settle(bill4)
eq("两人场景只需 1 笔", len(ts), 1)
eq("金额 50.00", ts[0][2], 5000)

bill5 = SplitBill(people=["A", "B"])
bill5.bills = {"A": PersonBill(name="A", total=2500, paid=5000),
               "B": PersonBill(name="B", total=2500, paid=0)}
ts = settle(bill5)
eq("A 垫付全款时只需 1 笔", len(ts), 1)
eq("B 转给 A 25.00", ts[0], ("B", "A", 2500))

# 各自已付清自己的份额，无需转账
bill6 = SplitBill(people=["A", "B"])
bill6.bills = {"A": PersonBill(name="A", total=2500, paid=2500),
               "B": PersonBill(name="B", total=2500, paid=2500)}
ts = settle(bill6)
eq("各自付清时无需转账", len(ts), 0)

# 四舍五入后仍必须结清
bill7 = SplitBill(people=["A", "B", "C"])
bill7.bills = {"A": PersonBill(name="A", total=3334, paid=10000),
               "B": PersonBill(name="B", total=3333, paid=0),
               "C": PersonBill(name="C", total=3333, paid=0)}
ts = settle(bill7)
eq("含尾差时转账总额 = A 垫付 - A 应付", sum(t[2] for t in ts), 6666)

print(f"\n通过 {passed} 项，失败 {failed} 项")
raise SystemExit(1 if failed else 0)
