---
name: alpha-radar
description: 多维投资研究与决策系统。五模块闭环——基本面引擎 → 估值引擎 → 决策引擎 → 预测账本 → 复盘引擎。用于对一家上市公司做标准化评估，并持续验证"预测 vs 实际"。当用户说"用 Alpha Radar 分析 XXX"、"判断这家公司基本面"、"这家公司值不值得关注"、"现在能不能买"、"给个买入区间"、"复盘一下当初的预测"、"我的预测准不准"、"快速筛一下这家公司"时触发。一手数据源：美股（SEC EDGAR，已自动化）；港股 / A股 为实验性（尚无自动取数）。
---

# 🛰️ Alpha Radar — 多维投资研究与决策系统

**Version:** 1.2
**工作区:** `D:/pi/select_stock`
**Purpose:** 对一家上市公司进行标准化的基本面、估值、投资决策、预测记录与复盘，并持续验证"预测 vs 实际"。

---

## 0. 六条铁律（违反任何一条，整个系统失效）

1. **先基本面，后估值。** 先回答"公司是不是越来越好"，再回答"贵不贵"。
2. **先预测企业价值，再看股价。** 不被当前价格锚定。
3. **股价下跌 ≠ 加仓理由；股价上涨 ≠ 卖出理由。** 只有基本面变化才触发仓位变化。
4. **价格变化与基本面变化必须分开记账。** 两者是独立变量。
5. **旧预测永不覆盖。** 一切记录 append-only，新判断产生新版本 v2 / v3。
6. **每个数字必须有来源与数据截点。** 禁止凭记忆或"印象中"写财务数字；无法验证的标注 `[未验证]`。

> **v1.1 起，纪律由代码强制，而非靠自觉：**
> 指标名必须命中词表（`metrics` 子命令）、实际值单位必须与预测一致、同版本内改数被拒绝（必须升版本）、
> 预测能力只对 **Base Case** 计分。详见 §6。

附加原则：
7. 预测错误必须归因，不许含糊带过。
8. 投资逻辑失效（thesis broken）比股价下跌更值得行动。
9. 最终目标不是提高预测命中率，而是提高**长期风险调整后收益**。

---

## 1. 五大模块总览

```text
                    🛰️ ALPHA RADAR
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
  ① FUNDAMENTAL     ② VALUATION      ③ DECISION
    基本面引擎          估值引擎          决策引擎
   公司好不好？        贵不贵？         买不买？买多少？
        │                 │                 │
        └─────────────────┼─────────────────┘
                          ▼
                    ④ PREDICTION LEDGER
                       预测账本（不可覆盖）
                          │
                          ▼
                    ⑤ REVIEW ENGINE
                       复盘引擎（预测 vs 实际）
                          │
                          ▼
                   改进下一次判断
```

| 模块 | 回答的问题 | 输出 |
|---|---|---|
| 01 Fundamental | 这是不是一家越来越好的公司？ | Fundamental Score / 100、Trend ↑→↓、Lifecycle Stage、Moat Score |
| 02 Valuation | 公司很好，但现在是不是太贵？ | Bear/Base/Bull、2027/2030 Fair Value、当前价格隐含情景、Margin of Safety |
| 03 Decision | 现在到底该不该买？买多少？ | Starter/Buy/Strong Buy/Heavy/Trim/Exit + 价格带 |
| 04 Prediction Ledger | 我们当初到底预测了什么？ | 不可覆盖的预测版本记录 |
| 05 Review | 后来到底对不对？错在哪？ | Actual vs Forecast、误差归因、Thesis 状态、预测能力评级 |

---

## 2. 数据来源纪律（这是本 skill 与"聊天式分析"的根本区别）

### 优先级
1. **一手申报文件**：美股 SEC EDGAR（10-K / 10-Q / 8-K / DEF 14A）、港股 HKEX 年报、A股 巨潮资讯
2. **财报原文与电话会纪要**
3. **行情与一致预期**：`stock-analysis` skill 脚本
4. **第三方数据**：仅用于交叉验证，必须标注

### 执行规则
- 每份报告开头必须写明：**数据截点、证据来源、数据文件路径**
- 估值口径必须区分 **GAAP 与 adjusted**，公司自己披露的 adjusted 数字不能直接当利润
- TTM 与 FY 口径不得混用
- 并购带来的收入增长不得混入 organic growth

### 现有工具链（复用，不要重造）

```bash
# [D-14] 一手数据自动取数（SEC）：ticker → CIK → companyfacts → 结构化提取
py scripts/alpha_fetch.py APH
py scripts/alpha_fetch.py --cik 820313
py scripts/alpha_fetch.py APH --force          # 忽略缓存重新下载
py scripts/alpha_fetch.py APH --no-extract     # 只下载
py scripts/alpha_fetch.py APH --submissions    # 顺带取近期申报清单

# 多层数据校验（**写档案前的强制前置**）
py scripts/verify_data.py ITRI --require-cross
py scripts/verify_data.py --all              # 校验全部已下载公司
py scripts/verify_data.py APH --no-cross      # 离线（仅内部校验）

# 预滞后的手动逃逸口
py analysis/sec/extract2.py <companyfacts.json>

# 一手指标计算：从 companyfacts 直接算 TTM / Margin / FCF / ROIC / 净债务
py scripts/alpha_metrics.py APH
py scripts/alpha_metrics.py APH --years 8
py scripts/alpha_metrics.py APH --json
py scripts/alpha_metrics.py APH --score-inputs   # 直接输出 alpha_score.py 的定量参数

# [D-75] 站点构建的【唯一入口】—— 本地与 CI 共用同一条路径
py scripts/pages_build.py                  # 构建 + 安全断言
py scripts/pages_build.py --with-gates     # 再跑全部 8 道门禁（CI 用这个）
py scripts/pages_build.py --strict         # 任一失败即非零退出

# [D-70] 静态站点（只读快照，可离线打开 / 可上 GitHub Pages）
py scripts/build_site.py                     # 默认：不含持仓（可公开）
py scripts/build_site.py --include-holdings  # 🔴 含持仓，不要公开
py scripts/build_site.py --with-gates        # 同时嵌入最近一次门禁结果
py scripts/build_site.py --out site/index.html

# [D-68] 一致预期（分析师预测）—— 研究级情景的必要输入
py scripts/alpha_quote.py NVDA --estimates
py scripts/alpha_quote.py NVDA --estimates --json
#   流程：fc.yahoo.com 取 cookie → /v1/test/getcrumb 取 crumb → 带两者请求
#   返回：目标价(均值/区间/家数)、评级、前瞻 PE、各期 EPS/收入一致预期
#   实测与原始报告完全吻合（ITRI $129.56 / INTU $405.60 / NOW $146.73）→ 数据源可信

# [D-66] 规则化情景（无行业研究时的占位，明确标注为低置信度）
py scripts/alpha_scenario.py NVDA
py scripts/alpha_scenario.py NVDA --json

# [D-13] 持仓与组合雷达
py scripts/alpha_portfolio.py sync                 # 从券商 API 拉取持仓快照
py scripts/alpha_portfolio.py sync --dry-run       # 只看字段，不写盘
py scripts/alpha_portfolio.py sync --user U --password P
py scripts/alpha_portfolio.py buy  --ticker MSFT --shares 10 --price 500 --date 2026-03-01
py scripts/alpha_portfolio.py sell --ticker MSFT --shares 4  --price 560 --date 2026-09-01
py scripts/alpha_portfolio.py cash --amount 25000
py scripts/alpha_portfolio.py holdings             # 当前持仓
py scripts/alpha_portfolio.py board                # 组合雷达（分析 + 持仓 + 一致性 + 集中度）
py scripts/alpha_portfolio.py check                # 只列持仓与分析的冲突
py scripts/alpha_portfolio.py analysis --ticker APH --score 84.6 --odds 0.92 --action Watch --price 87.24
```

**`alpha_portfolio.py` 选项速查：**

| 子命令 | 关键选项 |
|---|---|
| `sync` | `--url` `--user` `--password` `--proxy` `--dry-run` `--as-of` `--full` |
| `analysis` | `--ticker` `--score` `--lifecycle` `--moat` `--roic` `--wacc` `--net-debt-ebitda` `--odds` `--weighted` `--bear` `--action` `--price` `--valuation-pct` `--dossier` `--date` |
| `buy` / `sell` | `--ticker` `--shares` `--price` `--date` `--fee` `--currency` `--note` |
| `cash` | `--amount` |
| `holdings` / `board` / `check` | 无选项 |

```bash
# 行情快照（示例用法）
# 行情快照（[D-29] yfinance 的备选源；本机直连 Yahoo 不可达，需本地代理）
py scripts/alpha_quote.py APH
py scripts/alpha_quote.py APH --json
py scripts/alpha_quote.py APH --offline         # 只用缓存
py scripts/alpha_quote.py APH --proxy http://127.0.0.1:7897
py scripts/alpha_quote.py APH --estimates

# 行情 / 估值 / 财务快照（注意：依赖 yfinance，可能 429 限流，见 D-29）
py "C:/Users/Administrator/.pi/agent/skills/stock-analysis/scripts/stock_info.py" <TICKER>

# 预测账本 / 决策库 / 复盘
py scripts/alpha_ledger.py <子命令>

# 辅助计算器（评分锚 / 仓位 / 快速筛查）
py scripts/alpha_score.py <子命令>
```

**一手数据纪律**：`alpha_fetch.py` 取回的是 SEC 原始 `companyfacts`（未加工），
`<ticker>.txt` 只是提取视图。**写作前必须与 10-K/10-Q 原文交叉验证**，不要把提取结果直接当结论。

> **`alpha_metrics.py` 的 TTM 算法**：`最近年度 + 本年迄今 − 去年同期`。
> 这是为了避开「Q4 无独立季报」的问题。三个容易踩的坑（已修为 D-34/D-35/D-42）：
> ① 各 tag 的起始年份不同，**必须按日期对齐，不能用下标索引平行数组**；
> ② 同一结束日可能同时有 90 天（Q2）与 181 天（H1）两份，**必须取最长时长**；
> ③ 资产负债表三项（现金/权益/债务）**必须对齐到同一日期**，否则净债务是混合口径的假数；
> ④ **净债务必须扣除短期投资**（现金 + 短期投资）。否则会系统性高估 ——
>    实测 APH 高估 0.69B（14.08 vs 13.39）、INTU 高估 2.50B（2.96 vs 0.47）。
> ⑥ **总债务必须包含融资租赁负债**（有息、固定付款、融资资产 → 属于债务）。
>    实测 MSFT 用融资租赁建数据中心，金额 **$66.59B**；不计入会把净负债 +30.05B
>    误报成"净现金 −36.55B"。**经营租赁单独列示，不计入净债务**（为与 EBITDA 口径一致）。
> ⑦ **TTM 的财年边界**：若季末**恰好等于**财年末，TTM 就是该财年值 ——
>    此时基准年度必须是**上一年**。实测 MSFT CapEx 因此被算成 167.35B（真值 115.95B）。
> ⑤ **财年归属必须按财年**（INTU/FY 7 月结束）；单调性检查只对**收入**成立，NI/OCF 可为负。

### 2.1 多层数据校验（[G7] 强制）

> **错误的数据导致错误的结果。** 凡是要写进档案的财务数字，
> 必须先过 `verify_data.py`，**且不得有 ❌ 硬错误**。

四层校验：

| 层 | 检查什么 | 抓过什么 |
|---|---|---|
| **L1 会计恒等式** | Revenue − COGS = GrossProfit；GrossProfit > OpInc | 转写/取数错 |
| **L2 时间一致性** | YTD 单调性；YTD 取最长时长断言；**净债务同日性与独立重算**；TTM 量级包络 | D-35、D-42 |
| **L3 交叉来源** | **SEC vs Yahoo 同一日期逐项比对**；TTM 与 Yahoo trailing 比对 | D-35（内部双路抓不到） |
| **L4 量纲合理性** | 正负号、区间、有限数 | — |

**三种结论，不是两种：**

| 标记 | 含义 | 处理 |
|---|---|---|
| ✅ MATCH | 紧容差内 | — |
| ⚠️ DEFINITIONAL | 口径差异 / **日期不可比** | 提示，需人工判断；不算错 |
| ❌ MISMATCH | 超容差 | **查明前不得写档案**，退出码 1 |

> **为什么必须有 ⚠️ 这一级**：只分对/错会产生大量假警报，
> 而假警报会训练人忽略校验器 —— 那比没有校验器更糟。

**两条铁的教训（均已实测验证）：**

1. **交叉校验的有效性上限 = 两条路径的独立性。**
   内部的"双路 TTM"两条路径都调用同一个 `ytd` 原语 → 共享 bug → 必然一致。
   实测：注入 D-35 后内部双路仍报 Δ0.000%。**只有外部源（Yahoo trailing）能抓到它。**
2. **校验器与被校验对象必须共用"路径"，只在"数值"上独立。**
   这里**踩了三次**同一个坑：① 只查数据可用性不查引擎输出；② 用自己的 tag 列表；
   ③ 调 `latest()` 而引擎用 `latest_common()` + 求和。三次都是假绿。
   最终做法：抽出 `Facts.balance_sheet()` 作为唯一路径，校验器只独立重算数值。
3. **外部交叉的覆盖面 = 你能抓到的错误面。**
   capex/FCF 一开始不在交叉范围内，于是 MSFT 的 TTM 错误静默通过。
   **把 capex、FCF、去年同期 TTM 都加进交叉后，它被 8 条检查同时抓到。**
4. **每建一份新档案，必须重跑全部旧档案的校验**（`--all`）。
   实测：净债务口径错误**同时污染了两份档案**，而第一份已提交。
   单份校验只能证明"这一份自洽"，证明不了"所有档案口径一致"。

### 与已有 skill 的分工
- `investment-bottom-up-research`：**行业与产业链研究**（世界规律 → 产业链 → 瓶颈 → 护城河）
- `stock-analysis`：**数据获取层**
- `alpha-radar`：**公司评估与决策层 + 预测闭环**

典型链路：先用 bottom-up 找到值得研究的行业与公司 → 再用 Alpha Radar 逐家评估、定价、决策、记录预测。

---

## 3. Module 01 — Fundamental Engine

> 回答：**这家公司是不是越来越好？**

### 3.1 商业模式
必须回答：
- 公司卖什么？谁付钱？为什么客户买？为什么继续买？
- 收入来自哪里（产品 / 订阅 / 广告 / 服务 / 授权 / 佣金 / 硬件）？
- 收入是否重复？集中度如何（最大客户 / 地区 / 产品 / 行业）？

**收入质量排序：** 经常性收入 > 重复购买 > 一次性收入

### 3.2 增长质量
不要只看 Revenue Growth。必须拆成：

```text
增长 = 价格 × 数量 × 市占率 × 新产品 × 并购
```

必须单独列出 **Organic Growth** 与 **M&A Growth**。
> 30% 收入增长里如果有 20% 来自收购，那它不是 30% 的内生增长能力。

### 3.3 护城河（10 类，各评 0–5）

| # | 护城河 | 核心追问 |
|---|---|---|
| 1 | 品牌 | 客户为什么愿意多付钱？ |
| 2 | 网络效应 | 用户越多，产品是否越有价值？ |
| 3 | 转换成本 | 客户换供应商有多痛苦？ |
| 4 | 成本优势 | 为什么它的成本更低？可持续吗？ |
| 5 | 规模 | 规模是否构成竞争壁垒，还是只是负担？ |
| 6 | 技术 | 技术领先能保持几年？ |
| 7 | 数据 | 数据是否形成长期复利？ |
| 8 | 生态 / 锁定 | 产品之间是否互相强化？ |
| 9 | 客户认证 | 重新认证的周期与代价有多高？ |
| 10 | 渠道 / 分销 | 触达客户的路径是否稀缺？ |

输出 **Moat Score（/10）** 与 **Moat Trend ↑ / → / ↓**。

### 3.4 盈利能力
- Gross Margin / Operating Margin / Net Margin / FCF Margin
- 重点不是绝对值，而是**趋势**
  - `Revenue ↑ + Margin ↑` → 高质量增长（operating leverage）
  - `Revenue ↑ + Margin ↓` → 增长质量需要调查

### 3.5 现金流质量（本模块最重要）

```text
FCF          = Operating Cash Flow − CapEx
FCF Margin   = FCF / Revenue
Cash Conversion = FCF / Net Income
```

必须回答：**利润有没有真正变成现金？**

| 信号 | 判断 |
|---|---|
| Net Income ↑ + FCF ↑ | 健康 |
| Net Income ↑ + FCF ↓ | 必须调查：CapEx / Inventory / Receivables / 营运资本 / M&A |

### 3.6 ROIC
- 计算 ROIC 并与 WACC 对比：`ROIC > WACC` 才创造价值
- **重点：高增长过程中 ROIC 是否下降。** 若收入 100→150→225 但 ROIC 25%→18%→11%，说明增长越来越贵。

### 3.7 CapEx 效率
CapEx 不是天然负面。必须判断链条：

```text
CapEx → Revenue → FCF → ROIC
```
- 高 CapEx + 收入↑ + 利润率↑ + ROIC↑ → 可接受
- 高 CapEx + 收入增速↓ + ROIC↓ → 危险

### 3.8 资产负债表
Cash / Debt / Net Debt / Net Debt-EBITDA / Interest Coverage / Debt Maturity / Liquidity

**最危险组合：高增长 + 高负债 + 高 CapEx。**

### 3.9 管理层与资本配置
- **Guidance Accuracy**：过去管理层指引准不准？
- **Capital Allocation 排序**：高 ROIC 投资 > 低估回购 > 合理股息 > 并购 > 低回报投资
- **M&A**：并购是增加了 EPS，还是只是增加了 Revenue？
- **回购**：是否真的减少了股本，还是只在抵消股权激励（净稀释）？

### 3.10 竞争格局横向对比
至少 2–3 个直接竞争对手，比较：Revenue Growth / Gross Margin / Operating Margin / FCF Margin / ROIC / 市占率 / R&D / CapEx / Valuation。

### 3.11 Fundamental Score（默认权重 100 分）

| 指标 | 权重 |
|---|---:|
| Revenue Growth | 10 |
| Organic Growth | 10 |
| Gross Margin | 8 |
| Operating Margin | 10 |
| FCF Growth | 12 |
| FCF Margin | 10 |
| ROIC | 12 |
| Balance Sheet | 8 |
| Moat | 12 |
| Management / Capital Allocation | 8 |
| **Total** | **100** |

| 分数 | 评级 |
|---|---|
| 90–100 | Exceptional |
| 80–89 | Excellent |
| 70–79 | Good |
| 60–69 | Average |
| <60 | Weak |

**分数不是结论，趋势才是。**

> **[D-10] 评分锚已写进代码。** 权重表光看像量化，实际是主观打分 —— 同一公司两个人打分会不同，
> 同一人两次也会不同。现在每一项的阈值锚固定，用 `py scripts/alpha_score.py score ...` 计算，
> **同一组输入必然得到同一分数**。查锤子：`py scripts/alpha_score.py anchors`。
> 写报告时应附上输入值，否则分数不可追溯。

### 3.12 Fundamental Trend
- **↑ Accelerating**：Revenue / Margin / FCF / ROIC / Moat 多数改善
- **→ Stable**：核心指标稳定
- **↓ Deteriorating**：多个核心指标恶化

### 3.13 生命周期

| Stage | 特征 |
|---|---|
| 1 Early | 市场空间大、收入小、模式待验证 |
| 2 High Growth | 收入高增长、份额提升、Margin/ROIC 改善 |
| 3 Scale | 增长放缓但 FCF 高速增长、规模优势明显 |
| 4 Mature | 低增长、高现金流、回购分红重要 |
| 5 Decline | Revenue / Margin / ROIC / Moat 持续恶化 |

### 3.14 四种基本面状态

| 类型 | 特征 | 含义 |
|---|---|---|
| **A ★★★★★** | Revenue↑ Organic↑ Margin↑ FCF↑ ROIC↑ Moat↑ | 基本面加速改善 —— **最值得寻找** |
| **B ★★★★** | 各项稳定，FCF 稳步增长 | 成熟优秀公司 |
| **C ★★★** | Revenue↑ EPS↑ 但 FCF→ ROIC↓ Margin↓ | 表面增长、内部质量恶化 —— 谨慎 |
| **D ★–★★** | Revenue↓ Margin↓ FCF↓ ROIC↓ Debt↑ Moat↓ | 基本面恶化 —— 下跌不是买入理由 |

### 3.15 三色信号
- 🟢 **Revenue ↑ + Margin ↑ + FCF ↑** —— 最漂亮的组合
- 🟡 **Revenue ↑ + FCF ↓** —— 先查 CapEx / 库存 / 应收 / 并购。有解释可接受；无解释则警惕
- 🔴 **Revenue ↑ + ROIC ↓ + FCF ↓** —— 最危险的增长

---

## 4. Module 02 — Valuation Engine

> 回答：**公司很好，但现在是不是太贵？**

### 4.1 必须先建 Base Case，且写明假设
必填：Revenue CAGR / Margin / EPS / FCF / FCF Margin / Shares Outstanding / Net Debt / Terminal Multiple。

**不允许只给一个目标价。**

### 4.2 三情景

| 情景 | 定义 | 必须写明 |
|---|---|---|
| **Bear** | 核心增长逻辑部分失败 | 概率、Revenue、EPS、FCF、Multiple、Fair Value、关键假设 |
| **Base** | 最合理、概率最高 | 同上 |
| **Bull** | 核心逻辑明显超预期 | 同上 |

给出概率后必须计算**概率加权价值**，不要只比较单点。

### 4.3 估值方法选择

| 公司类型 | 首选方法 |
|---|---|
| 成熟稳定现金流 | P/FCF、DCF |
| 高增长软件 | EV/Revenue + Rule of 40、P/FCF（前瞻） |
| 重资产制造 / 半导体 | EV/EBITDA、P/B + ROIC、P/FCF（normalized） |
| 高 CapEx 扩张期 | **Normalized FCF**（不用当期 FCF） |
| 多业务混合体 | **SOTP**（分部估值后加总） |
| 金融 / 地产 | P/B、ROE、股息贴现 |

**规则**：周期性公司与重 CapEx 公司**不得**直接用当期 FCF 或当期 PE 估值，必须用 normalized 口径。

### 4.4 反推市场隐含预期（Alpha Radar 的关键功能）

```text
给定当前股价 → 反推：市场假设了什么增长率 / 利润率 / 退出倍数？
```
必须明确写出"市场已经提前定价了什么"，而不是简单说"贵"。

推荐做法：解出使 `当前股价 = 目标价` 所需的 EPS 或增速，与自己的 Base Case 比较。

### 4.5 当前价格的年化回报

```text
5年年化回报 = (目标价 / 当前价)^(1/5) − 1  + 股息率
3年年化回报 = (目标价 / 当前价)^(1/3) − 1  + 股息率
```

必须同时给出 **上行空间 / 下行空间 / 赔率**（赔率 = 上行 ÷ 下行）。

### 4.6 输出
- 2027 Fair Value、2030 Fair Value
- Bear / Base / Bull Price、概率加权价
- 当前隐含情景（Bear / Base / Bull）
- Margin of Safety
- Valuation Status：`Deep Undervalued / Undervalued / Fair / Expensive / Extremely Expensive`

---

## 5. Module 03 — Decision Engine

> 回答：**所以现在到底应该干什么？**

### 5.1 决策输入
```text
公司质量 × 基本面趋势 × 估值 × 预期回报 × 风险 × 当前股价
```

### 5.2 八种动作

| 动作 | 含义 |
|---|---|
| **Watch** | 值得研究，但无安全边际 |
| **Starter** | 建立观察仓 |
| **Buy** | 进入合理买入区 |
| **Strong Buy** | 明显安全边际 |
| **Core** | 适合长期核心仓位 |
| **Hold** | 继续持有 |
| **Trim** | 估值明显超过基本面 |
| **Exit** | 基本面结构性恶化 / 逻辑失效 |

### 5.3 价格纪律（每家公司必须给出具体数字）

| 股价区间 | 动作 | 建议仓位 |
|---|---|---:|
| > Trim 线 | 明显偏贵，不追 | 0–10% |
| Trim 线附近 | 偏贵 | 10–15% |
| Fair 区间 | 合理但安全边际低 | 15–20% |
| **Starter 区** | 开始建仓 | 25–35% |
| **Buy 区** | 比较舒服 | 40–55% |
| **Strong Buy 区** | 很有吸引力 | 60–75% |
| **Heavy 区** | 强烈关注 | 75–90% |
| 极端低估 | 若基本面未坏，重仓 | 90–100% |

### 5.3b 赔率硬规则（[D-11] 已入代码）

上表是**价格**维度。**仓位还必须过赔率这一关**，两者是独立的约束：

```
赔率 = 上行空间 / 下行空间

赔率 < 1:1        →  不建仓（0%），不因"公司很优秀"而豁免
赔率 1.0–1.5:1    →  5–10%
赔率 1.5–2.5:1    →  10–20%
赔率 2.5–4.0:1    →  20–35%
赔率 ≥ 4.0:1      →  35–50%

最终仓位 = 档位 × 置信度系数（Low 0.5× / Medium 0.8× / High 1.0×）
上限约束：单标的不得超过组合上限（默认 25%）
```

```bash
py scripts/alpha_score.py size --odds 0.5 --confidence High          # → 不建仓
py scripts/alpha_score.py size --odds 3.9 --confidence Medium --max-weight 25
py scripts/alpha_score.py size --odds 3.9 --confidence Medium --current-weight 12
```

> **为什么必须有这条硬规则：** 旧版的仓位阶梯只依赖价格，导致赔率 0.5:1 和 3.9:1 的标的用同一张表。
> APH 就是那个反例 —— 基本面 9/10，但赔率 0.5:1，所以正确动作是 **Watch 而非 Buy**。
> 这条规则把"好公司"和"好价格"彻底拆开，也把铁律 1 变成了代码。

### 5.4 两类触发条件必须分开写

```text
价格触发条件   （例如：<$40 开始建仓）
基本面失效条件 （例如：LEAP 增速转负 + FCF 连续 2 年恶化 + ROIC 跌破 WACC）
```
> **价格下跌本身永远不是加仓理由；只有"价格下跌 + 基本面未坏"才是。**

---

### 5.4 辅助计算器 —— `scripts/alpha_score.py`

三个缺陷（D-10 / D-11 / D-12）对应的可执行工具：

```bash
# [D-10] 评分锚：查看全部阈值 → 保证分数可复现
py scripts/alpha_score.py anchors

# [D-10] 按固定阈值锚算 Fundamental Score
py scripts/alpha_score.py score --revenue-growth 8 --organic-growth 6 \
    --gross-margin 39 --operating-margin 28 --fcf-growth 22 --fcf-margin 19 \
    --roic 20.2 --net-debt-ebitda 2.1 --moat 4.2 --management 4.0

# [D-11] 仓位（赔率<1 一律返回不建仓）
py scripts/alpha_score.py size --odds 3.9 --confidence Medium \
    --max-weight 25 --current-weight 12

# [D-12] 快速筛查（三项输入，15 分钟筛掉 90%）
py scripts/alpha_score.py lite --revenue-growth 18 --moat-trend up --valuation-pct 45 \n    --roic 22.9 --fcf-margin 39.7
```

**`score` 的十项输入**（与 §3.11 权重表一一对应）：
`--revenue-growth` `--organic-growth` `--gross-margin` `--operating-margin` `--fcf-growth`
`--fcf-margin` `--roic` `--net-debt-ebitda` `--moat`（0-5）`--management`（0-5）。
缺项会被标出，且提示"该分数不可与其他公司直接比较"。

**`size` 的选项**：`--odds` `--confidence` `--max-weight` `--current-weight`。

**`lite` 的选项**：`--revenue-growth` `--moat-trend`（up/flat/down）`--valuation-pct`，
以及两个**可选质量修正** `--roic` `--fcf-margin`（[D-52]）。
输出五种结论：✅ 升级到完整分析 / 🔍 值得跑全流程 / 👀 只进观察名单 / ⏸ 不投入 / ❌ 放弃。

> **[D-52] 为什么需要质量修正**：INTU 的 91% 评分项拉满（81% 毛利、22.9% ROIC、39.7% FCF 利润率），
> 却因收入增长 13.9% < 15% 的"加速"阈值被 Lite 判为"不投入深度研究"。
> 现在：ROIC ≥20% 且 FCF Margin ≥25% 时，增长阈值从 15% 降至 **10%**。
> **Lite 是粗筛，不是结论** —— 若与完整分析矛盾，以完整分析为准。

> **使用顺序**：先用 `lite` 过一遍观察名单，只对✅的跑完整 Alpha Radar；
> 跑完用 `score` 得可复现的基本面分；最后用 `size` 把赔率转成仓位上限。

### 5.4b 规则化情景 —— 何时用、何时必须声明无效（[D-66/D-67]）

对**没有现成行业研究**的标的，手拍 Bull/Base/Bear 会引入主观性。`alpha_scenario.py` 用写死的规则生成：

```text
g_bull = clamp(TTM Revenue YoY × 0.9, 0, 规模上限)
g_base = clamp(TTM Revenue YoY × 0.5, 0, 规模上限 × 0.6)
g_bear = min(TTM Revenue YoY × 0.1, 0)

规模上限（体量越大，可持续增速越低）：
  <$10B → 25%   <$100B → 18%   <$1T → 12%   ≥$1T → 8%

利润率系数：Bull ×1.10 / Base ×1.00 / Bear ×0.90
倍数系数  ：Bull ×1.20 / Base ×1.00 / Bear × [0.70 − min(0.30, max(0,ND/EBITDA)×0.05) − (0.10 if FCF<0)]

价值 = 当前市值 × (1+g)^5 × 利润率系数 × 倍数系数      概率 25/50/25
```

**已知的结构性缺陷（必须写进档案）：**

> 规则只看「**市值规模 + TTM 增速 + 杠杆 + 是否烧钱**」，
> **完全不看行业地位、竞争格局、技术路线或管理层。**
> 实测：它会把 **NVDA 与 GOOGL 按同一增速上限（8%）处理** —— 这显然没有信息量。

**四类公司上必须声明赔率输出无效：**

| 类型 | 例子 | 为什么无效 |
|---|---|---|
| pre-revenue | OKLO、SPCX | 无收入 → 规则无输入 |
| 零增长现金牛 | QCOM | 规则只看增长，不看股东回报 |
| 收入崩塌中 | NVTS | 规则无法表达"基本面恶化" |
| ADR 市值不可靠 | ASX、UMC | 普通股股数 × ADS 价格 ≠ 市值 |

**纪律**：用规则情景的档案，**不登记预测** —— 规则没有表达任何行业观点，
因而不具备"可被未来数据证伪"的资格，登记它会污染预测账本。
动作一律 **Watch（需研究后再决策）**。

### 5.4c 两类档案的等级区分（[D-66] vs 研究级）

| 等级 | 情景来源 | 能否登记预测 | 动作 |
|---|---|---|---|
| **研究级** | 以**一致预期为锚** + 显式折扣假设（或行业研究报告） | ✅ 可以 | Hold / Buy / Trim |
| **规则级** | `alpha_scenario.py` 机械规则 | ❌ **不可以** | Watch |

> **实测差异可达 4 倍**：ORCL 规则级赔率 0.65:1（CAGR 6.8%），研究级 2.71:1（CAGR 19.5%）。
> 规则级把 ORCL 当"高杠杆成熟公司"惩罚；研究级看到"一致预期认为收入会翻 1.83 倍"。
> **这个差异就是"为什么必须做研究级分析"的最好论据。**
>
> 但反过来也成立：**研究级把结论押在一致预期上，而一致预期可能系统性偏高。**
> 所以研究级档案必须写明"对一致预期的折扣假设"，并把它列为最大单点风险。

### 5.4c2 [D-73] 持仓的分级敏感度（两级）

| 文件 | 内容 | 是否入库 | 用途 |
|---|---|---|---|
| **`data/holdings.json`** | **只含标的**（tickers） | ✅ 可公开 | 判断"持有/未持有"与"持仓 vs 分析结论是否冲突" |
| `data/positions.json` | 含数量/成本/盈亏 | ❌ gitignore（仅本地） | 仓位% / 盈亏% |

```bash
py scripts/alpha_portfolio.py sync         # 默认**只写标的**（可公开）
py scripts/alpha_portfolio.py sync --full  # 额外写含数量的本地快照（⚠️ 勿公开）
```

> **设计要点**：公开站点**能显示冲突标记，但不显示数量**。
> 实测公开版：16 个「持有」标记 + 3 个「🔴 冲突」标记，**数量类字段 0 处**。
>
> **更根本的原则**：安全的保障是"**敏感数据根本不进仓库**"，而不是"构建时过滤掉"。
> `positions.json` 从未入库，所以 CI 根本读不到数量 —— 这比任何过滤都可靠。

### 5.4d 静态站点 —— 只读呈现（[D-70]）

产出 `site/index.html`：**单文件、零外部依赖、可离线打开、可直接上 GitHub Pages**。

| 页签 | 内容 |
|---|---|
| 组合雷达 | 19 家分析结论（可搜索）+ KPI（报告级/研究级/规则级、赔率 ≥1 数） |
| 公司档案 | 19 份档案卡片，**按等级过滤** + 全文搜索 + 点开阅读 |
| 预测账本 | 93 条预测，可排序筛选 |
| 决策记录 | 7 条决策 |
| 缺陷登记册 | DEFECTS.md 全文 |
| 方法论 | 九条铁律 + 三类档案等级 + 七道门禁 + 四层校验 |

**三条设计纪律（重要）：**

1. **只读**。站点**不提供任何写操作** —— 写必须走 `alpha_portfolio.py` / `alpha_ledger.py`，
   因为那些命令带 append-only、自动 git 固化、单位/版本校验三层纪律。
   **一个"方便"的界面能把这些纪律打穿。**
2. **不生成"分析"**。站点只呈现已写好的档案，**不调用 `alpha_scenario.py` 产生新"报告"**。
   规则级结果明确标注等级，不与研究级混淆。
3. **默认不含持仓**。`data/positions.json` 默认**不读**；`--include-holdings` 才包含，
   且页面顶部会打红标。构建时还有一道断言：公开版若含持仓字段则**中止构建**。

> **由 [G8] 门禁守护**：每次跑门禁都会重新构建站点并断言"无数量类字段"。
> 仓库是公开的 —— 这条门禁防的是"不小心把账户明细推到 Pages 上"。

### 5.4d2 可读性下限（[D-76]）—— 面向视力不佳者

改造前实测的问题：

| 问题 | 实测 |
|---|---|
| 字号过小 | **11 个文字元素里 10 个 ≤13px**（table 13 / th 11 / pill 11 / .g 10 / pre 12 / nav 13） |
| 对比度不达标 | 浅色主题 `--mut` 在 `--bg` 上仅 **4.33:1**，低于 WCAG AA 的 4.5 |
| 行宽过长 | `main` 1590px ÷ 15px ≈ **106 字/行**，远超中文建议的 ≤40 字 |

**做法**：不改原配色与布局，只加一层 `A11Y_CSS`，做四件事：

1. **字号**：引入 `--fs` 变量（默认 **19px**），所有元素按 `calc(var(--fs) × 系数)` 缩放；
   **兜底规则** `font-size:max(calc(var(--fs)*0.79), 15px)` —— 任何文字都不低于 15px
2. **用户可控**：页头有 `A−` / `A`（重置）/ `A+` 三个按钮，范围 **15–32px**，存 `localStorage`
3. **对比度**：浅色 `--mut` 加深至 `#4a5a55` → **6.75:1**（✓ AA）；深色 → 9.90:1
4. **行宽**：`.dossier{max-width:52ch}` —— 表格仍满宽可横向滚动

附加：高对比度模式开关（`◐`，纯黑白 + 黑/白边框）、表格斑马纹、数字列不换行、
点击目标 ≥44px、`aria-label` 标注、尊重 `prefers-reduced-motion`。

> **由 [G8] 门禁守护**：断言 9 项可读性特征未被改回去
> （字号变量 / 最小字号兜底 / 调节控件 / 高对比开关 / 持久化 / 对比度修正 / 行宽 / reduced-motion / aria）。
> 理由：这类回归**没有任何其他信号** —— 页面照样能跑，只是变难读。

### 5.4e 部署 —— 本地与 CI 共用同一条路径（[D-75]）

```bash
py scripts/pages_build.py --with-gates --strict   # ← CI 用的就是这条命令
```

`.github/workflows/pages.yml` 只做两件事：**调用上面这条命令** + **上传产物**。

> **为什么这样设计**：如果 CI 与本地跑的是**不同的命令序列**，
> 那么"本地通过"推不出"CI 通过"，验证就**被迫依赖 Actions**，反馈回路变长。
> 收敛成同一个入口后：**本地跑通 ⟺ CI 跑通**（CI 只多一步上传）。
> 实测价值：第一次跑本地就抓到 G5 文档漂移 —— **push 之前就修掉了**。

**产物不入库**：`site/` 已 gitignore，由 CI 构建。本地看预览：
`py scripts/build_site.py` 后用浏览器打开 `site/index.html`。

### 5.5 组合层 —— Radar Board（[D-13]）

单公司分析的局限：它回答不了「**我持有的这些，和我自己的分析结论一致吗**」。

```bash
py scripts/alpha_portfolio.py board   # 组合雷达
py scripts/alpha_portfolio.py check   # 只列冲突
```

**一致性判定**（持仓 × 分析结论）：

| 标记 | 含义 |
|---|---|
| 🔴 | **持有中，但赔率 <1 且分析为 Watch/Trim/Exit** —— 持仓与自己的分析矛盾 |
| ✅ | 持有中，分析为 Buy/Starter 且赔率 ≥1 |
| 🟡 | 持有中，分析与持仓方向不一致（非硬冲突） |
| 💡 | **未持有，但赔率 ≥1 且分析为 Starter/Buy** —— 达标却空仓 |
| ⚪ | 未持有，赔率 <1 |
| ❓ | 无分析档案 |

> **🔴 项必须显式处理，二选一：**
> **a) 调仓** —— 记录 `sell`；**b) 修订分析** —— 用新证据重跑 Alpha Radar，
> 并用 `analysis` 命令登记新结论（不覆盖旧记录）。
> **不能两头都算数** —— 这是铁律 4（价格变化与基本面变化分开）在组合层的落地。

**集中度**：输出 Top1/Top3/Top5 与 **HHI**。
> ⚠️ **HHI 只衡量权重分散度，不衡量相关性。** 若多个持仓是同一主题（如 AI/半导体），
> 实际风险远高于 HHI 所示。所以集中度必须与**主题**一起看，不能只看 HHI。

**持仓数据来源优先级**：券商快照（`sync` 写入 `data/positions.json`）> 手工交易流（`data/transactions.jsonl`）。
> API 给的是**当前持仓状态**（含 avg_cost / realized_pnl），不是交易流水 ——
> 按「买入交易」导入会捏造不存在的历史，且重复导入会重复计。

**凭据管理**：`FUTU_API_USER` / `FUTU_API_PASS` 环境变量，或 `data/.futu_auth`（已在 `.gitignore`）。**一律不入库。**

---

## 6. Module 04 — Prediction Ledger｜预测账本

> 回答：**我们当初到底预测了什么？**

### 6.1 铁律
**旧预测永不覆盖。** 所有记录追加写入 `data/predictions.jsonl`，新判断产生 v2 / v3。

**同版本内不得改数** —— 尝试用同一 `--version` 写入不同数值会被拒绝，强制你升版本。这是防止"悄悄修正历史"的护栏。

### 6.1b 指标词表（v1.1 强制）

指标名必须命中词表，写错立刻报错，**不再静默失配**。用 `alpha_ledger.py metrics` 查看全表，支持中英文别名自动归一。

| 类别 | 指标 | 是否计入预测能力评分 |
|---|---|---|
| **fundamental**（可被财报验证） | Revenue / Organic_Growth / Gross_Margin / Operating_Margin / Net_Margin / EPS / FCF / FCF_Margin / Cash_Conversion / ROIC / CapEx / Net_Debt_EBITDA / Shares / Backlog / Book_to_Bill | ✅ 计入 |
| **valuation**（依赖自身估值假设，弱可验证） | FairValue / Target_Price / Exit_Multiple | ❌ 不计分，只做对照 |

常用别名（自动归一）：`Revenues`/`sales`/`营收` → Revenue；`毛利率` → Gross_Margin；`自由现金流` → FCF；`fv` → FairValue。

> **为什么区分两类：** FairValue 取决于你自己选的退出倍数，**不可观测**，把它混进"预测能力"评分是自欺。可验证的只有基本面量。

### 6.1c 单位纪律（v1.1 强制）

录入实际值时，unit 必须与预测一致。不一致会被**拒绝**（可用 `--force` 强制录入，但会在报告中留痕并被排除出所有评分与对比）。

跨国标的必须写汇率假设：
```bash
--fx "TWD/USD=32.0"
```
> ASX 就是典型：财报 TWD、ADR 价格 USD。没有汇率假设，三年后无法复盘目标价。

### 6.2 数据结构

```json
{
  "record_type": "prediction",
  "ticker": "APH",
  "analysis_date": "2026-10-07",
  "forecast_version": "v1",
  "scenario": "Base",
  "metric": "Revenue",
  "metric_kind": "fundamental",
  "forecast_period": "2030",
  "forecast_value": 45000000000,
  "unit": "USD",
  "probability": 0.45,
  "confidence": "Medium",
  "thesis": "AI datacom + CommScope 并表",
  "source_basis": "10-Q Q2 2026 + 一致预期",
  "logged_at": "2026-10-07T15:30:00"
}
```

`probability` 为该情景概率（0–1，可选但建议填 —— 三情景之和应为 1）。

实际值写入 `data/actuals.jsonl`：

```json
{
  "record_type": "actual",
  "ticker": "APH",
  "metric": "Revenue",
  "period": "2030",
  "actual_value": 43100000000,
  "unit": "USD",
  "actual_date": "2031-02-01",
  "source": "10-K FY2030"
}
```

### 6.3 使用

```bash
# 查看指标词表
py scripts/alpha_ledger.py metrics

# 记录预测（建议三情景都记，并填概率；--prob 0-1）
py scripts/alpha_ledger.py predict --ticker APH --scenario Base --metric Revenue \
    --period FY2030 --value 45e9 --unit USD --prob 0.45 --confidence Medium \
    --thesis "AI datacom + CommScope 并表" --basis "10-Q Q2 2026 + 一致预期"

# 记录实际值（单位必须与预测一致；跨国标的带 --fx；可同时给 --attribution）
py scripts/alpha_ledger.py actual --ticker APH --metric Revenue \
    --period FY2030 --value 43.1e9 --unit USD --date 2031-02-01 \
    --source "10-K FY2030" --attribution Demand

# [D-05] 记录决策（append-only，不可修改；改主意记新的一条）
py scripts/alpha_ledger.py decision --ticker APH --action Watch \
    --price 88.62 --currency USD --odds 0.5 --fair-value 125 \
    --weight 0 --reason "赔率 0.5:1，价格已把高增长定价进去"

# [D-05] 列出决策历史
py scripts/alpha_ledger.py decisions --ticker APH

# [D-06] 哪些预测到期该复盘了
py scripts/alpha_ledger.py due --ticker APH --asof 2031-06-01 --lag 75

# [D-09] 事后补记归因（不覆盖 actual）
py scripts/alpha_ledger.py attribute --ticker APH --metric Revenue \
    --period FY2030 --attribution Margin --note "毛利率比预期低 2pp"

# 列出某公司全部预测版本
py scripts/alpha_ledger.py list --ticker APH

# 预测 vs 实际 报告（--price 用于算决策回报，可重复；--save/--out）
py scripts/alpha_ledger.py report --ticker APH --price APH=92.5 --save --out review_APH.md

# 修订预测：必须升版本，同版本改数会被拒绝
py scripts/alpha_ledger.py predict --ticker APH --scenario Base --metric Revenue \
    --period FY2030 --value 60e9 --unit USD --version v2 --thesis "上调：AI CapEx 超预期"

# 导出 CSV 便于人工审阅
py scripts/alpha_ledger.py export
```

**常用选项速查：**

| 子命令 | 关键选项 |
|---|---|
| `predict` | `--ticker` `--metric` `--period` `--value` `--unit` `--scenario` `--prob` `--confidence` `--version` `--date` `--thesis` `--basis` `--informational` |
| `actual` | `--ticker` `--metric` `--period` `--value` `--unit` `--date` `--source` `--fx` `--attribution` |
| `decision` | `--ticker` `--action` `--price` `--currency` `--weight` `--prev-weight` `--odds` `--fair-value` `--thesis` `--reason` `--date` |
| `decisions` | `--ticker` |
| `due` | `--ticker` `--asof` `--lag` |
| `attribute` | `--ticker` `--metric` `--period` `--attribution` `--note` |
| `list` | `--ticker` |
| `report` | `--ticker` `--price` `--save` `--out` |

**报告结构（v1.2，共 9 节）：**

| 章节 | 内容 | 是否计入预测能力 |
|---|---|---|
| 1. 主评分 | Base Case vs 实际 | ✅ **唯一计分区** |
| 2. 概率加权预测 vs 实际 | Σ(概率×预测值)，[D-08] | ❌ 参考 |
| 3. 情景区间命中 | 实际落在哪一段、是否出区间 | ❌ 独立统计 |
| 4. 历史版本对照 | v1 / v2 / … 各自 vs 实际 | ❌ |
| 5. 估值输出对照 | FairValue / Target_Price | ❌ 弱可验证 |
| 6. 预测能力 | 按 Ticker+Metric+币种分组 | ✅ 汇总 |
| 7. 误差归因分布 | 我最常犯哪类错误，[D-09] | ❌ |
| 8. 决策 vs 结果 | 决策价 → 回报/年化/赔率纪律，[D-05] | ❌ |
| 9. 单位强制覆盖留痕 | | ❌ |

### 6.3b 三个数据库的职责

| 库 | 文件 | 回答的问题 |
|---|---|---|
| **Company** | `analysis/<TICKER>_AlphaRadar.md` | 公司现在是什么 |
| **Forecast** | `data/predictions.jsonl` + `data/actuals.jsonl` | 我们预测了什么，实际如何 |
| **Decision** | `data/decisions.jsonl` | 当时在什么价格决定了什么动作，纪律遵守了吗 |

> [D-05] 之前只实现了 Company 与 Forecast，Decision 库完全缺失 ——
> 导致无法回答最关键的问题：*"我当时在 $88.62 决定了 WAIT，纪律遵守了吗？"*
> 现在 `report` 第 8 节会直接标出**违反赔率纪律**的决策。


### 6.4 每次分析的必录字段
至少记录 **Revenue / EPS / FCF** 的 Base Case，以及 Base Case 的 **2030 目标价**与 **Starter 价格**。
> 只记录目标价而不记录财务预测，等于无法复盘。

---

## 7. Module 05 — Review Engine｜复盘引擎

> 回答：**后来到底对不对？错在哪里？**

### 7.1 Actual vs Forecast

```text
Forecast Error = (Actual − Forecast) / Forecast
```

**⚠️ 只对 Base Case 计分。** 这是 v1.1 最重要的修正。

原因：如果允许在 Bear/Base/Bull 三个预测里事后挑最接近实际的那个来打分，那么三情景就变成了**永远准**——你会给自己虚假的自信，并据此放大仓位。

> **实测反例：** Base 预测 1.00B、实际 1.55B（偏 **+55%**）。旧逻辑事后挑选 Bull（1.60B）作为评分依据，输出"-3.1%、A 级"。
> 修正后正确输出 **+55.0%、D 级**，同时**独立地**报告"实际落在 Base~Bull 之间，区间内"。

### 7.1b 情景区间命中率（独立指标）

三情景的正确用途不是评分，而是回答：**"我的不确定性刻画对不对？"**

```text
区间命中率 = 实际落在 [Bear, Bull] 内的次数 / 已兑现情景总数
```

| 命中率 | 含义 | 行动 |
|---|---|---|
| > 85% | 区间可能过宽 | 收窄，敢于集中 |
| 70–85% | 合理 | 保持 |
| < 70% | **区间过窄** | Bear 不够悲观 / Bull 不够乐观，需重新设定 |

> **Base 误差 与 区间命中率 必须分开看。**
> "Base 偏 55% 但落在区间内" = 你的方向判断对、中心估计偏；
> "Base 偏 3% 但跌出区间" = 你在自欺（区间画得太窄，实际是运气）。

### 7.2 误差归因（9 类，必须选一个）

| # | 归因 | 含义 |
|---|---|---|
| 1 | **Demand Error** | 市场需求判断错误 |
| 2 | **Market Share Error** | 市占率判断错误 |
| 3 | **Margin Error** | 利润率判断错误 |
| 4 | **CapEx Error** | 资本开支判断错误 |
| 5 | **Management Error** | 管理层执行偏差 |
| 6 | **M&A Error** | 并购判断错误 |
| 7 | **Macro Error** | 宏观 / 利率 / 周期 |
| 8 | **FX Error** | 汇率 |
| 9 | **Valuation Error** | 公司对了，但市场给的估值错了 |

### 7.3 Thesis 状态（四选一）

| 状态 | 含义 |
|---|---|
| **Intact** | 投资逻辑保持 |
| **Strengthening** | 投资逻辑增强 |
| **Weakening** | 投资逻辑减弱 |
| **Broken** | 核心逻辑失效 |

检查项：Growth Driver / Moat / Market Share / Margin / FCF / ROIC / Capital Allocation / Competitive Position

### 7.4 三类准确率必须分开记录

```text
Fundamental Accuracy  基本面预测准不准？（Revenue / EPS / FCF / Margin 误差，只算 Base）
Moat Accuracy         护城河判断准不准？
Investment Accuracy   投资决策赚不赚钱？（买入价、目标价、实际价、年化收益、最大回撤）
```
> **预测正确 ≠ 投资正确。** 公司基本面完全符合预测，但买得太贵，投资回报仍然可能很差。
>
> 注：`FairValue` 类属于 Investment Accuracy 的检验对象，不进 Fundamental Accuracy。

### 7.5 误差归因（[D-09] 已入代码）

归因不再只写在 markdown 里 —— 它进了 `actuals.jsonl`，可被自动汇总。

```bash
# 录入实际值时直接给归因
py scripts/alpha_ledger.py actual --ticker APH --metric Revenue --period FY2030 \
    --value 43.1e9 --unit USD --attribution Demand

# 事后补记（不覆盖 actual）
py scripts/alpha_ledger.py attribute --ticker APH --metric Revenue \
    --period FY2030 --attribution Margin --note "毛利率比预期低 2pp"
```

可选值：`Demand` / `MarketShare` / `Margin` / `CapEx` / `Management` / `M&A` / `Macro` / `FX` / `Valuation`
（中文别名自动归一：`需求` → Demand、`毛利率` → Margin…）

`report` 第 7 节给出**归因分布**，并直接标出"当前最大错误来源"。

> **这是复盘引擎最高价值的输出**：它告诉你该修的是需求判断、利润率判断、还是估值判断。
> 哪个归因占比最高，下一轮就把资源投到那里。

### 7.6 财报后的标准动作

```text
0. py scripts/alpha_ledger.py due            # 先看哪些预测到期了（[D-06]）
1. 取实际数据（一手申报）
2. alpha_ledger.py actual 记录实际值 + --attribution 归因
3. alpha_ledger.py report 生成对照（自动 git 固化）
4. 判断 Thesis 状态
5. 更新预测 → 新版本 v(n+1)，不覆盖旧版本
6. 重新定价 → 更新价格带，并记一条新 decision
7. 在公司档案追加 "## Review" 段落（保留历史）
```

---

## 8. 标准公司档案

每家公司一个文件：`analysis/<TICKER>_AlphaRadar.md`（历史版本追加，不删除）

```text
# <TICKER> — Alpha Radar

Analysis Date:
Data Cutoff:
Current Price:
Evidence Sources:

## 1. Business
Business Model:
Revenue Sources:
Customers:
Market / TAM:
Competitors:

## 2. Fundamental
Revenue / TTM:
Organic Growth:
Gross Margin:
Operating Margin:
FCF:
FCF Margin:
Cash Conversion:
ROIC vs WACC:
Net Debt / EBITDA:
CapEx:
Shares Outstanding (净稀释?):

## 3. Moat
Moat Score: /10
Moat Trend: ↑ → ↓
Main Advantages:
Main Threats:

## 4. Lifecycle
Stage:
Reason:

## 5. Fundamental Score
Score: /100
Trend: ↑ → ↓
Type: A / B / C / D

## 6. Forecast
Bear (prob %):
Base (prob %):
Bull (prob %):
Probability-Weighted Fair Value:

## 7. Valuation
2027 Fair Value:
2030 Fair Value:
Current Implied Scenario:
Margin of Safety:
Upside / Downside / 赔率:

## 8. Decision
Starter:
Buy:
Strong Buy:
Heavy/Core:
Trim:
Exit:
Current Action:

## 9. Investment Thesis
Bull Thesis:
Bear Thesis:
Key Catalysts:
Key Risks:
Invalidation Conditions (基本面失效线):

## 10. Prediction Ledger
Forecast Version:
Prediction Date:
Forecast Horizon:
Ledger Entries:

## 11. Review
Actual vs Forecast:
Forecast Error:
Error Attribution:
Thesis Status:
Model Changes:
```

---

## 9. 标准研究输出（18 段，顺序固定）

1. 一句话结论
2. 数据截点与证据来源
3. 公司是什么（商业模式）
4. 为什么值得关注 / 不值得关注
5. 护城河（10 类评分 + 趋势）
6. 基本面趋势（↑ → ↓）
7. 生命周期 Stage
8. 财务质量（Margin / FCF / ROIC / 负债 / CapEx）
9. Bull / Base / Bear（含概率加权）
10. 当前市场隐含预期（反推）
11. 估值（2027 / 2030 Fair Value）
12. 当前价格年化回报 + 赔率
13. 买入价格带（Starter / Buy / Strong Buy / Heavy）
14. 减仓价格带（Trim / Exit）
15. 风险
16. Thesis Invalidation（基本面失效线）
17. Prediction Ledger（本次记录的预测）
18. 最终投资动作

---

## 10. 一页决策摘要（每次分析必须产出）

```text
🛰️ ALPHA RADAR — <TICKER>

━━━━━━━━━━━━━━━━━━━━━━━━
📅 数据截点:           当前价:

🏰 Fundamental   Score: /100   Trend: ↑/→/↓   Stage:
🏯 Moat          Score: /10    Trend: ↑/→/↓
📈 Revenue       TTM:          Organic:
💰 Margin        GM:           OM:            FCFM:
💵 FCF           FCF:          Cash Conv:     ROIC vs WACC:
🏦 Balance       Net Debt/EBITDA:             Interest Cov:
━━━━━━━━━━━━━━━━━━━━━━━━
🔮 2030 Forecast    Bear:      Base:      Bull:     加权:
💎 Valuation        2027 FV:   2030 FV:   隐含情景:
📐 赔率             上行:       下行:      赔率:
━━━━━━━━━━━━━━━━━━━━━━━━
🎯 Starter:    Buy:    Strong Buy:    Heavy:    Trim:    Exit:
📌 当前动作:
⚠️ 三条最大风险:
🔒 基本面失效线:
📒 本次记录预测: (已写入 predictions.jsonl / version vN)
━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 11. 工作流

### A. 首次分析一家公司
```text
0. [推荐] py scripts/alpha_score.py lite ...   # 先筛，不值得就不跑全流程
1. 取一手数据: py scripts/alpha_fetch.py <TICKER>   # [D-14] SEC 自动取数
2. 跑 Module 01 基本面 → py scripts/alpha_score.py score ... 得可复现分数
3. 跑 Module 02 估值 → 三情景 + 隐含预期 + 价格带
4. 写 Company Profile 到 analysis/<TICKER>_AlphaRadar.md
5. 跑 Module 03 决策 → py scripts/alpha_score.py size --odds <x> --confidence <y>
6. 调用 alpha_ledger.py predict 记录预测（含 --prob，不可省略）
7. 调用 alpha_ledger.py decision 记录本次动作（含 --price --odds）
8. 输出 18 段标准报告 + 一页决策摘要
```

### B. 财报后更新（最重要，别跳过）
```text
0. py scripts/alpha_ledger.py due        # [D-06] 先看哪些预测到期了
1. 取实际数据（一手申报）
2. alpha_ledger.py actual 记录实际值 + --attribution 归因
3. alpha_ledger.py report 生成对照
4. 判断 Thesis 状态
5. 更新预测为 v(n+1)，追加而非覆盖
6. 更新价格带与当前动作，并记一条新 decision
7. 在公司档案追加 "## Review" 段落（保留历史）
```

### C. 组合级扫描（每月/每季）
```text
1. 跑所有持仓 + 观察名单的 Review
2. 汇总预测能力评级（哪个指标我最不准）
3. 检查哪些标的进入/离开价格带
4. 检查是否有 thesis 转向 Weakening / Broken
```

---

### D. 门禁与编排（每次改完必须跑）

```bash
# 1) 全部门禁，串行（本地快速自检）
py scripts/gates.py --all

# 2) Herdr 并行编排（5 个门禁各占一个 pane，条件下等待）
bash scripts/herdr_ci.sh              # 跑 1 遍
bash scripts/herdr_ci.sh --repeat 3   # 跑 3 遍验证稳定性
bash scripts/herdr_ci.sh --keep       # 保留现场供人工查看
bash scripts/herdr_ci.sh --build A2   # 串行构建队列（人工批准项会拒绝）
```

**五个门禁：**

| ID | 门禁 | 检验什么 |
|---|---|---|
| G1 | 账本回归测试 | `test_ledger.sh` —— 63 项（P0-1/2/3 + P1-4/7 + P2-17 + 边界） |
| G2 | skill 副本同步 | 项目文件与 `~/.pi/agent/skills/` 是否漂移 |
| G3 | 真实数据完整性 | `data/*.jsonl` 可解析、条数不低于基线、无版本内数值冲突 |
| G4 | 语法 / 导入 | `py_compile` |
| G5 | **文档-CLI 漂移** | CLI 的子命令/选项是否都在 SKILL.md 中；文档提到的子命令是否真实存在 |
| G6 | **账本已固化进 git** | 工作树存在、`data/*.jsonl` 已跟踪且与 HEAD 一致、条数不低于基线 |
| G7 | **一手数据多层校验** | `verify_data.py --all --require-cross`：四层校验无 ❌ 硬错误 |

> **G5 不是附属品。** v1.0 出过一次事故：SKILL.md 写着"估值类不计分"，而 report 实际给 FairValue 打了 B 级 —— 文档和代码各说各话，没有任何机制能发现。G5 就是那个机制，它第一次跑就抓到了 3 处真实漂移。

> **G6 是铁律 5 的技术保障。** [D-18] 之前，「旧预测永不覆盖」只是口头约定 ——
> `predictions.jsonl` 可被任何文本编辑器静默改写。现在还加了写入即自动 commit（[A1]）：
> 每次 `predict` / `actual` / `decision` 落盘后自动提交，提交信息形如
> `ledger(prediction): APH Revenue 2030 Base`。
> 测试环境不会触发（`ALPHA_RADAR_HOME` 指向临时目录时自动禁用）。

**编排规则（不要违反）：**

1. **并行只用于只读门禁。** 构建任务（改 `alpha_ledger.py`）必须串行 —— 同一文件并发写入会互相覆盖。
2. **条件用哨兵，不猜输出。** 每个门禁结束时打印 `__GATE_PASS__ <ID>` / `__GATE_FAIL__ <ID>`，编排器用 `herdr pane wait-output --regex` 等待。
3. **pane 侧命令必须跨 shell 安全。** Herdr 新建 tab 的根 pane 可能是 PowerShell，那里 `bash` 会落到 WSL 占位符（`C:\Windows\System32\bash.exe`）并报"没有已安装的分发版"。所以 pane 里一律用 `py scripts/gates.py ...`。
4. **先跑 canary。** 用最快门禁（G4）验证"pane 起得来 + 哨兵能回"，失败即中止，避免错误配置以"等待超时"的形式浪费几分钟。
5. **需人工批准的任务永不自动跑。** 例如 `git init`（改变仓库形态）。

---

## 12. 目录结构

```text
D:/pi/select_stock/
├── Alpha_Radar_SKILL.md              # 本文件
├── Investment_Bottom_Up_Research_SKILL.md
├── templates/
│   ├── Company_Profile_Template.md
│   ├── Review_Template.md
│   └── prediction_ledger.csv         # CSV 示例（机器源为 jsonl）
├── scripts/
│   ├── alpha_ledger.py               # 预测账本 + 决策库 + 复盘引擎
│   ├── alpha_score.py                # 评分锚 / 仓位 / Lite
│   ├── alpha_fetch.py                # [D-14] SEC 自动取数
│   ├── alpha_metrics.py              # 一手指标计算（TTM/Margin/FCF/ROIC）
│   ├── alpha_quote.py                # [D-29] 行情快照（yfinance 备选源）
│   ├── verify_data.py                # [G7] 四层数据校验（含外部交叉）
│   ├── alpha_portfolio.py            # [D-75] 站点构建的【唯一入口】—— 本地与 CI 共用同一条路径
py scripts/pages_build.py                  # 构建 + 安全断言
py scripts/pages_build.py --with-gates     # 再跑全部 8 道门禁（CI 用这个）
py scripts/pages_build.py --strict         # 任一失败即非零退出

# [D-70] 静态站点（只读快照，可离线打开 / 可上 GitHub Pages）
py scripts/build_site.py                     # 默认：不含持仓（可公开）
py scripts/build_site.py --include-holdings  # 🔴 含持仓，不要公开
py scripts/build_site.py --with-gates        # 同时嵌入最近一次门禁结果
py scripts/build_site.py --out site/index.html

# [D-68] 一致预期（分析师预测）—— 研究级情景的必要输入
py scripts/alpha_quote.py NVDA --estimates
py scripts/alpha_quote.py NVDA --estimates --json
#   流程：fc.yahoo.com 取 cookie → /v1/test/getcrumb 取 crumb → 带两者请求
#   返回：目标价(均值/区间/家数)、评级、前瞻 PE、各期 EPS/收入一致预期
#   实测与原始报告完全吻合（ITRI $129.56 / INTU $405.60 / NOW $146.73）→ 数据源可信

# [D-66] 规则化情景（无行业研究时的占位，明确标注为低置信度）
py scripts/alpha_scenario.py NVDA
py scripts/alpha_scenario.py NVDA --json

# [D-13] 持仓与组合雷达
│   ├── gates.py                      # 门禁运行器（跨 shell）
│   ├── gates_data_integrity.py       # G3
│   ├── gates_git_frozen.py           # G6 [D-18]
│   ├── check_doc_cli.py              # G5 文档-CLI 漂移自检
│   ├── test_ledger.sh                # G1 回归测试（63 项）
│   ├── sync_skills.sh                # G2 skill 同步
│   └── herdr_ci.py                   # [D-28] Herdr 并行编排器（跨 shell）
├── .gitignore / .gitattributes       # [D-18] 账本版本控制
├── data/                             # 机器可读、append-only
│   ├── predictions.jsonl
│   ├── actuals.jsonl
│   ├── decisions.jsonl               # [D-05] 决策库
│   ├── analyses.jsonl                # [D-13] 分析结论（机器可读）
│   ├── positions.json                # [D-13] 券商持仓快照
│   ├── transactions.jsonl            # [D-13] 手工交易流（快照缺失时用）
│   ├── prediction_ledger.csv         # export 产物
│   └── review_report.md              # report --save 产物
├── analysis/
│   ├── README.md                     # 研究资产索引 + 覆盖状态 + 工作队列
│   ├── <TICKER>_AlphaRadar.md        # 公司档案（历史追加）
│   ├── <TICKER>_BottomUp_Research.md # 行业级研究
│   └── sec/                          # 一手数据与提取脚本
├── site/index.html                   # [D-70] 静态站点（只读快照）
├── DEFECTS.md                        # 缺陷登记册
└── notes/                            # 讨论、原始素材
```

---

## 13. 已知缺口（尚未修复）

诚实记账，避免"以为已有"：

| 缺口 | 影响 |
|---|---|
| **Decision Database 无版本概念** | 已可记录（[D-05]），但决策本身无 v1/v2 修订机制 |
| **无组合横向视图（[D-13]）** | 单公司视角，回答不了"谁最值得现在买" |
| **港股/A股 无自动取数** | 已有 SEC 自动取数（[D-14]），港股/A股 仍为手工 |
| **`stock-analysis` 已 429（[D-29]）** | 价格/一致预期层无备选源 |
| **`probability` 未参与评分** | 已存但只在第 2 节展示，不影响 Base 计分口径（这是故意的，见 [D-01]） |

已用门禁/工具覆盖的（不再是缺口）：
- ✅ **数据错误无多重校验** → **G7** `verify_data.py`（四层，含外部交叉）
- ✅ **append-only 无技术保障** → G6 + 写入即 commit（[D-18]）
- ✅ **文档-CLI 漂移** → G5 (`scripts/check_doc_cli.py`)
- ✅ **账本完整性无体检** → G3 (`scripts/gates_data_integrity.py`)
- ✅ **回归无保障** → G1 (`scripts/test_ledger.sh`, 63 项)
- ✅ **Fundamental Score 不可复现** → `alpha_score.py score`（[D-10]）
- ✅ **仓位与赔率脱钩** → `alpha_score.py size`（[D-11]）
- ✅ **赔率定义不统一** → §5.3b 已写死（[D-43]）
- ✅ **无快速筛查档** → `alpha_score.py lite`（[D-12]）
- ✅ **无数据获取自动化** → `alpha_fetch.py`（[D-14]）

> 完整缺陷清单与实测证据见 `DEFECTS.md`。

---

## 14. 反偏误检查清单（每次分析结束前必过）

- [ ] 我有没有因为"公司很优秀"就放松估值要求？
- [ ] 我的 Base Case 是不是其实是乐观情景？
- [ ] 我的 Bear Case 是不是"温和下跌"而不是"逻辑失败"？
- [ ] 我有没有把并购增长当有机增长？
- [ ] 我有没有把 adjusted 利润当真实利润？
- [ ] 我有没有把当期 FCF 用于重 CapEx 公司的估值？
- [ ] 我有没有被当前股价锚定（先看股价再编逻辑）？
- [ ] 我的每个数字都有来源吗？
- [ ] 我有没有写下"什么情况说明我错了"？
- [ ] 我这次的预测，两年后能不能被验证？

---

## 15. Alpha Radar 的核心猎物

寻找的不是最热门的公司，也不是最便宜的公司，而是：

> **基本面正在改善 + 护城河正在增强 + 未来现金流增长具有可见性 + 市场尚未完全定价 + 当前价格提供足够安全边际**

即：

> **基本面改善速度 > 市场预期改善速度**

---

## 16. 最终哲学

> 不要问"这家公司是不是好公司"，
> 要问**"未来 5 年，这家公司赚钱的能力是否比过去 5 年更强"**。
>
> 然后继续追问：Revenue 会不会增长？Margin 会不会提高？FCF 会不会增长？ROIC 会不会提高？Moat 会不会增强？
>
> 五个 Yes → 值得深入研究。
> 五个 Yes **且估值尚未反映** → 这才是真正的机会。
>
> 反之，若 Revenue 增长不错但 ROIC 下降、FCF 恶化、护城河减弱——**即使股价跌了 50%，也不能因为"便宜"就买。**

这套系统的最终目的，是把 **"股价下跌"** 和 **"公司变便宜了"** 彻底区分开。

---