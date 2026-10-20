# workbuddy.md · WorkBuddy 开发记录

本项目全程使用腾讯 WorkBuddy（AI 智能体）开发，本文为开发对话上下文摘要，
用于「麦当劳程序员创意开发大赛」WorkBuddy 专项奖励核验。

## 开发环境

- 工具：腾讯 WorkBuddy 桌面版（Agent 模式）
- 时间：2026-10-20 21:00 – 23:30（北京时间）
- MCP：麦当劳中国官方 MCP Server（`mcd-mcp`，https://mcp.mcd.cn ，
  通过 WorkBuddy 自定义连接器接入，Token 从 open.mcd.cn/mcp 申请）

## 开发过程摘要（对话主线）

1. **赛事调研**：让 WorkBuddy 抓取官方仓库活动规则、排行榜快照，
   并解析 500 条报名 Issue（483 个有效项目）做赛道聚类统计，
   确认「多人拼单 AA」为空白赛道（0 直接竞品），且自带 viral loop。

2. **技术验证**：WorkBuddy 通过已连接的 mcd-mcp 实测关键链路——
   - `query-nearby-stores` 定位合肥之心城餐厅
   - `query-meals` 拉取 106 个餐品真实价格
   - `query-meal-detail` 验证套餐可拆解（板烧三件套 → 堡/薯条/可乐，
     且 diffPrice 为相对默认项差价）
   - `calculate-price` 验证行实付 / 整单优惠 / 公共费结构
   - `list-nutrition-foods` 解析 160 条自定义表格格式营养数据

3. **架构设计**：与 WorkBuddy 讨论确定——
   Python 零第三方依赖（mccarbon 同款策略）、金额全整数分、
   最大余额法配平、债务最小化清算、单文件 HTML 清算卡、
   MCP 快照 + 纯前端 Demo（零 Token 门槛）。

4. **编码实现**：WorkBuddy 逐文件生成并实测——
   - `scripts/mcd_client.py`：手写 Streamable HTTP 客户端
     （JSON-RPC 2.0 + SSE + 三种返回格式归一化）
   - `scripts/expand.py`：套餐原子化拆解
   - `scripts/allocate.py`：分摊引擎（行内比例分摊/公共费/优惠回摊/
     最大余额法/贪心清算）
   - `scripts/plan.py`：端到端编排 9 个 MCP 工具
   - `scripts/card.py` + `scripts/cli.py` + `scripts/snapshot.py`
   - `demo/index.html`：纯前端拼单计算器

5. **测试驱动**：WorkBuddy 编写并运行
   - `tests/test_allocate.py`：34 项单元测试全过
   - `tests/smoke.py`：MCP 链路 7/7
   - `tests/e2e.py`：真实数据端到端（¥44.50 三人分，合计分毫不差）
   - 期间发现并修复：测试断言错误 1 处、
     套餐子项 code 与菜单不一致的名称兜底、Token 自动读取。

6. **文档与参赛材料**：README / MCP_INTEGRATION / SKILL.md /
   快照生成（43 套餐预拆解）/ 本文件。

## 用户角色

用户负责：需求决策（选题方向、命名「AA 除不尽」）、
MCP Token 申请与配置、GitHub 账号（Pupuiscoming）。
WorkBuddy 负责：调研、设计、全部代码与文档、测试。
