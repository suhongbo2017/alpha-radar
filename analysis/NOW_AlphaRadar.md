# NOW（ServiceNow, Inc.）— Alpha Radar

> Skill：`alpha-radar` v1.2　｜　报告：`analysis/NOW_MSFT_CRM_BottomUp_Research.md` §5.1
> **Analysis Date**：2026-10-12　｜　**Data Cutoff**：SEC companyfacts 2026-06-30；行情 2026-10-10
> **Current Price**：**$140.86**（NYSE，1 年分位 **54**）
> **⚠️ 2025-12 有 5:1 拆股** —— 所有历史价格已按拆股调整；与旧报告（$137.97）可比
> **数据校验**：`verify_data.py NOW --require-cross` → ✅ 29 / ⚠️ 4 / ❌ **0**
>
> ```bash
> py scripts/alpha_fetch.py NOW --force && py scripts/verify_data.py NOW --require-cross
> py scripts/alpha_metrics.py NOW --score-inputs && py scripts/alpha_quote.py NOW
> ```

---

## 0. 一句话结论

> **NOW 是六家里第一个"赔率达标"的标的（1.36:1），也是第一个 ROIC 低于 WACC 的（9.0% vs 9.2%）。**
> **市场已经杀过它一次（距 52 周高点 −27%），预期已下调，而基本面（RPO +21%、ACV>$5M 客户 +23.5%、续约率 98%）仍在 20%+ 增长。**
> **矛盾点：护城河很强（工作流嵌入 + 统一数据模型），但 GAAP 利润率只有 11.4%、ROIC 仅 9.0% —— 钱都被 SBC 和并购吃掉了。**
>
> **行动：Starter（4–8%）。** 这是六家里唯一"赔率够 + 估值已下调"的组合。

---

## 1. Business

| 项目 | 内容 |
|---|---|
| Business Model | 企业 ITSM / 工作流平台，四类应用：Technology、CRM & Industry、Core Business、Creator |
| Revenue Sources | 订阅制，3 年合同为主；ACV > $5M 的大客户 **658 家（+23.5% YoY）** |
| 关键指标 | **续约率 98%**；RPO +21.3% |
| Competitors | Atlassian、Salesforce、Microsoft（Power Platform）、BMC、freshworks |

---

## 2. Fundamental

| 指标 | 数值 | 备注 |
|---|---:|---|
| Revenue（TTM 2026-06-30） | **$14.73B** | ✅ 与 Yahoo trailing 一致 |
| Revenue Growth（TTM YoY） | **+22.2%** | |
| Organic Growth | ~+21% | 披露口径 |
| Gross Margin | **74.8%** | |
| Operating Margin（GAAP） | **11.4%** | ⚠️ **低** —— SBC 极重 |
| Net Margin | 11.3% | |
| FCF（TTM） | **$4.58B** | |
| FCF Margin | **31.1%** | ✅ 与 GAAP 营业利润率的巨大差距 = SBC |
| Cash Conversion | **274.3%** | ✅ 预收模式 |
| **ROIC** | **9.0%** | ⚠️ NOPAT $1.20B / 投入资本 $13.29B |
| **ROIC vs WACC** | **9.0% vs 9.2%（−0.2pp）** | 🔴 **六家中唯一低于 WACC** |
| Net Debt | **$771M** | 债务 5.43B − (现金+短投 4.66B) |
| Net Debt / EBITDA | 0.28x | ✅ |
| Revenue 5 年 CAGR | **24.1%** | |

> **最关键的矛盾**：收入 5 年 CAGR 24.1%、FCF 利润率 31.1%、续约率 98%，
> 但 **ROIC 只有 9.0%，低于 WACC 9.2%**。
> 原因是双重稀释：① GAAP 口径下 SBC 吃掉近 20pp 的利润率；② 6 个月内商誉从 $3.58B 涨到 **$9.84B**（并购）。
> **这是"好生意、差资本效率"的典型样本。**

---

## 3. Moat

**Moat Score：4.3 / 5　｜　Trend：↑ 加强**

| # | 护城河 | 分 | 依据 |
|---|---|---:|---|
| 1 | 工作流嵌入（转换成本） | **4.5** | 流程跑在 NOW 上后迁移 = 重做企业流程；98% 续约率 + 3 年合同 |
| 2 | 大客户锁定 | **4.5** | ACV > $5M 客户 658 家，**+23.5%** → 企业级渗透在加速而非饱和 |
| 3 | 数据模型统一 | 4.0 | "single data fabric + integrated data layer" —— AI 最需要的上下文 |
| 4 | 规模 / 平台 | 3.5 | |
| 5 | 技术领先 | 3.5 | 但对手是 MSFT / Salesforce |
| 6 | 品牌 | 3.0 | B2B |

> 取**最强三项平均**（4.5/4.5/4.0 → 4.33，取 **4.3**），口径同前（D-36）。

---

## 4. Lifecycle

**Stage 2**（高速成长）—— 收入 +22%、RPO +21%、大客户 +23.5%，尚无减速证据。
但 **ROIC < WACC 说明增长正在毁灭价值**，这是 Stage 2 里罕见的组合。

---

## 5. Fundamental Score

**77.5 / 100 → Good**

| 项目 | 权重 | 输入 | 得分 |
|---|---:|---:|---:|
| Revenue Growth % | 10 | 22.19 | 8.0 |
| Organic Growth % | 10 | 21.0 | 10.0 |
| Gross Margin % | 8 | 74.77 | 8.0 |
| Operating Margin % | 10 | 11.40 | 4.0 |
| FCF Growth % | 12 | 18.99 | **12.0** |
| FCF Margin % | 10 | 31.09 | **10.0** |
| **ROIC %** | 12 | **9.00** | **4.8** |
| Net Debt/EBITDA | 8 | 0.28 | 8.0 |
| Moat | 12 | 4.3 | 10.3 |
| Management | 8 | 3.0 | 4.8 |
| **合计** | | | **77.5** |

**Management 3.0**：运营执行 A（收入/续约率）但**资本配置 C** ——
6 个月商誉 $3.58B→$9.84B，ROIC 被稀释到 WACC 以下；没有任何显性股东回报（无股息）。

---

## 6. Forecast（沿用报告 §5.1）

| 情景 | 概率 | 假设 | FY2031 收入 | FCF 利润率 | FCF | 倍数 | FY2031 价值 |
|---|---:|---|---:|---:|---:|---:|---:|
| **Bull** | 25% | AI 成为新交互层，NOW 拥有执行权；增速回 20%+；并购消化良好 | $40.4B | 35% | $14.1B | 28x | **$384** |
| **Base** | 50% | 增速自然衰减至 15%；利润率稳中略升；AI 渐进贡献 | $30.6B | 32% | $9.8B | 22x | **$209** |
| **Bear** | 25% | Agent 绕过 UI，工作流商品化；ROIC 继续被并购稀释；OCF 持续不增长 | $22.3B | 27% | $6.0B | 14x | **$82** |
| **概率加权** | 100% | | | | | | **$221** |

---

## 7. Valuation

**现价 $140.86　｜　市值 $142.6B（调整拆股后）　｜　净债务 $0.77B　｜　EV ≈ $143.4B**

| 倍数 | 数值 |
|---|---:|
| **EV/FCF（TTM $4.58B）** | **31.3x** |
| Forward PE（FY2027 Non-GAAP EPS $5.01） | **28.1x** |
| 一致预期目标价 | $146.73（**+4.2%**） |
| 距 52 周高点 | **−27%** |

**赔率（一致口径，5 年）**

```text
上行 = 221 / 140.86 − 1 = +56.9%
下行 = 1 − 82 / 140.86 = −41.8%
赔率 = 1.36 : 1     ← ✅ 达标（>1）
5 年 CAGR = 9.4%    ← 不含股东回报（NOW 无股息）
```

**阈值价**（赔率 = 1）：**$152** —— 现价已在阈值之下 ✓

**Valuation Status：Fair（合理）** —— 不是低估，但赔率结构可接受。

---

## 8. Decision

| 价格带 | 价位 | 动作 | 建议仓位 |
|---|---|---:|---:|
| Strong Buy | **< $95** | 强烈关注 | 20–30% |
| Buy | **$95 – $125** | 建仓 | 10–20% |
| **Starter** | **$125 – $160** | 建立观察仓 | **4–8%** |
| Fair | $160 – $220 | 持有观察 | 0–5% |
| Trim | $280 – $380 | 减仓 | — |
| Exit | > $420 | 除非 Bull 验证 | 0% |

- **Current Action：Starter（4–8%）** ← 六家中唯一进入建仓区的
- **仓位依据**：`alpha_score.py size --odds 1.36 --confidence Medium --max-weight 25` → **4–8%**
- **基本面失效条件**：
  1. **续约率跌破 97%** → 护城河出现裂缝（报告指定的关键阈值）
  2. **RPO 增速跌破 15%**
  3. **ACV > $5M 客户增速转负** → 企业级渗透见顶
  4. **再有 > $5B 并购且 ROIC 继续下行** → 资本配置失控
  5. **ROIC 持续低于 WACC**（当前 −0.2pp，若扩大到 −2pp 以上则为结构性毁灭价值）

---

## 9. Investment Thesis

**Bull**：98% 续约率 + 3 年合同 + 统一数据模型（AI 最需要的上下文）+ 大客户 +23.5% + 预期已下调（−27%）+ 赔率 1.36:1
**Bear**：ROIC 9.0% **低于 WACC**（增长毁灭价值）+ GAAP 营业利润率仅 11.4%（SBC 重）+ 商誉半年翻近 3 倍 + 无股东回报 + Agent 可能绕过 UI
**Catalysts**：RPO 转化、续约率、AI 定价能力、并购纪律
**Invalidation**：见 §8 五条

---

## 10. Prediction Ledger

**v1　｜　2026-10-12　｜　FY2031**

| metric | Bull(25%) | Base(50%) | Bear(25%) |
|---|---:|---:|---:|
| Revenue | $40.4B | $30.6B | $22.3B |
| FCF | $14.1B | $9.8B | $6.0B |
| FairValue | $384 | $209 | $82 |

## 11. Review

尚未到期（最早可核对期 FY2031，`resolves_after` = 2032-09-14）。Thesis Status：N/A（首建）。

---

## 附录：方法学与局限

**校验结果**：✅ 29 / ⚠️ 4 / ❌ 0。TTM capex 与 Yahoo trailing 有 **1.24%** 差异（口径，未解释完全）；其余逐项 Δ0.00%。

**局限**
1. **ROIC 9.0% 是 GAAP 口径**，含巨额 SBC。公司 Non-GAAP 口径下 ROIC 会显著更高 ——
   但 **SBC 是真实的股东成本**（稀释），本档案采用 GAAP，并把它记为主要负面因素。
2. **5:1 拆股（2025-12）**：SEC 的 EPS/股数为拆股前口径，本档案的估值倍数用市值/目标市值计算，不受影响。
3. FCF 情景来自报告；本档案未独立重建。