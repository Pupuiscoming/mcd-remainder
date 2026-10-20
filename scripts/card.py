"""生成单文件 HTML 清算卡：无 CDN、无脚本依赖，双击即可打开并截图分享。

设计目标：
- 一张图讲清「谁吃了什么、谁该付多少、谁转给谁」
- 手机友好，宽度自适应，可直接长截图发群
- 所有金额来自 MCP 真实核价，未核实时明确标注
"""

from __future__ import annotations

import html
from datetime import datetime

from allocate import fmt


def render_card(bill, transfers=None, repo_url: str = "", unverified: bool = False) -> str:
    transfers = transfers if transfers is not None else getattr(bill, "transfers", [])
    people = bill.people
    esc = html.escape

    persons_html = []
    for p in people:
        b = bill.bills[p]
        items = "".join(
            f"<li><span>{esc(u.label)}</span>"
            f"<em>{'' if u.qty in (1, 1.0) else f'×{u.qty:g}'}</em></li>"
            for u in b.units
        ) or "<li><span>未分配</span></li>"
        est = any(u.price_src in ("estimated_avg", "unknown") for u in b.units)
        persons_html.append(f"""
    <div class="person">
      <div class="phead"><span class="pname">{esc(p)}</span><span class="pamt">{fmt(b.total)}</span></div>
      <ul class="pitems">{items}</ul>
      <div class="pmeta">
        <span>食物 {fmt(b.food)}</span>
        <span>公共 {fmt(b.shared)}</span>
        <span>优惠 -{fmt(b.discount)}</span>
        <span class="kcal">{b.kcal:.0f} kcal</span>
      </div>
      {'<div class="warn">含估价，非菜单精确价</div>' if est else ''}
    </div>""")

    transfers_html = "".join(
        f"""<div class="tr"><span class="who">{esc(a)}</span>
        <span class="arrow">转账</span>
        <span class="who">{esc(b)}</span>
        <span class="amt">{fmt(c)}</span></div>"""
        for a, b, c in transfers
    ) or """<div class="tr none">无需转账，已平账</div>"""

    payer = getattr(bill, "payer", people[0] if people else "")
    unverified_note = ('<div class="unverified">离线演示数据，价格未经 MCP 实时核实</div>'
                       if unverified else "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    est_flag = any(u.price_src in ("estimated_avg", "unknown")
                   for line in bill.lines for u in line.units)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AA 除不尽 · 拼单清算卡</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#F5F5F5;font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
       color:#1a1a1a;padding:20px}}
  .card{{max-width:520px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;
        box-shadow:0 4px 24px rgba(0,0,0,.08)}}
  .head{{background:#DA291C;color:#fff;padding:20px 22px}}
  .head h1{{font-size:19px;font-weight:700;letter-spacing:.5px}}
  .head .sub{{font-size:12px;opacity:.85;margin-top:4px}}
  .sum{{display:flex;border-bottom:1px solid #eee}}
  .sum div{{flex:1;padding:14px 8px;text-align:center;border-right:1px solid #eee}}
  .sum div:last-child{{border-right:0}}
  .sum .k{{font-size:11px;color:#888}}
  .sum .v{{font-size:16px;font-weight:700;margin-top:2px}}
  .body{{padding:18px 22px}}
  .sec{{font-size:12px;color:#999;margin:0 0 10px;letter-spacing:1px}}
  .person{{background:#FAFAFA;border-radius:10px;padding:12px 14px;margin-bottom:10px}}
  .phead{{display:flex;justify-content:space-between;align-items:baseline}}
  .pname{{font-weight:600;font-size:15px}}
  .pamt{{font-weight:700;font-size:17px;color:#DA291C}}
  .pitems{{list-style:none;margin:8px 0;font-size:13px;color:#555}}
  .pitems li{{display:flex;justify-content:space-between;padding:1px 0}}
  .pitems em{{font-style:normal;color:#aaa;font-size:12px}}
  .pmeta{{display:flex;gap:10px;flex-wrap:wrap;font-size:11px;color:#999;
          border-top:1px dashed #e5e5e5;padding-top:7px;margin-top:4px}}
  .kcal{{color:#E8912D;font-weight:600}}
  .warn{{font-size:11px;color:#C77800;margin-top:5px}}
  .tr{{display:flex;align-items:center;gap:8px;background:#FFF8E6;border-radius:8px;
       padding:9px 12px;margin-bottom:7px;font-size:13px}}
  .tr .who{{font-weight:600}}
  .tr .arrow{{color:#bbb;font-size:11px}}
  .tr .amt{{margin-left:auto;font-weight:700;color:#DA291C}}
  .tr.none{{justify-content:center;color:#999;background:#F5F5F5}}
  .foot{{background:#FFF8E6;padding:12px 22px;font-size:11px;color:#999;text-align:center}}
  .foot b{{color:#DA291C}}
  .unverified{{background:#FFF3CD;color:#856404;padding:8px 22px;font-size:11px;text-align:center}}
  .rule{{font-size:11px;color:#aaa;line-height:1.7;border-top:1px solid #eee;
         padding:12px 22px 16px}}
</style></head><body>
<div class="card">
  <div class="head">
    <h1>AA 除不尽</h1>
    <div class="sub">{esc(bill.store_name)}　{now}　垫付：{esc(payer)}</div>
  </div>
  {unverified_note}
  <div class="sum">
    <div><div class="k">实付合计</div><div class="v">{fmt(bill.payable)}</div></div>
    <div><div class="k">参与人数</div><div class="v">{len(people)} 人</div></div>
    <div><div class="k">转账笔数</div><div class="v">{len(transfers)} 笔</div></div>
  </div>
  <div class="body">
    <p class="sec">每人应付</p>
    {''.join(persons_html)}
    <p class="sec" style="margin-top:16px">结算方案</p>
    {transfers_html}
  </div>
  <div class="rule">
    分摊规则：套餐按各子项<b>原价权重</b>比例分摊实付金额（不是人头平分）；
    打包费/配送费按{('食物金额比例' if bill.shared_rule == "by_amount" else '人头')}分摊；
    整单优惠按各人金额比例回摊；金额以「分」为单位用最大余额法配平，合计分毫不差。
    {'部分子项未能匹配到菜单精确价，已标注为估价。' if est_flag else ''}
  </div>
  <div class="foot">由 <b>McRemainder · AA 除不尽</b> 生成 · 数据来自麦当劳中国官方 MCP{('　' + esc(repo_url)) if repo_url else ''}</div>
</div>
</body></html>"""
