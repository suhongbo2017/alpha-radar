# data/estimates/ — 分析师一致预期缓存

由 `py scripts/alpha_quote.py <TICKER> --estimates --json` 写入。
来源：Yahoo quoteSummary（需 cookie+crumb，见 SKILL.md §2 的 D-68 说明）。

**已缓存 17 家**：APH ITRI INTU NOW MSFT CRM ASX NVDA GOOGL RKLB ORCL OKLO NFLX KTOS QCOM UMC NVTS
**无覆盖 2 家**：SKHY（韩国）、SPCX（未上市）

用途：**研究级情景的锚**。规则级情景（`alpha_scenario.py`）不用它。
