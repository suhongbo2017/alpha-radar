# analysis/ — 研究资产索引

两套框架并用：

- **`investment-bottom-up-research`** → 行业与产业链研究（`*_BottomUp_Research.md`）
- **`alpha-radar`** → 公司评估、定价、决策、预测闭环（`*_AlphaRadar.md`）
- **`sec/`** → 一手数据（SEC companyfacts 提取结果、原文关键词上下文、提取脚本）

---

## 覆盖状态

| Ticker | 公司 | Bottom-Up 报告 | Alpha Radar 档案 | 预测账本 | 当前状态 |
|---|---|---|---|---|---|
| APH | Amphenol | ✅ | ⬜ 待建 | ✅ v1（EPS/FairValue） | 已在框架内，等待建 Alpha Radar 档案 |
| INTU | Intuit | ✅ | ⬜ 待建 | ⬜ | 待跑 Alpha Radar |
| ITRI | Itron | ✅ | ⬜ 待建 | ⬜ | 待跑 Alpha Radar |
| NOW | ServiceNow | ✅ | ⬜ 待建 | ⬜ | 待跑 Alpha Radar |
| MSFT | Microsoft | ✅ | ⬜ 待建 | ⬜ | 待跑 Alpha Radar |
| CRM | Salesforce | ✅ | ⬜ 待建 | ⬜ | 待跑 Alpha Radar |
| ASX | 日月光投控 | ⬜ | ⬜ | ⚠️ v1（来源未验证） | 仅有讨论级数据，需一手验证后重建 |

---

## 命名约定

```text
analysis/<TICKER>_BottomUp_Research.md    # 行业/产业链级研究，一次性较完整
analysis/<TICKER>_AlphaRadar.md           # 公司档案，历史版本追加，不删除
analysis/sec/<ticker>.txt                 # SEC companyfacts 提取摘要
analysis/sec/<ticker>_ctx.txt             # 10-K/10-Q 原文关键词上下文
```

## 数据流

```text
SEC EDGAR companyfacts JSON
        │  py analysis/sec/extract2.py
        ▼
analysis/sec/<ticker>.txt
        │  人工阅读 + 交叉验证
        ▼
analysis/<TICKER>_BottomUp_Research.md / _AlphaRadar.md
        │  py scripts/alpha_ledger.py predict
        ▼
data/predictions.jsonl   ──财报后──▶  data/actuals.jsonl
        │  py scripts/alpha_ledger.py report
        ▼
data/review_report.md     （预测 vs 实际 + 误差归因 + 预测能力评级）
```

## 待办

### 已修复（v1.1 / v1.2）
- [x] P0-1 / D-01 三情景事后择优 → 改为 Base 计分 + 独立区间命中率
- [x] P0-2 / D-02 预测版本混算 → 分组键含版本，同版本改数被拒绝
- [x] P0-3 / D-03 币种不校验 → 单位一致性强制，不一致拒绝录入
- [x] P1-4 / D-04 指标名静默失配 → 指标词表，写错立即报错
- [x] P1-7 / D-07 估值类不计分
- [x] P2-17 / D-17 重复录入 → 写入时检测
- [x] D-05 Decision Database（`decisions.jsonl` + `decision`/`decisions` + 报告第 8 节）
- [x] D-06 due 复盘提醒（`due`）
- [x] D-08 probability 参与概率加权（报告第 2 节）
- [x] D-09 误差归因入库 + 分布（`--attribution` / `attribute` / 报告第 7 节）
- [x] D-10 评分锚（`alpha_score.py score`）
- [x] D-11 仓位 = f(赔率,置信度)，赔率<1 不建仓（`alpha_score.py size`）
- [x] D-12 Alpha Radar Lite（`alpha_score.py lite`）
- [x] D-14 SEC 自动取数（`alpha_fetch.py`，已实测 APH 3.5MB → 335 行）
- [x] D-15 description 诚实化（不再声称支持港股/A股）
- [x] D-28 `herdr_ci.py` 跨 shell 编排器
- [x] 门禁 G1（63 项）/ G2 / G3（含决策库）/ G4 / G5（多工具）

### 未修复（明确记账）
- [ ] **D-13 组合横向视图**（Module 06 Radar Board）—— 等多个标的档案建好再做
- [ ] **D-18 append-only 无技术保障** —— ⛔ **等人工批准 `git init`**
- [ ] **D-29 `stock-analysis` yfinance 429** —— 需选备选行情源

> 完整缺陷清单（含实测证据与元教训）见 `DEFECTS.md`。

---

## 剩余工作队列（A0–A10 已基本完成）

| ID | 任务 | 状态 |
|---|---|---|
| **A0** | `git init` + 首次提交（固化 15 条预测） | ✅ 完成（D-18） |
| A1 | 预测写入后自动 commit 钩子 | ✅ 完成（`autocommit`） |
| A2 | Decision Database | ✅ 完成（D-05） |
| A3 | due 复盘提醒 | ✅ 完成（D-06） |
| A4 | probability 概率加权 | ✅ 完成（D-08） |
| A5 | 误差归因 + 分布 | ✅ 完成（D-09） |
| A6 | SEC 自动取数 | ✅ 完成（D-14） |
| A7 | 文档-CLI 漂移自检 | ✅ 完成（G5） |
| A8 | 评分锚 | ✅ 完成（D-10） |
| A9 | 仓位 = f(赔率,置信度) | ✅ 完成（D-11） |
| A10 | Alpha Radar Lite | ✅ 完成（D-12） |

### 剩余缺口
- [ ] **D-13** 组合横向视图（Radar Board）
- [ ] **D-29** `stock-analysis` yfinance 429，需备选行情源
- [ ] 港股 / A股 一手数据源（D-15 已降级为诚实描述）

> 已无 ⛔ 待批准项。完整的 33 项缺陷登记（含实测证据与元教训）见 `DEFECTS.md`。

### 业务待办
- [ ] 用 `templates/Company_Profile_Template.md` 为 APH 建 Alpha Radar 档案
- [ ] 为 INTU / ITRI / NOW / MSFT / CRM 逐个跑 Alpha Radar 并登记预测
- [ ] ASX 数据一手化（取 ASE 年报/法说会），重建预测版本 v2
- [ ] 下一次财报季后执行 Review 流程

---

## 版本控制（D-18）

```bash
git log --oneline           # 账本固化历史
git show HEAD:data/predictions.jsonl | wc -l    # 校验当前账本 vs HEAD
```

**写入即固化**：`predict` / `actual` / `decision` 落盘后自动 commit，
提交信息形如 `ledger(prediction): APH Revenue 2030 Base`。
关闭方式：`ALPHA_RADAR_AUTOCOMMIT=0`（批量导入时用）。
测试环境（`ALPHA_RADAR_HOME` 指向临时目录）自动禁用 —— 否则 63 项测试会制造垃圾 commit。

**append-only 的正确边界**：

| | predictions | actuals |
|---|---|---|
| 性质 | 当时的判断 | 已发生的事实 |
| 改写 | **禁止**，必须升版本 | 允许纠错，但需**独立提交留痕** |

---

## 门禁与编排

```bash
py scripts/gates.py --list          # 列出门禁
py scripts/gates.py --all           # 串行跑全部门禁
py scripts/gates.py --only G5       # 单个门禁（跨 shell 安全）

bash scripts/sync_skills.sh         # 同步 skill 到 ~/.pi/agent/skills/
bash scripts/sync_skills.sh --check # 只检查是否漂移

py scripts/herdr_ci.py              # [D-28] Herdr 并行编排，1 遍（跨 shell）
py scripts/herdr_ci.py --repeat 3   # 跑 3 遍
py scripts/herdr_ci.py --keep       # 保留 workspace 供人工查看
py scripts/herdr_ci.py --build A2   # 串行构建队列
```

| 门禁 | 内容 |
|---|---|
| G1 | 账本回归（63 项） |
| G2 | skill 副本同步 |
| G3 | 真实数据完整性（预测 / 实际 / 归因 / 决策） |
| G4 | 语法 / 导入 |
| G5 | 文档-CLI 漂移（三个工具 + 报告 9 节） |
| G6 | **账本已固化进 git**（写入即 commit，检验无未提交改动） |

**编排铁律**：并行只用于只读门禁；构建必须串行（同一文件）；条件用哨兵 `__GATE_PASS__/__GATE_FAIL__`；pane 侧命令必须跨 shell 安全；先跑 canary；人工批准项永不自动执行。
---

## 数据校验（[D-38~D-42] 后成为强制前置）

> **错误的数据导致错误的结果。** 任何要写进档案的财务数字，必须先过 `verify_data.py`。

```bash
py scripts/verify_data.py ITRI --require-cross   # 单公司（含外部交叉）
py scripts/verify_data.py --all --require-cross  # 全量（G7 门禁）
```

| 层 | 检查 |
|---|---|
| L1 | 会计恒等式：Revenue − COGS = GrossProfit 等 |
| L2 | 时间一致性：YTD 最长时长断言、**净债务同日性与独立重算**、TTM 量级包络 |
| L3 | **交叉来源：SEC vs Yahoo 同一日期逐项比对** + TTM vs Yahoo trailing |
| L4 | 量纲与合理性 |

**三种结论**：✅ MATCH / ⚠️ DEFINITIONAL（口径或日期差异，不算错）/ ❌ MISMATCH（退出码 1）

两条铁的教训：
1. **交叉校验的有效性上限 = 两条路径的独立性。** 共享原语的"双路验证"是自欺（D-39）
2. **校验器必须做故障注入测试。** 没红过的校验器 = 未验证

---

## 已建档案（3 家）

| 标的 | Fundamental | 生命周期 | ROIC vs WACC | 净杠杆 | 现价/1年分位 | 赔率(一致口径) | 预期总回报 | 动作 |
|---|---:|---|---|---|---:|---:|---:|---|
| **APH** | 84.6 Excellent | 2.5→3 | 19.2% vs 10.4% | 1.46x | $87.24 / 95 | 0.92:1 | 8.0% | Watch |
| **ITRI** | 53.8 Weak | 3→4 | 10.5% vs 8.5% | 2.36x | $85.58 / 13 | 0.91:1 | 8.1% | Watch |
| **INTU** | **89.8 Excellent** | 3→4 | **22.9% vs 9.05%** | **0.07x** | $302.75 / 11 | 0.69:1 | **10.1%** | Watch |

> 三家的 "Watch" 含义不同：APH = 好公司贵；ITRI = 便宜但公司弱；INTU = **最好的公司 + 低价，但赔率仍不达标**。

## 口径纪律（踩过的坑，已写死）

1. **净债务必须扣除短期投资**（[D-46]）—— 否则系统性高估
2. **资产负债表三项必须同日**（[D-42]）
3. **赔率统一定义**（[D-43]）：上行 = 加权价值涨幅；下行 = 至 Bear 情景跌幅。**不得用 52 周低点当分母**
4. **TTM = 最近年度 + 本年迄今 − 去年同期**，YTD 取最长时长，按**财年**分组
5. **每建一份新档案，必须重跑 `verify_data.py --all`** —— 错误会跨档案传播（[D-46] 同时污染了 APH 与 INTU）
