"""套餐原子化拆解：把「一个三件套」拆成「堡 / 薯条 / 可乐」三个可归属的子项。

麦当劳的销售单位大量是套餐，而拼单清算必须落到单品粒度——
A 吃堡、B 吃薯条、C 喝可乐，各付多少必须能算清楚。

关键技术点：
  query-meal-detail 返回 rounds（选配轮次），每轮有若干 choices，
  其中 isDefault=1 的是默认项，其余项带 diffPrice（相对默认项的差价）。
  因此只要默认项能在菜单里查到价格，任意换配都能精确定价：

      大薯条 = 中薯条(默认, ¥14) + diffPrice(+¥2) = ¥16

  这是通用 AA 计算器做不到的——它必须依赖麦当劳 MCP 的真实套餐结构。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from menu import MenuIndex


@dataclass
class ComboChild:
    """套餐拆解出的一个子项。"""

    round_id: int
    round_name: str
    code: str
    name: str
    qty: int = 1
    diff_price: float = 0.0      # 相对本轮默认项的差价
    unit_price: float = 0.0      # 估价（用于分摊的权重）
    price_src: str = "unknown"   # 估价来源，用于透明标注
    support_modify: bool = False

    @property
    def label(self) -> str:
        extra = ""
        if abs(self.diff_price) > 1e-9:
            sign = "+" if self.diff_price > 0 else "-"
            extra = f"({sign}¥{abs(self.diff_price):g})"
        return f"{self.name}{extra}"


@dataclass
class ComboInfo:
    code: str
    name: str
    children: list[ComboChild] = field(default_factory=list)
    total_basis: float = 0.0
    all_estimated: bool = False


DIFF_RE = re.compile(r"([+-]?)\s*[¥￥]?\s*(\d+(?:\.\d+)?)")


def parse_diff(text) -> float:
    """解析 diffPrice，形如 '+ ¥2.5' / '- ¥1' / '+¥0' / '¥2'。"""
    if text is None:
        return 0.0
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    m = DIFF_RE.search(s)
    if not m:
        return 0.0
    val = float(m.group(2))
    return -val if m.group(1) == "-" else val


def default_choice_of(round_node: dict):
    """取本轮默认项：优先 isDefault=1，否则取第一个。"""
    choices = round_node.get("choices") or []
    if not choices:
        return None
    for c in choices:
        if c.get("isDefault") == 1:
            return c
    return choices[0]


def price_of_choice(menu: MenuIndex, choice: dict):
    """查一个选项在菜单里的价格，返回 (价格, 来源)。查不到返回 (None, 'unknown')。"""
    code = str(choice.get("code", "")).strip()
    name = (choice.get("name", "") or "").strip()
    meal = menu.get(code) if code else None
    if meal and meal.unit_price > 0:
        return meal.unit_price, "menu_code"
    meal = menu.find_by_name(name)
    if meal and meal.unit_price > 0:
        return meal.unit_price, "menu_name"
    return None, "unknown"


def expand_combo(detail: dict, menu: MenuIndex,
                 selections: dict | None = None) -> ComboInfo:
    """把一个套餐拆成子项列表。

    selections: {round_id: choice_code}，指定某轮选哪个；
                未指定的轮次使用默认项。
    """
    selections = {int(k): str(v) for k, v in (selections or {}).items()}
    info = ComboInfo(code=str(detail.get("code", "")), name=detail.get("name", "") or "")

    unresolved: list[ComboChild] = []

    for rnd in detail.get("rounds") or []:
        rid = int(rnd.get("id", 0))
        rname = rnd.get("name", "") or f"第{rid}项"
        choices = rnd.get("choices") or []
        if not choices:
            continue

        # 本轮选中项
        picked = None
        if rid in selections:
            want = selections[rid]
            picked = next((c for c in choices if str(c.get("code")) == want), None)
        if picked is None:
            picked = default_choice_of(rnd)
        if picked is None:
            continue

        qty = int(picked.get("quantity") or 1) or 1

        # 默认项价格（作为基准）
        default = default_choice_of(rnd) or picked
        base_price, base_src = price_of_choice(menu, default)

        diff = parse_diff(picked.get("diffPrice"))

        if base_price:
            price = round(base_price + diff, 2)
            src = base_src if abs(diff) < 1e-9 else f"{base_src}+diff"
        else:
            price = 0.0
            src = "unknown"

        child = ComboChild(
            round_id=rid,
            round_name=rname,
            code=str(picked.get("code", "")),
            name=picked.get("name", "") or "",
            qty=qty,
            diff_price=diff,
            unit_price=price,
            price_src=src,
            support_modify=bool(picked.get("supportModify")),
        )
        info.children.append(child)
        if src == "unknown":
            unresolved.append(child)

    # 兜底：完全查不到价的子项，按已估价子项的均值补齐，保证比例可用
    if unresolved:
        known = [c for c in info.children if c.price_src != "unknown"]
        if known:
            avg = sum(c.unit_price for c in known) / len(known)
        else:
            avg = 1.0
        for c in unresolved:
            c.unit_price = round(avg, 2)
            c.price_src = "estimated_avg"

    info.total_basis = sum(c.unit_price * c.qty for c in info.children)
    info.all_estimated = all(c.price_src == "estimated_avg" for c in info.children)
    return info
