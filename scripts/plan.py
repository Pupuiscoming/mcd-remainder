"""把麦当劳 MCP 真实数据组装成分摊账单。

完整调用链（本项目共用到 9 个 MCP 工具）：
  query-nearby-stores   → 定位门店
  query-meals           → 真实菜单与价格（子项估价的基准）
  query-meal-detail     → 套餐拆解（核心）
  query-store-coupons   → 门店可用券
  query-my-coupons      → 卡包里已有的券
  available-coupons     → 还能领的券
  calculate-price       → 真实核价（含优惠/打包费/配送费/餐具费）
  list-nutrition-foods  → 每人的热量账单
  query-my-account      → 积分归属提示
"""

from __future__ import annotations

from dataclasses import dataclass, field

from allocate import Line, SplitBill, Unit, allocate, settle
from expand import expand_combo
from menu import (
    match_nutrition, menu_from_mcp, menu_from_snapshot, nutrition_index,
)

COMBO_HINTS = ("件套", "套餐", "双人餐", "分享餐", "随心配", "随心拼", "四宫格", "拼盘", "亲子餐")


@dataclass
class ItemSpec:
    """一行订单。"""

    code: str
    qty: int = 1
    share: list[dict] = field(default_factory=list)  # [{person, part/qty}]
    selections: dict = field(default_factory=dict)   # 套餐换配 {round_id: choice_code}


@dataclass
class PlanSpec:
    people: list[str]
    items: list[ItemSpec]
    city: str = ""
    keyword: str = ""
    store_code: str = ""
    shared_rule: str = "by_amount"
    payer: str = ""


def looks_like_combo(name: str, tags: list) -> bool:
    text = (name or "") + " " + " ".join(tags or [])
    return any(h in text for h in COMBO_HINTS)


def resolve_store(client, spec: PlanSpec) -> dict:
    if spec.store_code:
        return {"storeCode": spec.store_code, "storeName": "指定门店"}
    data = client.call("query-nearby-stores", {
        "beType": 1, "searchType": 2, "city": spec.city, "keyword": spec.keyword,
    })
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError("未找到门店，请检查 city / keyword")


def build_bill(client, spec: PlanSpec, offline_snapshot: dict | None = None) -> SplitBill:
    """端到端：门店 → 菜单 → 拆解 → 核价 → 分摊 → 清算。"""
    if offline_snapshot is not None:
        menu = menu_from_snapshot(offline_snapshot)
        store = {"storeCode": menu.store_code, "storeName": menu.store_name}
        nut = nutrition_index(offline_snapshot.get("nutrition") or [])
    else:
        store = resolve_store(client, spec)
        store_code = str(store.get("storeCode", ""))
        raw_menu = client.call("query-meals",
                               {"storeCode": store_code, "orderType": 1, "beType": 1})
        menu = menu_from_mcp(raw_menu, store_code, store.get("storeName", ""))
        nut = nutrition_index(client.call("list-nutrition-foods", {}))

    bill = SplitBill(
        store_name=store.get("storeName", ""),
        people=list(spec.people),
        shared_rule=spec.shared_rule,
    )
    # ---------- 拆解每一行 ----------
    pending_lines: list[Line] = []
    for idx, item in enumerate(spec.items, start=1):
        meal = menu.get(item.code)
        name = meal.name if meal else item.code
        is_combo = looks_like_combo(name, getattr(meal, "tags", []) or [])

        if is_combo and offline_snapshot is None:
            detail = client.call("query-meal-detail", {
                "storeCode": menu.store_code, "orderType": 1, "beType": 1, "code": item.code,
            })
            rounds = detail.get("rounds") if isinstance(detail, dict) else None
            if rounds:
                combo = expand_combo(detail, menu, item.selections)
                units = _units_from_combo(combo, item, bill.people, idx)
            else:
                units = _units_flat(meal, item, bill.people, idx, name)
        elif is_combo and offline_snapshot is not None:
            snap_combo = (offline_snapshot.get("combos") or {}).get(str(item.code))
            if snap_combo:
                units = _units_from_snapshot(snap_combo, item, bill.people, idx)
            else:
                units = _units_flat(meal, item, bill.people, idx, name)
        else:
            units = _units_flat(meal, item, bill.people, idx, name)

        pending_lines.append(Line(
            no=idx,
            product_code=str(item.code),
            product_name=name,
            quantity=item.qty,
            subtotal=0,
            original_subtotal=0,
            is_combo=is_combo,
            units=units,
        ))

    # ---------- 真实核价 ----------
    if offline_snapshot is None:
        price = client.call("calculate-price", {
            "storeCode": menu.store_code, "orderType": 1, "beType": 1,
            "items": [{"productCode": str(it.code), "quantity": it.qty} for it in spec.items],
        })
        plist = price.get("productList") or []
        by_code = {str(p.get("productCode")): p for p in plist}
        bill.subtotal = int(price.get("productPrice") or 0)
        bill.discount = int(price.get("discount") or 0)
        bill.packing = int(price.get("packingPrice") or 0)
        bill.delivery = int(price.get("deliveryPrice") or 0)
        bill.tableware = int(price.get("tablewarePrice") or 0)
        bill.payable = int(price.get("price") or 0)
        for line in pending_lines:
            p = by_code.get(line.product_code)
            if p:
                line.subtotal = int(p.get("subtotal") or 0)
                line.original_subtotal = int(p.get("originalSubtotal") or 0)
    else:
        # 离线模式：用快照里的菜单价估算，并明确标记未核实
        for line in pending_lines:
            meal = menu.get(line.product_code)
            unit = meal.current_price if meal else 0.0
            line.subtotal = int(round(unit * line.quantity * 100))
            line.original_subtotal = int(round((meal.original_price or unit) * line.quantity * 100))
        bill.subtotal = sum(l.subtotal for l in pending_lines)
        bill.payable = bill.subtotal
        bill._price_unverified = True  # type: ignore[attr-defined]

    bill.lines = pending_lines

    # ---------- 分摊 ----------
    bill.bills = {}
    allocate(bill)

    # ---------- 热量归属 ----------
    for p in bill.people:
        kcal = 0.0
        for u in bill.bills[p].units:
            rec = match_nutrition(nut, u.label.split("(")[0].strip())
            if rec:
                kcal += rec.get("kcal", 0.0) * u.qty
        bill.bills[p].kcal = round(kcal, 1)

    # ---------- 垫付与清算 ----------
    payer = spec.payer or bill.people[0]
    if payer in bill.bills:
        bill.bills[payer].paid = bill.payable
    bill.transfers = settle(bill)  # type: ignore[attr-defined]
    bill.payer = payer  # type: ignore[attr-defined]
    return bill


def _units_from_combo(combo, item: ItemSpec, people: list[str], line_no: int) -> list[Unit]:
    """把套餐子项按 share 配置归属到人。"""
    units: list[Unit] = []
    # 建立 子项 → 归属人 的映射：按 part 名称模糊匹配
    shares = item.share or []
    leftover_qty = float(item.qty)

    for child in combo.children:
        holders: list[tuple[str, float]] = []
        for s in shares:
            person = s.get("person", "")
            part = (s.get("part") or "").strip()
            if not part:
                continue
            if part in child.name or child.name in part or part in child.round_name:
                holders.append((person, 1.0))
        if not holders:
            # 没指定归属 → 记到第一个人（后续可交互调整），并标注未分配
            holders = [(people[0], 1.0)] if people else []
        for person, frac in holders:
            units.append(Unit(
                person=person,
                label=child.label,
                code=child.code,
                qty=frac * item.qty,
                basis=child.unit_price,
                price_src=child.price_src,
                line_no=line_no,
            ))
        leftover_qty = 0.0
    return units


def _units_flat(meal, item: ItemSpec, people: list[str], line_no: int, fallback_name: str) -> list[Unit]:
    """单品行：按份数分给人。"""
    unit_price = meal.unit_price if meal else 0.0
    name = meal.name if meal else fallback_name
    shares = item.share or []
    units: list[Unit] = []
    assigned = 0.0
    for s in shares:
        q = float(s.get("qty") or 0)
        if q <= 0:
            continue
        units.append(Unit(person=s.get("person", ""), label=name,
                          code=str(item.code), qty=q, basis=unit_price, line_no=line_no))
        assigned += q
    rest = float(item.qty) - assigned
    if rest > 1e-9 and people:
        units.append(Unit(person=people[0], label=name, code=str(item.code),
                          qty=rest, basis=unit_price, line_no=line_no))
    if not units and people:
        units.append(Unit(person=people[0], label=name, code=str(item.code),
                          qty=float(item.qty), basis=unit_price, line_no=line_no))
    return units


def _units_from_snapshot(snap_combo: dict, item: ItemSpec, people: list[str], line_no: int) -> list[Unit]:
    """离线模式：用快照里预展开的套餐结构。"""
    units: list[Unit] = []
    for child in snap_combo.get("children") or []:
        cname = child.get("name", "")
        holders = [(s.get("person", ""), 1.0) for s in (item.share or [])
                   if (s.get("part") or "") and ((s.get("part") in cname) or (cname in s.get("part")))]
        if not holders:
            holders = [(people[0], 1.0)] if people else []
        for person, frac in holders:
            units.append(Unit(
                person=person, label=cname, code=str(child.get("code", "")),
                qty=frac * item.qty, basis=float(child.get("unit_price") or 0),
                price_src=child.get("price_src", "snapshot"), line_no=line_no,
            ))
    return units
