"""菜单与套餐数据的加载、缓存与快照。

在线模式：直接调 MCP（query-meals / query-meal-detail）
离线模式：读 data/snapshot.json（由 scripts/snapshot.py 从 MCP 预拉取生成）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "snapshot.json"

SPEC_WORDS = ("大杯", "中杯", "小杯", "大", "中", "小", "热", "冰", "（冰/热）", "(冰/热)")


@dataclass
class Meal:
    code: str
    name: str
    current_price: float
    original_price: float
    image: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def unit_price(self) -> float:
        """用于分摊的估价：优先原价（未打折的真实价值），缺失时退回现价。"""
        return self.original_price or self.current_price


@dataclass
class MenuIndex:
    store_code: str
    store_name: str
    meals: dict[str, Meal] = field(default_factory=dict)

    def get(self, code: str) -> Meal | None:
        return self.meals.get(str(code))

    def find_by_name(self, name: str) -> Meal | None:
        """按名称匹配套餐子项到菜单单品。

        套餐子项（如「可乐中杯」「中薯条」）的 code 常常和菜单单品
        （如「可乐」「薯条」）不一致，需要按名称回查。
        """
        if not name:
            return None
        exact = [m for m in self.meals.values() if m.name == name]
        if exact:
            return min(exact, key=lambda m: m.current_price)

        base = strip_spec(name)
        if not base:
            return None
        # 去掉规格词后完全相等
        exact2 = [m for m in self.meals.values() if strip_spec(m.name) == base]
        if exact2:
            return min(exact2, key=lambda m: abs(m.current_price))
        # 包含关系（取最短名称，避免「双层吉士汉堡」被「巨无霸」误伤）
        cands = [m for m in self.meals.values()
                 if base and (base in m.name or m.name in base)]
        if cands:
            return min(cands, key=lambda m: (len(m.name), m.current_price))
        return None


def strip_spec(name: str) -> str:
    s = (name or "").strip()
    for w in SPEC_WORDS:
        s = s.replace(w, "")
    s = re.sub(r"[【】\[\]()（）\s]+", "", s)
    return s


def menu_from_mcp(data: dict, store_code: str = "", store_name: str = "") -> MenuIndex:
    """把 query-meals 的返回解析成 MenuIndex。"""
    idx = MenuIndex(store_code=str(store_code), store_name=store_name)
    raw_meals = (data or {}).get("meals") or {}
    for code, m in raw_meals.items():
        if not isinstance(m, dict):
            continue
        idx.meals[str(code)] = Meal(
            code=str(code),
            name=m.get("name", "") or "",
            current_price=to_float(m.get("currentPrice")),
            original_price=to_float(m.get("originalPrice")),
            image=m.get("image", "") or "",
        )
    return idx


def to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_snapshot(path: Path | str = SNAPSHOT) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"快照不存在：{p}\n请先运行 python scripts/snapshot.py 从 MCP 预拉取数据"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def menu_from_snapshot(snap: dict) -> MenuIndex:
    idx = MenuIndex(
        store_code=str(snap.get("store_code", "")),
        store_name=str(snap.get("store_name", "")),
    )
    for code, m in (snap.get("meals") or {}).items():
        idx.meals[str(code)] = Meal(
            code=str(code),
            name=m.get("name", "") or "",
            current_price=to_float(m.get("current_price")),
            original_price=to_float(m.get("original_price")),
            image=m.get("image", "") or "",
        )
    return idx


def nutrition_index(rows: list) -> dict:
    """把 list-nutrition-foods 的 160 条营养数据建成 {名称: {kcal, protein, ...}}。"""
    out = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        name = str(r.get("productName", "")).strip()
        if not name:
            continue
        rec = {
            "kcal": to_float(r.get("energyKcal")),
            "protein": to_float(r.get("protein")),
            "fat": to_float(r.get("fat")),
            "carb": to_float(r.get("carbohydrate")),
            "sodium": to_float(r.get("sodium")),
        }
        out[name] = rec
        key = strip_spec(name)
        out.setdefault(key, rec)
    return out


def match_nutrition(nut: dict, name: str) -> dict | None:
    if not name:
        return None
    if name in nut:
        return nut[name]
    base = strip_spec(name)
    if base in nut:
        return nut[base]
    for k, v in nut.items():
        if base and (base in k or k in base):
            return v
    return None
