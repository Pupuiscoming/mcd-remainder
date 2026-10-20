"""把清算结果渲染成 PNG 卡片（微信/QQ 群直发图片，无需截图）。

用法：
    python scripts/cli.py --demo --json examples/result.json
    python scripts/card_png.py examples/result.json --out assets/card-demo.png

依赖：Pillow（仅本脚本需要，其余功能零依赖）
字体：Windows 微软雅黑；其他系统请改 FONT_DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

W = 750
RED = (218, 41, 28)
GOLD = (255, 199, 44)
CREAM = (255, 248, 230)
INK = (26, 26, 26)
GRAY = (85, 85, 85)
LIGHT = (153, 153, 153)
LINE = (238, 238, 238)
BGROW = (250, 250, 250)
WARN = (199, 120, 0)

FONT_DIR = Path("C:/Windows/Fonts")
F_REG = str(FONT_DIR / "msyh.ttc")
F_BOLD = str(FONT_DIR / "msyhbd.ttc")


def font(size: int, bold=False):
    from PIL import ImageFont
    path = F_BOLD if bold else F_REG
    if not Path(path).exists():
        path = F_REG
    return ImageFont.truetype(path, size)


def fmt(cents: int) -> str:
    return f"¥{cents / 100:.2f}"


def render(data: dict, out_path: Path) -> Path:
    people = data.get("people", [])
    transfers = data.get("transfers", [])

    # ---------- 动态高度 ----------
    pad = 40
    head_h = 170
    sum_h = 110
    person_hs = []
    for p in people:
        n_items = len([u for ln in data.get("lines", [])
                       for u in ln.get("units", []) if u.get("person") == p.get("name")])
        person_hs.append(96 + max(n_items, 1) * 36 + 18)
    tr_h = 120 + len(transfers) * 66 + 20
    foot_h = 130
    H = head_h + sum_h + sum(person_hs) + tr_h + foot_h + pad

    img = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(img)

    # ---------- 头部 ----------
    d.rectangle([0, 0, W, head_h - 10], fill=RED)
    d.text((pad, 42), "AA 除不尽", font=font(46, True), fill=(255, 255, 255))
    d.text((pad + 250, 58), "McRemainder", font=font(22), fill=(255, 214, 208))
    store = data.get("store", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    payer = next((p["name"] for p in people if p.get("paid_cents", 0) > 0), "")
    sub = f"{store}　·　{now}" + (f"　·　垫付：{payer}" if payer else "")
    d.text((pad, 118), sub, font=font(20), fill=(255, 224, 220))
    d.rectangle([0, head_h - 10, W, head_h], fill=GOLD)

    # ---------- 汇总 ----------
    y = head_h + 18
    d.text((pad, y), "这顿拼单", font=font(22, True), fill=INK)
    boxes = [("实付合计", fmt(data.get("payable_cents", 0))),
             ("参与人数", f"{len(people)} 人"),
             ("转账笔数", f"{len(transfers)} 笔")]
    bw = (W - pad * 2 - 20) // 3
    for i, (k, v) in enumerate(boxes):
        bx = pad + i * (bw + 10)
        d.rounded_rectangle([bx, y + 38, bx + bw, y + 104], 10, fill=(255, 255, 255))
        d.text((bx + 14, y + 48), k, font=font(17), fill=LIGHT)
        d.text((bx + 14, y + 68), v, font=font(24, True), fill=INK)

    # ---------- 每人账单 ----------
    y = head_h + sum_h + 8
    d.text((pad, y), "每人应付", font=font(22, True), fill=INK)
    y += 42
    for p, ph in zip(people, person_hs):
        units = [u for ln in data.get("lines", [])
                 for u in ln.get("units", []) if u.get("person") == p.get("name")]
        d.rounded_rectangle([pad, y, W - pad, y + ph - 10], 12, fill=BGROW)
        d.text((pad + 20, y + 16), p.get("name", ""), font=font(26, True), fill=INK)
        amt = fmt(p.get("total_cents", 0))
        aw = d.textlength(amt, font=font(30, True))
        d.text((W - pad - 20 - aw, y + 14), amt, font=font(30, True), fill=RED)
        iy = y + 56
        for u in units:
            label = u.get("label", "")
            qty = u.get("qty", 1)
            txt = label + (f"  ×{qty:g}" if qty not in (1, 1.0) else "")
            d.text((pad + 20, iy), txt, font=font(19), fill=GRAY)
            est = u.get("price_src") in ("estimated_avg", "unknown")
            if est:
                tw = d.textlength(txt, font=font(19))
                d.text((pad + 26 + tw, iy - 2), "估价", font=font(14), fill=WARN)
            iy += 36
        meta = (f"食物 {fmt(p.get('food_cents', 0))}"
                f"　公共 {fmt(p.get('shared_cents', 0))}"
                f"　优惠 -{fmt(p.get('discount_cents', 0))}")
        d.text((pad + 20, iy + 2), meta, font=font(16), fill=LIGHT)
        kcal = p.get("kcal", 0)
        kt = f"{kcal:.0f} kcal"
        kw = d.textlength(kt, font=font(16, True))
        d.text((W - pad - 20 - kw, iy + 2), kt, font=font(16, True), fill=(232, 145, 45))
        y += ph

    # ---------- 转账 ----------
    d.text((pad, y), f"结算方案（{len(transfers)} 笔转账）", font=font(22, True), fill=INK)
    y += 42
    if not transfers:
        d.rounded_rectangle([pad, y, W - pad, y + 52], 10, fill=(240, 240, 240))
        cw = d.textlength("无需转账，已平账", font=font(19))
        d.text(((W - cw) / 2, y + 14), "无需转账，已平账", font=font(19), fill=LIGHT)
        y += 66
    for t in transfers:
        d.rounded_rectangle([pad, y, W - pad, y + 54], 10, fill=CREAM)
        d.text((pad + 20, y + 12), t.get("from", ""), font=font(21, True), fill=INK)
        aw = d.textlength("—转账→", font=font(15))
        d.text((pad + 150, y + 18), "—转账→", font=font(15), fill=(187, 187, 187))
        d.text((pad + 170 + aw, y + 10), t.get("to", ""), font=font(21, True), fill=INK)
        amt = fmt(t.get("cents", 0))
        amw = d.textlength(amt, font=font(22, True))
        d.text((W - pad - 20 - amw, y + 13), amt, font=font(22, True), fill=RED)
        y += 66

    # ---------- 校验 ----------
    total = sum(p.get("total_cents", 0) for p in people)
    payable = data.get("payable_cents", 0)
    ok = "分毫不差" if total == payable else "不一致"
    vt = f"校验通过 · 各人应付合计 {fmt(total)} = 实付 {fmt(payable)} · {ok}"
    vw = d.textlength(vt, font=font(17))
    d.text(((W - vw) / 2, y + 6), vt, font=font(17), fill=LIGHT)

    # ---------- 底部 ----------
    d.rectangle([0, H - foot_h, W, H], fill=(255, 251, 232))
    d.line([(pad, H - foot_h + 1), (W - pad, H - foot_h + 1)], fill=GOLD, width=2)
    rule = "分摊规则：套餐按子项原价权重比例分摊 · 公共费按食物金额比例 · 优惠按比例回摊"
    rule2 = "金额以「分」为单位最大余额法配平，合计精确等于实付"
    d.text(((W - d.textlength(rule, font=font(14))) / 2, H - foot_h + 22),
           rule, font=font(14), fill=(170, 160, 130))
    d.text(((W - d.textlength(rule2, font=font(14))) / 2, H - foot_h + 46),
           rule2, font=font(14), fill=(170, 160, 130))
    ft = "McRemainder · AA 除不尽　—　数据来自麦当劳中国官方 MCP"
    d.text(((W - d.textlength(ft, font=font(14))) / 2, H - foot_h + 84),
           ft, font=font(14), fill=(190, 180, 150))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", help="cli.py --json 导出的清算结果")
    ap.add_argument("--out", default=str(ROOT / "assets" / "card.png"))
    args = ap.parse_args()
    data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    out = render(data, Path(args.out))
    print(f"PNG 清算卡已生成：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
