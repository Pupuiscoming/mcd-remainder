---
name: mcd-remainder
description: AA 除不尽 · 麦当劳拼单清算 Skill。当用户提到拼单、一起点麦当劳、AA 算账、谁该付多少、分摊餐费、垫付收钱等场景时使用。基于麦当劳 MCP 把套餐拆到单品粒度、真实核价、按子项原价权重分摊、最大余额法配平、债务最小化清算，并生成可截图分享的清算卡。
---

# AA 除不尽 · 麦当劳拼单清算

## 触发场景

- "我们仨拼单点了麦当劳，帮我算算谁该付多少"
- "我垫付了 XX 元，他们该转我多少"
- "一个三件套三个人分着吃，怎么算钱"
- "帮我生成拼单清算卡"

## 执行流程

### 第 1 步：收集信息（缺什么问什么，一次问全）

- 参与人员名单（≥2 人）
- 每个人吃了什么（套餐要问清谁吃堡/薯条/饮料，或子项归谁）
- 谁垫付（默认第一人）
- 门店（可选：默认按城市+地标搜索）

### 第 2 步：定位门店（若用户未指定）

调用 `query-nearby-stores`（beType=1, searchType=2, city, keyword），
展示门店名与 storeCode，请用户确认。

### 第 3 步：拉取菜单并拆解

- `query-meals`（storeCode, orderType=1, beType=1）→ 真实菜单与价格
- 对套餐调用 `query-meal-detail` → 拆出 rounds/choices 子项
- 子项定价：默认项查菜单价，换配项 = 默认价 + diffPrice

### 第 4 步：真实核价

`calculate-price`（storeCode, orderType=1, beType=1, items=[{productCode, quantity}]）
→ 每行 subtotal（行实付）、discount（整单优惠）、packing/delivery/tableware（公共费）

### 第 5 步：分摊（本地算法，见 scripts/allocate.py）

1. 行内按子项原价权重比例分摊实付
2. 公共费按食物金额比例（可按人头）分摊
3. 整单优惠按各人食物金额比例回摊
4. 以「分」为单位，最大余额法配平
5. 债务最小化清算（N 人最多 N-1 笔转账）

### 第 6 步：热量归属（可选加分项）

`list-nutrition-foods` → 160 条营养数据按归属聚合，每人 kcal 账单。

### 第 7 步：输出

- 对话中展示：每人应付表 + 转账方案 + 校验行（合计 == 实付）
- 用户需要分享卡时：运行
  `python scripts/cli.py --spec <方案.json> --card <卡片.html>`
  生成单文件 HTML 清算卡

## 工具纪律

- ✅ 可调：query-nearby-stores / query-meals / query-meal-detail /
  calculate-price / list-nutrition-foods / query-store-coupons /
  query-my-coupons / available-coupons / query-my-account
- ❌ 禁止自动调用：create-order / cancel-order / auto-bind-coupons /
  draw-lottery（用户明确要求下单时才走确认流程）
- ❌ 禁止编造：价格未经 calculate-price 核实时必须标注"未核实"；
  子项估价必须标注来源

## 兜底

- MCP 不可用：提示用户配置 Token，或引导使用 demo/index.html 离线版
- 套餐子项匹配不到菜单价：按已估价子项均值兜底并标注"估价"
