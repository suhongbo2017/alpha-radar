# Alpha Radar

Alpha Radar 是一个面向长期投资研究的本地工具链。它把公司基本面、估值情景、投资决策、预测账本和事后复盘串成一个可追踪的闭环。

项目的重点不是自动生成买卖信号，而是让每个数字、假设、决策和复盘结果都有来源、有时间截点，并且能够在未来用实际数据验证。

> 免责声明：本项目是研究与记录工具，不构成投资、税务或法律建议。行情、财报和第三方数据可能延迟、缺失或存在口径差异。

## 功能概览

- 从 SEC EDGAR `companyfacts` 获取美国上市公司的原始 XBRL 数据。
- 计算 TTM Revenue、毛利、营业利润、FCF、ROIC、净债务等指标。
- 对 SEC 数据执行会计恒等式、时间一致性、外部交叉和量纲合理性检查。
- 用固定阈值计算 Fundamental Score，用赔率和置信度给出仓位区间建议。
- 记录不可覆盖的预测、实际值、投资决策和误差归因。
- 生成预测与实际值的复盘报告。
- 从行情缓存或 Yahoo Finance 获取价格快照和分析师一致预期。
- 从券商接口同步持仓快照，计算组合市值、集中度和持仓/分析一致性。
- 生成单文件、零外部依赖的静态研究站点，可离线打开或部署到 GitHub Pages。
- 通过 G1-G10 门禁检查账本、数据、文档、Git 固化、站点安全和缺陷册自洽。

## 适用范围

当前自动化数据链路主要覆盖：

- 美国上市公司：SEC EDGAR companyfacts。
- 行情和一致预期：Yahoo Finance 接口，可能需要代理并受限流影响。

以下市场没有完整的一手数据自动化链路：

- 港股、A 股、韩国市场。
- 未上市公司，例如 SpaceX。

这些标的可以保存人工研究文件，但不能把 SEC 工具的结果当作它们的一手数据。无法自动验证的数字必须在研究文件中明确标注来源和验证状态。

## 环境准备

### Windows

项目脚本使用 Python 标准库，建议使用 Python 3.10 或更高版本。Windows 环境通常使用 Python Launcher：

```powershell
py --version
py -m compileall -q scripts
```

需要联网获取 SEC 或 Yahoo 数据时，还需要：

- `curl`：行情、Yahoo 交叉校验和券商同步使用。
- Git：账本自动固化和 G6 门禁使用。
- Git Bash：G1、G2 的 Shell 测试需要；`scripts/gates.py` 会自动寻找常见安装路径。

### Linux / macOS

把下面命令中的 `py` 替换为 `python3` 即可：

```bash
python3 --version
python3 -m compileall -q scripts
```

### 代理

本机无法直连 Yahoo 时，可设置代理。默认代理地址是 `http://127.0.0.1:7897`，也可以覆盖：

```powershell
$env:ALPHA_PROXY = "http://127.0.0.1:7897"
py scripts/alpha_quote.py MSFT
```

SEC 请求使用 `ALPHA_SEC_UA` 设置 User-Agent。生产使用时应改成包含真实联系邮箱的值：

```powershell
$env:ALPHA_SEC_UA = "alpha-radar research (contact: you@example.com)"
```

## 目录结构

```text
.
├── analysis/
│   ├── *_AlphaRadar.md              # 公司评估与决策档案
│   ├── *_BottomUp_Research.md       # 行业与产业链研究
│   ├── README.md                    # 研究资产索引
│   └── sec/                         # SEC 提取摘要、上下文和提取脚本
├── data/
│   ├── predictions.jsonl            # 预测账本
│   ├── actuals.jsonl                # 实际值与误差归因
│   ├── decisions.jsonl              # 投资决策历史
│   ├── analyses.jsonl               # Alpha Radar 分析结论
│   ├── quotes/                      # 行情缓存
│   ├── estimates/                   # 分析师一致预期缓存
│   ├── revaluations/                # 价格敏感性审计（追加式，不改预测）
│   ├── positions.example.json       # 持仓快照格式示例
│   └── positions.json               # 本地持仓，禁止公开提交
├── scripts/
│   ├── alpha_fetch.py               # SEC 数据下载
│   ├── alpha_metrics.py              # 一手财务指标计算
│   ├── verify_data.py                # 多层数据校验
│   ├── alpha_source.py               # 多源交叉校验（第二/第三外部源）
│   ├── alpha_quote.py               # 行情和一致预期
│   ├── alpha_scenario.py            # 规则化 Bull/Base/Bear
│   ├── alpha_score.py               # 评分、仓位、快速筛查
│   ├── alpha_ledger.py              # 预测账本和复盘
│   ├── alpha_portfolio.py           # 持仓与组合雷达
│   ├── build_site.py                # 静态站点生成
│   └── gates.py                     # 总门禁入口
├── templates/                       # 公司档案与复盘模板
├── site/index.html                  # 静态站点产物
├── DEFECTS.md                       # 已知缺陷和历史教训
├── REVIEWS.md                       # 项目审查记录（审查过程本身可被审核）
└── Alpha_Radar_SKILL.md             # 详细研究方法与工作规则
```

SEC 原始 `*_facts.json`、券商凭据、持仓文件和派生报告默认被 `.gitignore` 排除。不要因为本地文件存在就假设它们会被版本控制保护，仍应定期检查：

```powershell
git status --short
```

## 推荐工作流

一份新公司研究建议按下面顺序执行：

1. 明确股票代码、市场、数据截点和研究问题。
2. 获取 SEC 原始数据；如果市场不在 SEC 覆盖范围内，改用对应市场的一手文件并标注人工来源。
3. 运行 `verify_data.py`，先处理所有 `MISMATCH`。
4. 运行 `alpha_metrics.py`，把指标与 10-K/10-Q 原文交叉确认。
5. 阅读行业研究和公司档案模板，写入基本面、增长质量、护城河、现金流和 ROIC 分析。
6. 获取当前价格和一致预期；研究级情景与规则级情景必须分开标注。
7. 用 `alpha_score.py` 做定量辅助，不把评分结果当作独立的投资结论。
8. 用 `alpha_ledger.py predict` 记录可验证的 Base/Bull/Bear 预测。
9. 用 `alpha_portfolio.py analysis` 记录当时的分析结论和动作。
10. 财报公布后用 `actual` 录入事实，用 `report` 复盘预测误差。
11. 运行全部门禁并检查 Git 状态。
12. 如需公开展示，只使用不含持仓的静态站点构建。

完整研究方法、数据纪律和估值口径见 [`Alpha_Radar_SKILL.md`](Alpha_Radar_SKILL.md)。

## SEC 数据链路

### 下载数据

```powershell
# ticker -> CIK -> companyfacts -> 提取摘要
py scripts/alpha_fetch.py MSFT

# 直接使用 CIK
py scripts/alpha_fetch.py --cik 789019

# 忽略 24 小时缓存
py scripts/alpha_fetch.py MSFT --force

# 只下载原始 companyfacts，不运行提取
py scripts/alpha_fetch.py MSFT --no-extract

# 同时下载近期申报清单
py scripts/alpha_fetch.py MSFT --submissions

# 归档已分析标的的 SEC 申报原文（按 accession number 去重）
py scripts/alpha_archive.py --once
py scripts/alpha_archive.py --ticker MSFT --forms 10-K,10-Q,8-K
```

输出文件包括：

- `analysis/sec/company_tickers.json`：ticker 到 CIK 的映射缓存。
- `analysis/sec/msft_facts.json`：SEC 原始 companyfacts，通常不提交 Git。
- `analysis/sec/msft.txt`：`extract2.py` 生成的结构化阅读视图。
- `analysis/sec/archive/<TICKER>/<ACCESSION>/`：10-K、10-Q、8-K 原文、主文档和 SEC `index.json`，按申报编号保存，默认不提交 Git。
- `data/filing_archive.jsonl`：归档索引，记录表单、申报日期、报告期、URL、本地路径和 SHA-256；同一 `ticker + accession_number` 不重复追加。

`alpha_archive.py` 只归档真实 SEC 申报文件，不把抓取结果自动写入 `actuals.jsonl`，也不自动修改预测。检测失败会保留警告并返回非零状态，便于后台调度重试。

`alpha_fetch.py` 的默认缓存有效期为 24 小时。下载成功不代表数据已经适合写进研究结论；必须阅读申报原文并运行校验。

### 计算指标

```powershell
py scripts/alpha_metrics.py MSFT
py scripts/alpha_metrics.py MSFT --json
py scripts/alpha_metrics.py MSFT --years 8
py scripts/alpha_metrics.py MSFT --score-inputs
```

主要口径：

```text
TTM = 最近年度 + 本年迄今 - 去年同期
FCF = Operating Cash Flow - CapEx
Net Debt = 有息债务 + 融资租赁负债 - 现金 - 短期投资
```

需要特别注意：

- TTM 必须按日期对齐，不能按数组下标拼接。
- 同一结束日存在多条 YTD 记录时，取最长时长。
- 非自然年公司要按财年归属，而不是按自然年分组。
- 现金、权益和债务必须来自同一资产负债表日期。
- CapEx 和 FCF 的 SEC 与第三方口径可能不同，必须查看校验器说明。

### 多层校验

```powershell
# 单家公司，含 SEC 与 Yahoo 交叉
py scripts/verify_data.py MSFT --require-cross

# 全部已下载公司
py scripts/verify_data.py --all --require-cross

# 离线时只跑内部检查
py scripts/verify_data.py MSFT --no-cross

# 输出机器可读结果
py scripts/verify_data.py MSFT --json
```

四层检查：

| 层 | 内容 | 结果含义 |
|---|---|---|
| L1 | 营业收入（Revenue）、销售成本（COGS）、毛利（GrossProfit）、营业利润（OpInc）等会计关系 | 发现取数或转写错误 |
| L2 | YTD 时长、财年归属、TTM、资产负债表同日性 | 发现时间错位和 TTM 错误 |
| L3 | SEC 与 Yahoo 同日数据、Yahoo trailing TTM | 发现共享内部路径无法发现的问题 |
| L4 | 正负号、数值范围、有限数和单位 | 发现明显异常输入 |

处理原则：

- `MATCH`：通过紧容差检查。
- `DEF` / `DEFINITIONAL`：可能是口径、币种或日期差异，需要人工判断。
- `MISMATCH`：在查明前不得把相关数字写入研究档案。

如果没有任何 `*_facts.json`，`--all` 会失败。这不是代码错误，而是说明当前工作区没有可供 G7 校验的 SEC 原始数据。

## 行情与情景

### 行情快照

```powershell
py scripts/alpha_quote.py MSFT
py scripts/alpha_quote.py MSFT --json
py scripts/alpha_quote.py MSFT --offline
py scripts/alpha_quote.py MSFT --proxy http://127.0.0.1:7897
```

行情获取顺序是 Yahoo 直连、代理和缓存回退。缓存文件位于 `data/quotes/<TICKER>.json`，使用缓存时必须关注 `fetched_at`、`market_time` 和数据源字段，不能把旧价格当作实时价格。

### 一键自动分析

输入一个 ticker，自动完成 SEC 数据获取、行情快照、一手指标计算、多层交叉校验、规则化情景和结果归档：

```powershell
py scripts/alpha_one.py NVDA
```

常用选项：

```powershell
py scripts/alpha_one.py NVDA --force       # 强制刷新 SEC 数据
py scripts/alpha_one.py NVDA --offline     # 不请求行情，只使用缓存
py scripts/alpha_one.py NVDA --no-cross    # 跳过外部源交叉校验
py scripts/alpha_one.py NVDA --no-report   # 只保存 JSON，不生成运行 Markdown
py scripts/alpha_one.py NVDA --no-draft    # 不生成研究草稿

### 浏览器入口（本地工作台）

命令行适合脚本和自动化；日常手动运行可使用本地页面：

```powershell
py scripts/alpha_web.py
```

程序会打开 `http://127.0.0.1:8765/`。页面可以输入 ticker、选择强制刷新/离线/交叉校验等选项，启动 `alpha_one.py` 并查看阶段状态。服务只监听本机回环地址，按 `Ctrl+C` 停止；它不会让 GitHub Pages 执行任何命令，也不会自动写入正式预测、估值或组合决策。
```

每次运行的 JSON、Markdown 报告和研究草稿保存在 `data/runs/`。自动完成的数据步骤会记录命令、结果和数据缺口；报告还会列出需要人工完成的原文核对、业务/护城河分析、管理层判断、情景假设和估值桥。`*_research_draft.md` 只是待填写交接文档，不会进入 `analysis/`，也不会被当作正式档案。

该命令只做数据自动化和规则粗筛，不会自动创建研究级档案，也不会写入正式预测、Fair Value 或组合决策。规则情景不是投资结论；只有完成研究并通过研究快照资格校验后，才可登记正式预测。

### 分析师一致预期

```powershell
py scripts/alpha_quote.py MSFT --estimates
py scripts/alpha_quote.py MSFT --estimates --json
```

该流程需要 Yahoo cookie 和 crumb，失败可能是网络、限流、接口变化或该公司没有分析师覆盖。失败时不要用空值替代真实预期，也不要把规则情景误写成研究级情景。

### 规则化情景

```powershell
py scripts/alpha_scenario.py MSFT
py scripts/alpha_scenario.py MSFT --json
```

`alpha_scenario.py` 根据市值、TTM 收入增速、净债务/EBITDA 和 FCF 正负生成 Bull/Base/Bear。它是可复现的规则输出，不是行业研究结论，适合做占位和敏感性参考，不应直接作为高置信度买入依据。

## 评分与筛查

### Fundamental Score

```powershell
py scripts/alpha_score.py anchors
py scripts/alpha_score.py score `
  --revenue-growth 8 --organic-growth 6 `
  --gross-margin 39 --operating-margin 28 `
  --fcf-growth 22 --fcf-margin 19 `
  --roic 20.2 --net-debt-ebitda 2.1 `
  --moat 4.2 --management 4.0 --json
```

PowerShell 的续行符是反引号；在 Git Bash 或 Linux 中请改用反斜杠。评分缺项时会按已提供项目归一化，并明确提示该结果不可直接与完整输入的公司比较。

### 仓位建议

```powershell
py scripts/alpha_score.py size --odds 2.5 --confidence Medium
py scripts/alpha_score.py size --odds 3.9 --confidence High --max-weight 25 --current-weight 8
```

硬规则：赔率低于 `1:1` 时输出不建仓。仓位区间只是约束和研究辅助，不是买入信号。

### 快速筛查

```powershell
py scripts/alpha_score.py lite `
  --revenue-growth 12 --moat-trend up --valuation-pct 55

py scripts/alpha_score.py lite `
  --revenue-growth 12 --moat-trend up --valuation-pct 55 `
  --roic 22 --fcf-margin 26
```

Lite 只用于决定是否投入完整研究，不替代完整分析。

## 预测账本与复盘

预测和事实使用 JSONL 追加记录。旧预测不能覆盖；同一版本修改数值必须升到 `v2`、`v3` 等新版本。

### 先查看指标词表

```powershell
py scripts/alpha_ledger.py metrics
```

常用指标包括 `Revenue`、`Organic_Growth`、`Gross_Margin`、`Operating_Margin`、`EPS`、`FCF`、`ROIC`、`Net_Debt_EBITDA`、`FairValue` 和 `Target_Price`。

### 记录预测

```powershell
py scripts/alpha_ledger.py predict `
  --ticker MSFT --metric Revenue --period FY2030 `
  --value 450000000000 --unit USD `
  --scenario Base --prob 0.50 --confidence Medium `
  --version v1 `
  --thesis "云业务和生产力软件保持中高个位数增长" `
  --basis "FY2026 10-K、10-Q 与公司指引"
```

情景必须是 `Bear`、`Base` 或 `Bull`。`--prob` 范围为 `0 < p <= 1`。指标默认必须命中词表；只有明确知道自己在做什么时才使用 `--allow-custom`。

### 记录实际值

```powershell
py scripts/alpha_ledger.py actual `
  --ticker MSFT --metric Revenue --period FY2030 `
  --value 448000000000 --unit USD `
  --source "2029 10-K, filed 2030-08-01" `
  --attribution Demand
```

实际值的单位必须与对应预测一致。若确实经过换算或确认要强制录入，可使用 `--force`，系统会写入 `unit_forced` 标记并在复盘中排除该组的正常评分。支持的误差归因包括：

```text
Demand / MarketShare / Margin / CapEx / Management / M&A / Macro / FX / Valuation
```

### 查看、到期提醒和复盘

```powershell
py scripts/alpha_ledger.py list --ticker MSFT
py scripts/alpha_ledger.py due --asof 2030-09-01
py scripts/alpha_ledger.py report --ticker MSFT
py scripts/alpha_ledger.py report --ticker MSFT --save
py scripts/alpha_ledger.py attribute `
  --ticker MSFT --metric Revenue --period FY2030 `
  --attribution Demand --note "终端需求低于假设"
py scripts/alpha_ledger.py export
```

复盘规则：

- 预测能力只对 `Base` 情景、最新版本和 `fundamental` 指标计分。
- `Bear`/`Bull` 用于区间命中统计，不用于事后选择最接近的情景冒充主预测。
- `valuation` 指标可以记录，但不计入预测能力评分。
- 同一指标的单位不一致时，该组不参与对比。

### 记录投资决策

```powershell
py scripts/alpha_ledger.py decision `
  --ticker MSFT --action Starter --price 500 `
  --weight 10 --odds 2.0 `
  --reason "赔率达标，等待估值与基本面进一步确认"

py scripts/alpha_ledger.py decisions --ticker MSFT
```

动作值包括 `Watch`、`Starter`、`Buy`、`StrongBuy`、`Core`、`Hold`、`Trim` 和 `Exit`。决策记录是历史事实，改变观点时新增记录，不修改旧记录。

## 组合与持仓

### 本地交易流

```powershell
py scripts/alpha_portfolio.py buy `
  --ticker MSFT --shares 10 --price 500 --date 2026-03-01
py scripts/alpha_portfolio.py sell `
  --ticker MSFT --shares 4 --price 560 --date 2026-09-01
py scripts/alpha_portfolio.py cash --amount 25000
py scripts/alpha_portfolio.py holdings
py scripts/alpha_portfolio.py board
py scripts/alpha_portfolio.py check
```

交易流是追加记录，持仓状态从交易流派生。卖出超过当前持仓会被拒绝。若存在 `data/positions.json` 快照，组合工具会优先使用券商快照，因为快照代表当前状态，不等于完整历史交易流水。

### 券商同步

```powershell
# 先只查看返回字段，不落盘
py scripts/alpha_portfolio.py sync --dry-run

# 环境变量方式
$env:FUTU_API_USER = "your-user"
$env:FUTU_API_PASS = "your-password"
py scripts/alpha_portfolio.py sync
```

也可以使用命令行参数或 `data/.futu_auth`：

```json
{"user":"your-user","password":"your-password"}
```

凭据不得提交 Git。同步接口默认地址来自 `FUTU_API_URL`，也可通过 `--url` 覆盖。同步会写入 `data/positions_raw.json` 和 `data/positions.json`，其中前者包含原始响应，必须确认 `.gitignore` 仍然有效。

### 隐私边界

默认站点构建不读取 `data/positions.json`：

```powershell
py scripts/build_site.py
```

以下命令会把持仓字段嵌入 HTML，只能在本地使用，不能部署到公开站点：

```powershell
py scripts/build_site.py --include-holdings
```

## 静态站点

生成单文件站点：

```powershell
py scripts/build_site.py
py scripts/build_site.py --with-gates
py scripts/build_site.py --out site/index.html
```

打开方式：

```powershell
Start-Process (Resolve-Path site/index.html)
```

站点包含已登记的分析、预测、决策、缺陷和门禁摘要。它是只读展示层，不会写入账本，也不会调用规则引擎生成新的投资分析。

公开部署前至少确认：

```powershell
py scripts/gates.py --only G8
git status --short
```

G8 会重新构建默认站点，并检查常见持仓字段是否泄漏。该检查是防线，不是绝对安全证明；新增敏感字段时必须同步扩充门禁和人工审查范围。

## 门禁

查看门禁：

```powershell
py scripts/gates.py --list
py scripts/gates.py --all
py scripts/gates.py --only G1
```

| 门禁 | 内容 | 常见失败原因 |
|---|---|---|
| G1 | 账本回归测试 | 核心计算或输出发生回归 |
| G2 | skill 副本同步 | 工作区文档与本地 Pi skill 副本不一致 |
| G3 | JSONL 和账本完整性 | 字段缺失、指标非法、版本冲突、孤儿归因 |
| G4 | Python 语法和导入 | 语法错误或模块导入失败 |
| G5 | 文档与 CLI 一致性 | 文档中的命令或报告章节漂移 |
| G6 | 账本 Git 固化 | 账本未提交或 HEAD 与工作树不一致 |
| G7 | SEC 多层数据校验 | 没有原始 facts、外部交叉失败或存在硬错误 |
| G8 | 站点安全构建 | 构建失败或默认 HTML 含敏感持仓字段 |
| G9 | 研究快照一致性 | 快照与档案不一致（`--refresh` 会掩盖它，所以 CI 不用） |
| G10 | 缺陷册自洽 | DEFECTS.md 的统计行与主表实数不一致 → 用 `defect_stats.py --write` 重生 |

**已知失败豁免（`scripts/expected_fail.json`）**：已登记、根因已明确、暂时无法修的项（当前 3 项：MU/NOC/SOFI，见 D-82/83/84）
可以按 **target** 豁免，不必让整条 CI 永久变红。三条硬约束：每项必须绑定一个**仍未关闭**的缺陷 ID；
**表外的失败照常红**（新问题不许靠加豁免表处理）；表内项不再失败或缺陷已修好 → **豁免过期即红**（防腐烂）。

```powershell
py scripts/gates.py --all          # 10 道门禁，豁免项会显式报出条数
```

当前 G7 依赖 `analysis/sec/*_facts.json`。这些文件默认不入 Git，因此新环境首次运行全部门禁时，G7 失败是预期现象；先下载需要校验的公司数据，或只运行不依赖外部原始数据的门禁。

G2 需要工作区 skill 与本机副本同步：

```powershell
bash scripts/sync_skills.sh --check
bash scripts/sync_skills.sh
```

## Git 固化与自动提交

`alpha_ledger.py` 默认在写入 `predictions.jsonl`、`actuals.jsonl` 或 `decisions.jsonl` 后执行 Git 提交。提交信息类似：

```text
ledger(prediction): MSFT Revenue FY2030 Base
```

这是为了保留账本历史，但有两个重要副作用：

1. 执行写入命令会改变当前仓库的 Git 历史。
2. 自动提交只会 `git add` 目标账本文件，但提交仍发生在当前分支。

查看状态和历史：

```powershell
git status --short
git log --oneline -- data/predictions.jsonl
git show HEAD:data/predictions.jsonl
```

批量测试或人工批处理时可以关闭自动提交：

```powershell
$env:ALPHA_RADAR_AUTOCOMMIT = "0"
```

测试环境使用 `ALPHA_RADAR_HOME` 指向临时目录时，自动提交也会自动关闭：

```powershell
$env:ALPHA_RADAR_HOME = "C:\temp\alpha-radar-test"
```

关闭自动提交后，必须自行检查、提交并记录账本变更；不要把“关闭自动提交”当作取消 append-only 纪律。

## 测试与本地验证

最小验证：

```powershell
py -m compileall -q scripts
py scripts/check_doc_cli.py
py scripts/gates.py --only G1
py scripts/gates.py --only G3
py scripts/gates.py --only G8
```

完整验证：

```powershell
py scripts/gates.py --all
```

G1 使用临时数据目录运行回归测试，不应向真实账本写入测试记录。若要查看测试脚本：

```powershell
bash scripts/test_ledger.sh
```

代码改动后，应至少覆盖：

- 正常输入、缺失输入、非法单位和非法日期。
- 重复预测、同版本冲突和版本升级。
- Yahoo/SEC 网络失败、缓存回退和空响应。
- 不同财年、52/53 周财年和跨币种数据。
- 空持仓、零市值、部分卖出和券商快照字段缺失。
- Markdown、JSONL 和站点输出中的特殊字符。
- 默认站点与 `--include-holdings` 站点的敏感字段边界。

## 常见问题

### `G7` 提示没有 `*_facts.json`

先运行：

```powershell
py scripts/alpha_fetch.py MSFT
```

然后再运行：

```powershell
py scripts/verify_data.py MSFT --require-cross
```

如果只想离线检查已经存在的提取结果，使用 `--no-cross`。没有原始 facts 时不能声称 G7 通过。

### Yahoo 请求失败或返回空数据

检查：

```powershell
curl --version
$env:ALPHA_PROXY
py scripts/alpha_quote.py MSFT --proxy http://127.0.0.1:7897
```

可以使用 `--offline` 读取已有缓存，但必须查看缓存时间。缓存回退只解决可用性，不解决数据新鲜度。

### `G2` 失败

检查差异：

```powershell
bash scripts/sync_skills.sh --check
```

确认要同步后执行：

```powershell
bash scripts/sync_skills.sh
```

同步前应先检查工作区和本机 skill 副本中是否有需要保留的本地修改。

### `G6` 失败

先查看：

```powershell
git status --short
git diff -- data/predictions.jsonl data/actuals.jsonl data/decisions.jsonl
```

确认账本内容后提交；不要用强制回退命令覆盖历史记录。

### 预测实际值无法录入

常见原因：

- 指标名不在词表中：先运行 `py scripts/alpha_ledger.py metrics`。
- 单位与预测不一致：换算后再录入，或使用 `--force` 并保留说明。
- 同一实际值已经存在：确认是否为重述，再决定是否使用 `--allow-duplicate`。
- 期间格式无法解析：优先使用 `FY2030`、`2030`、`Q3FY2027` 或 `2027Q3`。

### 静态页面没有最新数据

重新构建：

```powershell
py scripts/build_site.py
```

如果构建时间变化但内容不变，检查 JSONL 是否真的有新记录，并确认 `latest_by` 的最新日期字段符合预期。

## 维护约定

- 新增 CLI 参数时，同步更新脚本帮助、`README.md`、`Alpha_Radar_SKILL.md` 和 G5 检查。
- 新增账本字段时，同步更新 G3、复盘报告、导出逻辑和测试。
- 新增敏感字段时，同步更新 `.gitignore`、G8 和公开站点检查。
- 修改财务指标算法时，必须更新 `alpha_metrics.py`、`verify_data.py`、故障注入测试和 `DEFECTS.md`。
- 研究档案必须写明数据截点、来源、单位、币种和验证状态。
- 规则级情景和研究级情景必须在文件、报告和站点中明确区分。
- 不要修改或删除历史预测来“修正”结果；应追加新版本或新事实。
- 运行自动提交命令前确认当前分支和工作区状态。

## 相关文档

- [`Alpha_Radar_SKILL.md`](Alpha_Radar_SKILL.md)：研究方法、五大模块和详细口径纪律。
- [`analysis/README.md`](analysis/README.md)：当前研究资产、覆盖状态和业务待办。
- [`DEFECTS.md`](DEFECTS.md)：历史缺陷、实测证据和修复记录。
- [`Investment_Bottom_Up_Research_SKILL.md`](Investment_Bottom_Up_Research_SKILL.md)：行业与产业链研究方法。
- [`templates/Company_Profile_Template.md`](templates/Company_Profile_Template.md)：公司档案模板。
- [`templates/Review_Template.md`](templates/Review_Template.md)：复盘模板。
- [`data/estimates/README.md`](data/estimates/README.md)：一致预期缓存说明。

## 许可证与数据责任

仓库当前未声明统一开源许可证。发布或复用前请先确认代码、研究文本、第三方数据和生成产物的授权边界。

SEC、Yahoo Finance 和券商接口各自受其服务条款约束。不要把需要登录、包含个人持仓或包含凭据的文件部署到公开站点或提交到公开仓库。

### 项目审查记录

`REVIEWS.md` 记录的是**审查过程**（方法、证据、未验证清单、审查者自己的误判），
不是审查结论。目的是让后来的人能判断**审查本身是否合理**。

规则：追加式不改写；每条结论必须带可复现命令；必须写明未验证清单。

### 多源交叉校验

单一外部源（Yahoo）错了你无法知道。`alpha_source.py` 补上第二、第三个源：

```powershell
py scripts/alpha_source.py list              # 可用源与各自的独立性
py scripts/alpha_source.py cross ITRI        # 与引擎逐项比对
py scripts/alpha_source.py selftest ITRI     # 故障注入：确认校验器真会变红
```

| 源 | 覆盖 | 独立性 |
|---|---|---|
| SEC + `alpha_metrics.py` | 年度 + 季度 XBRL（基准） | 主源 |
| Yahoo | TTM trailing | 高（独立聚合管道） |
| stockanalysis.com | TTM + 年度 + 分部 | 中（上游同源，解析不同） |
| Nasdaq API | 年度 4 年 | 中（同上） |

判定分四种：`MATCH` / `DEFINITIONAL`（口径可精确解释）/ `MISMATCH`（硬错误）/ `UNCOMPARABLE`（日期不同，按 D-38 不跨期比）。
另有 `FRESHNESS`：第三方已有更新期 → **该更新档案了**，这是信号不是错误。

> 诚实说明：后三个源的上游都是公司申报文件，所以它们**不是**独立证据，
> 只是独立的解析/聚合路径。能抓住"我算错了"，抓不住"公司报错了"。

### 一条命令：行情 → 快照 → 站点

```powershell
py scripts/alpha_quote.py GOOGL --post          # 1. 刷新报价（--post 用盘后价，财报盘后发布时用）
py scripts/pages_build.py --refresh --with-gates # 2. 重生研究快照 + 构建站点 + 全部门禁
```

`site/index.html` 会带上最新档案内容。**`site/` 不入库**（D-75），由本地或 CI 构建。

> `--refresh` 只用于本地：它会让 `data/research_snapshots/` 跟着档案走。
> **CI 不用 `--refresh`**，否则 G9 永远变绿、门禁失去意义。

### 重估赔率审计

当行情变化但尚未修订正式预测时，可以快速重算价格敏感性指标：

```powershell
# 需要手动脚本或 agent 生成，产出示例见 data/revaluations/
# 输入：data/analyses.jsonl 的 weighted_value/bear_value + 最新报价
# 输出：上行/下行/赔率（不写入 predictions/decisions）
```

这类审计属于**追加式研究记录**，应提交到 `data/revaluations/` 以便追溯"当时认为赔率如何"，但**不改写已登记的预测或决策**。

