# SKHY（SK hynix（韩国，ADR））— Alpha Radar

> **Analysis Date**：2026-10-12　｜　**数据校验**：`verify_data.py SKHY --require-cross` → ❌ **0 错误**
> **Current Price**：—　｜　**市值**：—

> ⚠️ **Bull/Base/Bear 由 `alpha_scenario.py` 的规则生成，不是行业研究结论。**
> 规则、参数与已知局限见 §6 与附录。**赔率因此是低置信度的。**

---

## 0. 一句话结论

⚠️ **无法用 Alpha Radar 建档**：SK hynix 是韩国公司，在 SEC 的申报**只有 `ffd` 分类标准的 5 个 tag**（证券发行的费用/金额），**没有任何财务报表数据**。

需要韩国 DART 一手申报，本工具链（只接 SEC）无法取得。

**→ 因此本档案只记录事实，不给出估值与赔率。**

---

## 1. Business

DRAM / HBM / NAND 存储芯片。

## 2. Fundamental（一手数据，已过四层校验）

| 指标 | 数值 |
|---|---:|
| Revenue（TTM） | — |
| Revenue Growth（TTM YoY） | —% |
| Gross Margin | —% |
| Operating Margin | —% |
| FCF | — |
| FCF Margin | —% |
| Cash Conversion | —% |
| ROIC | —% |
| Net Debt | — |
| Net Debt / EBITDA | —x |
| 股数 | — |

## 3. Moat

无法评估（无一手财务数据）。**但作为 HBM 的主要供应商，它是 AI 算力链上的真实瓶颈环节。**

## 4. Management

无法评估。

## 5. Lifecycle

按 §2 的收入增速 / FCF / ROIC 组合判断。

## 6. Forecast —— ⚠️ 规则生成

| 情景 | 概率 | 增速假设 | 利润率系数 | 倍数系数 | 5 年后市值 |
|---|---:|---:|---:|---:|---:|
| Bull | 25% | 0.00% | ×1.10 | ×1.20 | 0B |
| Base | 50% | 0.00% | ×1.00 | ×1.00 | 0B |
| Bear | 25% | 0.00% | ×0.90 | ×0.00 | 0B |
| **加权** | | | | | **0B** |

> 规模上限 0%（市值 —）　｜　
> Bear 倍数 0.00（净杠杆 —x ＋ FCF正）

## 7. Valuation

```text
上行 = +0%      下行 = 0%
赔率 = 0.00:1            5 年 CAGR = 0.0%
```

> ⚠️ **规则输出，不是研究结论。** 规则只看「市值规模 + TTM 增速 + 杠杆 + 是否烧钱」，
> **完全不看行业地位、竞争格局、技术路线或管理层**。它会把 NVDA 与 GOOGL 按同一上限处理。

## 8. Decision

**Current Action：Watch（需研究后再决策）**

本档案只有**已校验的定量事实**，没有行业研究。按 Alpha Radar 的纪律 ——
**基本面判断与估值判断必须分开** —— 目前只完成了前者。
在补上真正的行业研究之前，**不应据此建仓或加仓**。

## 9. Investment Thesis

**关键正面**：⚠️ **无法用 Alpha Radar 建档**：SK hynix 是韩国公司，在 SEC 的申报**只有 `ffd` 分类标准的 5 个 tag**（证券发行的费用/金额），**没有任何财务报表数据**。

**主要风险**：存储是强周期行业；HBM 的份额与定价是核心变量。

**已知偏误（必须记录）**：🔴 **本档案是"无法建档"的说明。** 要分析 SK hynix 需要接入韩国 DART，这是本工具链当前的覆盖边界（description 已注明"港股/A股为实验性"，**韩国市场应一并列入未覆盖**）。

## 10. Prediction Ledger

本次**不登记预测**。规则生成的情景没有表达任何关于行业的观点，
因此**不具备"可被未来数据证伪"的资格** —— 登记它会污染预测账本。
待补上行业研究后，再以 v1 登记。

## 11. Review

尚未开始（无预测）。

---

## 附录：方法与局限

**数据**：SEC companyfacts（一手），已过 `verify_data.py` 四层校验（会计恒等式、时间一致性、
第三方交叉、量纲），**硬错误 0**。外币申报（—）按 XBRL 提供的 USD 单位取值。

**局限（必读）**
1. **情景是规则生成的**，见 `scripts/alpha_scenario.py` 头部。结构性缺陷：只看规模与增速，不看行业。
2. **规则对四类公司无效**：pre-revenue（OKLO / SPCX）、零增长现金牛（QCOM）、
   收入崩塌中（NVTS）、ADR 市值不可靠（ASX / UMC）。
3. **未使用一致预期**，无分析师预测交叉验证。
4. **Moat / Management 为定性判断**，未经系统化证据采集（不像前 6 份有 Bottom-Up 报告支撑）。
