"""拼单分摊引擎。

分摊规则（这是本项目的核心算法，也是普通 AA 做不到的事）：

1. 行内比例分摊
   麦当劳按「行」计价（calculate-price 返回 productList[].subtotal）。
   一行可能是一个套餐（三件套 ¥34.5），也可能是 N 个单品。
   行内按各归属单位的「原价权重」比例分摊实付金额，
   而不是把行金额简单除以人数。
      例：堡 23.5 / 薯条 14 / 可乐 9.5，权重和 47，行实付 34.5
         吃堡的人付 34.5 × 23.5/47 = 17.25

2. 公共费分摊
   打包费 / 配送费 / 餐具费不属于任何一个人的食物，
   默认按各人食物金额比例分摊，可切换为按人头平分。

3. 整单优惠回摊
   calculate-price 的 discount 是整单优惠，按各人食物金额比例回摊，
   确保没有人白占优惠便宜。

4. 尾差处理
   全程用「分」为单位的整数计算，最后用最大余额法（Hare quota）
   把余数分给小数部分最大的人，保证各人金额之和精确等于实付金额。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Unit:
    """一个可归属单位：某个人分到的一份食物。"""

    person: str
    label: str
    code: str = ""
    qty: float = 1.0
    basis: float = 0.0       # 单价权重（元，仅用于计算比例）
    price_src: str = "menu"
    line_no: int = 0
    amount: int = 0          # 分摊结果（分）


@dataclass
class Line:
    no: int
    product_code: str
    product_name: str
    quantity: int
    subtotal: int            # 该行实付（分）
    original_subtotal: int   # 该行原价（分）
    is_combo: bool = False
    units: list[Unit] = field(default_factory=list)


@dataclass
class PersonBill:
    name: str
    units: list[Unit] = field(default_factory=list)
    food: int = 0            # 食物应付（分）
    shared: int = 0          # 公共费分摊（分）
    discount: int = 0        # 优惠抵扣（分，正数表示少付多少）
    total: int = 0           # 实际应付（分）
    paid: int = 0            # 已垫付（分）
    kcal: float = 0.0

    @property
    def net(self) -> int:
        """净额：>0 应收（别人欠他），<0 应付（他欠别人）。"""
        return self.paid - self.total


@dataclass
class SplitBill:
    store_name: str = ""
    people: list[str] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    bills: dict[str, PersonBill] = field(default_factory=dict)
    subtotal: int = 0        # 商品合计（分）
    discount: int = 0        # 整单优惠（分）
    packing: int = 0         # 打包费（分）
    delivery: int = 0        # 配送费（分）
    tableware: int = 0       # 餐具费（分）
    payable: int = 0         # 实付合计（分）
    shared_rule: str = "by_amount"
    estimated: bool = False  # 是否存在估价（非菜单精确价）


def apportion(total: int, weights: list[float]) -> list[int]:
    """按权重把 total（分）拆成整数分列表，保证求和精确等于 total。

    使用最大余额法：先取下整，再把余数按小数部分从大到小分配。
    """
    n = len(weights)
    if n == 0:
        return []
    if total == 0:
        return [0] * n

    s = sum(weights)
    if s <= 0:
        base = total // n
        out = [base] * n
        out[0] += total - sum(out)
        return out

    raw = [total * w / s for w in weights]
    floors = [int(x) for x in raw]
    remainder = total - sum(floors)
    if remainder > 0:
        order = sorted(range(n), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
        for k in range(remainder):
            floors[order[k % n]] += 1
    return floors


def allocate(bill: SplitBill) -> SplitBill:
    """执行分摊，原地填充各人的 food / shared / discount / total。"""
    people = bill.people

    # ---------- 1. 行内比例分摊 ----------
    for line in bill.lines:
        weights = [u.basis * u.qty for u in line.units]
        # 权重缺失时退化为按份数平分
        if sum(weights) <= 0:
            weights = [u.qty for u in line.units]
        shares = apportion(line.subtotal, weights)
        for u, amt in zip(line.units, shares):
            u.amount = amt

    for name in people:
        b = bill.bills.setdefault(name, PersonBill(name=name))
        b.units = [u for line in bill.lines for u in line.units if u.person == name]
        b.food = sum(u.amount for u in b.units)

    # ---------- 2. 公共费分摊 ----------
    shared_total = bill.packing + bill.delivery + bill.tableware
    if shared_total > 0:
        if bill.shared_rule == "by_head":
            weights = [1.0] * len(people)
        else:
            weights = [max(bill.bills[p].food, 0) for p in people]
            if sum(weights) <= 0:
                weights = [1.0] * len(people)
        shares = apportion(shared_total, weights)
        for p, amt in zip(people, shares):
            bill.bills[p].shared = amt

    # ---------- 3. 整单优惠回摊 ----------
    if bill.discount > 0:
        weights = [max(bill.bills[p].food, 0) for p in people]
        if sum(weights) <= 0:
            weights = [1.0] * len(people)
        shares = apportion(bill.discount, weights)
        for p, amt in zip(people, shares):
            bill.bills[p].discount = amt

    # ---------- 4. 汇总 ----------
    for p in people:
        b = bill.bills[p]
        b.total = b.food + b.shared - b.discount

    bill.estimated = any(
        u.price_src in ("estimated_avg", "unknown")
        for line in bill.lines for u in line.units
    )
    return bill


def settle(bill: SplitBill) -> list[tuple[str, str, int]]:
    """债务最小化清算：把「每人应付」压缩成最少的转账笔数。

    N 个人最多 N-1 笔转账即可结清。
    返回 [(付款人, 收款人, 金额分), ...]
    """
    debtors = []   # (人, 待付金额)  净额为负
    creditors = []  # (人, 待收金额) 净额为正
    for p in bill.people:
        net = bill.bills[p].net
        if net < 0:
            debtors.append([p, -net])
        elif net > 0:
            creditors.append([p, net])

    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)

    transfers: list[tuple[str, str, int]] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        dp, damt = debtors[i]
        cp, camt = creditors[j]
        pay = min(damt, camt)
        if pay > 0:
            transfers.append((dp, cp, pay))
        debtors[i][1] -= pay
        creditors[j][1] -= pay
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return transfers


def yuan(cents: int) -> float:
    return round(cents / 100.0, 2)


def fmt(cents: int) -> str:
    return f"¥{cents / 100.0:.2f}"
