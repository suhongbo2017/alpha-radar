# RKLB（Rocket Lab Corp）— Alpha Radar

> **Analysis Date**：2026-10-12　｜　**数据校验**：`verify_data.py RKLB --require-cross` → ❌ **0 错误**
> **Current Price**：$68.21　｜　**市值**：42.95B

> ⚠️ **Bull/Base/Bear 由 `alpha_scenario.py` 的规则生成，不是行业研究结论。**
> 规则、参数与已知局限见 §6 与附录。**赔率因此是低置信度的。**

---

## 0. 一句话结论

**早期成长 + 亏损**：收入 $769M、OM **−29.1%**、FCF **−$371M**、ROIC −15.8%。

TTM 收入 +52.5%；但净现金 $2.27B 靠持续融资维持。



---

## 1. Business

小型运载火箭（Electron / Neutron）+ 卫星系统。

## 2. Fundamental（一手数据，已过四层校验）

| 指标 | 数值 |
|---|---:|
| Revenue（TTM） | 0.77B |
| Revenue Growth（TTM YoY） | 52.5% |
| Gross Margin | 37.3% |
| Operating Margin | -29.1% |
| FCF | -0.37B |
| FCF Margin | -48.3% |
| Cash Conversion | 224% |
| ROIC | -15.8% |
| Net Debt | -2.27B |
| Net Debt / EBITDA | 14.01x |
| 股数 | 629.7M |

## 3. Moat

**Moat 3.0**：Electron 的发射记录与 Neutron 的在研地位；但 SpaceX 在成本上碾压。

## 4. Management

**Management 3.5**：技术执行强（发射成功率）；资本配置依赖融资环境。

## 5. Lifecycle

按 §2 的收入增速 / FCF / ROIC 组合判断。

## 6. Forecast —— ⚠️ 规则生成

| 情景 | 概率 | 增速假设 | 利润率系数 | 倍数系数 | 5 年后市值 |
|---|---:|---:|---:|---:|---:|
| Bull | 25% | 18.00% | ×1.10 | ×1.20 | 130B |
| Base | 50% | 10.80% | ×1.00 | ×1.00 | 72B |
| Bear | 25% | 0.00% | ×0.90 | ×0.30 | 12B |
| **加权** | | | | | **71B** |

> 规模上限 18%（市值 42.95B）　｜　
> Bear 倍数 0.30（净杠杆 14.01x ＋ FCF负）

## 7. Valuation

```text
上行 = +66%      下行 = 73%
赔率 = 0.90:1            5 年 CAGR = 10.6%
```

> ⚠️ **规则输出，不是研究结论。** 规则只看「市值规模 + TTM 增速 + 杠杆 + 是否烧钱」，
> **完全不看行业地位、竞争格局、技术路线或管理层**。它会把 NVDA 与 GOOGL 按同一上限处理。

## 8. Decision

**Current Action：Watch（需研究后再决策）**

本档案只有**已校验的定量事实**，没有行业研究。按 Alpha Radar 的纪律 ——
**基本面判断与估值判断必须分开** —— 目前只完成了前者。
在补上真正的行业研究之前，**不应据此建仓或加仓**。

## 9. Investment Thesis

**关键正面**：**早期成长 + 亏损**：收入 $769M、OM **−29.1%**、FCF **−$371M**、ROIC −15.8%。

**主要风险**：**Neutron 首飞是单点事件** —— 成功则打开中型载荷市场，失败则叙事受损。

**已知偏误（必须记录）**：账面无 FCF，估值只能按 PS / EV-Sales 与期权价值看待。规则情景把 Bear 倍数压到 0.30（烧钱 + 高杠杆惩罚），方向正确但幅度无依据。

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
