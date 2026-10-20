# MCP Integration · 麦当劳 MCP 集成说明

## Server

| 项 | 值 |
|---|---|
| Server | 麦当劳中国官方 MCP（`mcd-mcp`） |
| 接入方式 | Streamable HTTP · `https://mcp.mcd.cn` |
| 认证 | `Authorization: Bearer <MCP_TOKEN>`（Token 从 https://open.mcd.cn/mcp 申请） |
| 客户端实现 | `scripts/mcd_client.py` —— **零第三方依赖**，仅 Python 标准库 `urllib`，手写 JSON-RPC 2.0 + SSE 解析 + Session 管理 |

配置示例见 [`mcp-config.example.json`](mcp-config.example.json)（仅环境变量占位符，仓库不含真实 Token）。

## 调用流程

```
用户描述拼单（谁、点了什么、谁垫付）
        │
        ▼
query-nearby-stores ──── 定位门店（city + keyword → storeCode）
        │
        ▼
query-meals ──────────── 拉取该门店真实菜单（106 个餐品 + 现价/原价）
        │
        ▼
query-meal-detail ────── 对每个套餐拉取选配结构，原子化拆解
        │                 （板烧三件套 → 板烧鸡腿堡 / 中薯条 / 可乐中杯）
        │                 diffPrice 相对默认项差价 → 任意换配精确定价
        ▼
calculate-price ──────── 真实核价（一次提交全部商品）
        │                 返回：每行实付 subtotal / 整单 discount
        │                       / packingPrice / deliveryPrice / tablewarePrice
        ▼
list-nutrition-foods ─── 160 条官方营养数据 → 每人热量账单
        │
        ▼
query-store-coupons ─┐
query-my-coupons ────┼─ 券信息（可领的 / 已有的 / 门店可用的）
available-coupons ───┘   → 拼单凑单提示
        │
        ▼
query-my-account ─────── 积分归属提示（整单积分给垫付人的建议）
        │
        ▼
分摊引擎（本地计算，不发 MCP 请求）
  行内按子项原价权重比例分摊 → 公共费分摊 → 优惠回摊
  → 最大余额法配平 → 债务最小化清算
        │
        ▼
单文件 HTML 清算卡（可截图分享）
```

**只读为主。** 本项目不调用 `create-order` / `cancel-order` / `auto-bind-coupons` 等
写操作工具——清算场景只需要算清楚，不需要替用户下单。

## 工具清单与业务价值

| # | 工具 | 类型 | 业务价值 | 实测 |
|---|---|---|---|---|
| 1 | `query-nearby-stores` | 只读 | 按城市+关键词定位门店，拿 storeCode | ✅ 合肥之心城 3500158 |
| 2 | `query-meals` | 只读 | 门店真实菜单：106 个餐品、现价/原价。**套餐子项估价的基准** | ✅ 14 分类 / 106 餐品 |
| 3 | `query-meal-detail` | 只读 | **核心依赖**：套餐拆解为 rounds/choices，diffPrice 差价 | ✅ 43 个套餐全部预拆解 |
| 4 | `calculate-price` | 只读 | 真实核价：行实付、整单优惠、打包/配送/餐具费（单位：分） | ✅ |
| 5 | `list-nutrition-foods` | 只读 | 160 条营养数据 → 每人 kcal / 蛋白质账单 | ✅ |
| 6 | `query-store-coupons` | 只读 | 指定门店+订单类型可用券 | ✅（当前门店空） |
| 7 | `query-my-coupons` | 只读 | 用户卡包已有券（不承诺当前订单可用） | ✅ |
| 8 | `available-coupons` | 只读 | 麦麦省当前可领券 → 拼单凑单提示 | ✅ 5 张 |
| 9 | `query-my-account` | 只读 | 积分账户 → 整单积分归属垫付人的建议 | ✅ |

## 实测记录（真实调用，2026-10-20）

### 套餐拆解（query-meal-detail · 板烧鸡腿堡三件套 9900005462）

```json
{"rounds": [
  {"id": 1, "name": "板烧鸡腿堡", "choices": [
     {"code": "1406", "name": "板烧鸡腿堡", "isDefault": 1, "diffPrice": "+ ¥0"}]},
  {"id": 2, "name": "选择套餐内小食", "choices": [
     {"code": "4810",  "name": "中薯条",                    "isDefault": 1, "diffPrice": "+ ¥0"},
     {"code": "4820",  "name": "大薯条",                    "diffPrice": "+ ¥2"},
     {"code": "4437",  "name": "小杯玉米杯",                "diffPrice": "- ¥1"},
     {"code": "514782","name": "脆脆薯条",                  "diffPrice": "+ ¥2"}]},
  {"id": 3, "name": "选择套餐内饮料", "choices": [
     {"code": "3050", "name": "可乐中杯", "isDefault": 1, "diffPrice": "+ ¥0"},
     {"code": "3071", "name": "无糖可口可乐中杯",           "diffPrice": "+ ¥0"},
     {"code": "507411","name": "麦咖啡™冰美式中杯",         "diffPrice": "+ ¥9"}]}
]}
```

**定价原理**：默认项价格从菜单查得（中薯条 ¥14），任意换配 =
默认项价 + diffPrice（大薯条 = 14 + 2 = ¥16）。全程无编造。

### 真实核价（calculate-price）

```json
{"productPrice": 9440, "discount": 0, "price": 9440,
 "productList": [
   {"productCode": "9900005462", "productName": "板烧鸡腿堡三件套",
    "quantity": 1, "originalSubtotal": 3450, "subtotal": 3450},
   {"productCode": "9900006332", "productName": "薄皮V翅双拼十翅",
    "quantity": 1, "originalSubtotal": 4990, "subtotal": 4990}],
 "packingPrice": 0, "deliveryPrice": 0, "tablewarePrice": 0}
```

`productList[].subtotal` 即"行实付"——分摊引擎以它为分子，
保证各人金额之和精确等于整单实付。

## 踩坑记录（真实开发中遇到并解决）

1. **套餐子项 code 与菜单单品 code 不一致**
   套餐内「可乐中杯」code=`3050`，而菜单单品「可乐」code=`9900008751`。
   解决：`menu.find_by_name()` 名称匹配兜底（去规格词 → 精确 → 包含），
   并在清算卡上标注每个子项的价格来源（`menu_code` / `menu_name` / `estimated`）。

2. **MCP 返回三种格式需要归一化**
   - `structuredContent`：干净 JSON（首选）
   - `content[].text`：说明文字 + `## Original Response` + JSON
   - `list-nutrition-foods` 的 `data` 是自定义表格字符串 `[160]{productName,...}`
   解决：`mcd_client.unwrap()` 三级解析 + `parse_custom_table()` 表格解析。

3. **价格单位是「分」**：所有金额以整数分参与计算，
   避免浮点误差；展示层统一 ÷100。

4. **营养数据有重复条目**：按 `productName` 去重 + 去规格词匹配。

5. **限流**：官方 600 次/分钟。快照模式一次预取（43 套餐拆解），
   之后离线复用，不再消耗额度。

## 数据诚实原则

- 快照数据标注 `generated_at`，离线 Demo 明确显示"未经实时核价"
- 未能匹配菜单精确价的子项在结果中标注"估价"
- MCP 调用失败时降级并如实报错，**绝不编造餐品、价格、营养数据**
