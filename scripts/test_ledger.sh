#!/usr/bin/env bash
# Alpha Radar ledger 回归测试（P0-1/2/3 + P1-4/7 + P2-17 + 边界）
cd "$(dirname "$0")/.." || exit 1
L="py scripts/alpha_ledger.py"
pass=0; fail=0
ok()   { echo "  ✓ $1"; pass=$((pass+1)); }
ng()   { echo "  ✗ $1"; fail=$((fail+1)); }
# [D-71] 临时库必须【每次运行唯一】且【断言为空】。
# 旧实现用固定路径 /c/tmp/ar_reg：Windows 上 rm -rf 遇到文件锁会静默失败，
# 而 mkdir -p 仍然成功 → 残留的旧预测会触发"版本冲突" → 写预测的用例全部拿到空输出。
# 实测该残留会让 T1/T2/T4/T7/T8 失败，且是间歇性的（取决于是否有残留进程持锁）。
# flaky 的门禁比没有门禁更糟 —— 它会训练人忽略红灯。
RUN_DIR="/c/tmp/ar_reg_$$"
fresh(){
  export ALPHA_RADAR_HOME="$RUN_DIR"
  rm -rf "$RUN_DIR" 2>/dev/null
  mkdir -p "$RUN_DIR/data"
  if [ -n "$(ls -A "$RUN_DIR/data" 2>/dev/null)" ]; then
    echo "  ✗ 临时库未清空（$RUN_DIR/data 有残留）—— 中止，否则结果不可信"
    exit 1
  fi
}

# ---------- T1 P0-1: Base 计分，不得事后择优 ----------
fresh
$L predict --ticker T --scenario Bear --metric Revenue --period FY2027 --value 0.6e9 --unit USD --prob 0.25 >/dev/null
$L predict --ticker T --scenario Base --metric Revenue --period FY2027 --value 1.0e9 --unit USD --prob 0.45 >/dev/null
$L predict --ticker T --scenario Bull --metric Revenue --period FY2027 --value 1.6e9 --unit USD --prob 0.30 >/dev/null
$L actual  --ticker T --metric Revenue --period FY2027 --value 1.55e9 --unit USD >/dev/null
out=$($L report --ticker T)
echo "$out" | grep -q "+55.0%" && ok "T1 Base 误差 = +55.0%（不再被 Bull 掩盖）" || ng "T1 Base 误差错误"
echo "$out" | grep -q "| \*\*D\*\* |" && ok "T1 评级 = D" || ng "T1 评级错误"
echo "$out" | grep -q "区间命中率：1/1 = 100%" && ok "T1 区间命中率独立统计" || ng "T1 缺区间命中率"

# ---------- T2 P0-2: 版本隔离 ----------
fresh
$L predict --ticker T --scenario Base --metric Revenue --period FY2030 --value 45e9 --unit USD --version v1 >/dev/null
if $L predict --ticker T --scenario Base --metric Revenue --period FY2030 --value 50e9 --unit USD --version v1 >/dev/null 2>&1; then
  ng "T2 同版本改数未被拒绝"; else ok "T2 同版本改数被拒绝"; fi
$L predict --ticker T --scenario Base --metric Revenue --period FY2030 --value 60e9 --unit USD --version v2 >/dev/null
$L actual  --ticker T --metric Revenue --period FY2030 --value 47e9 --unit USD >/dev/null
out=$($L report --ticker T)
echo "$out" | grep -q "| T | Revenue | 2030 | v2 |" && ok "T2 主评分用最新版本 v2" || ng "T2 未用最新版本"
echo "$out" | grep -q "历史版本对照" && echo "$out" | grep -q "| T | Revenue | 2030 | v1 |" && ok "T2 v1 单列于历史版本" || ng "T2 缺历史版本对照"

# ---------- T3 P0-3: 单位校验 ----------
fresh
$L predict --ticker T --scenario Base --metric Revenue --period FY2030 --value 1.45e12 --unit TWD >/dev/null
if $L actual --ticker T --metric Revenue --period FY2030 --value 46e9 --unit USD >/dev/null 2>&1; then
  ng "T3 单位不一致未被拒绝"; else ok "T3 单位不一致被拒绝"; fi
$L actual --ticker T --metric Revenue --period FY2030 --value 46e9 --unit USD --force >/dev/null
out=$($L report --ticker T)
echo "$out" | grep -q "单位不一致" && ok "T3 force 录入后报告留痕" || ng "T3 无留痕"
echo "$out" | grep -q "单位不一致 1 条" && ok "T3 计数与待公布区分" || ng "T3 计数混入待公布"
echo "$out" | grep -q "尚无已兑现的 fundamental" && ok "T3 排除出评分" || ng "T3 未排除评分"

# ---------- T4 P1-4: 指标词表 ----------
fresh
if $L predict --ticker T --scenario Base --metric RevenueXX --period FY2030 --value 1e9 >/dev/null 2>&1; then
  ng "T4 未知指标未被拒绝"; else ok "T4 未知指标被拒绝"; fi
# 断言精确的归一结果（不用 --allow-custom，否则会掩盖归一失败）
i=0
while IFS='|' read -r raw want; do
  i=$((i+1))
  got=$($L predict --ticker "Q$i" --scenario Base --metric "$raw" --period "FY2030" --value 1 --unit X 2>&1 \
        | grep -o '"metric": "[^"]*"' | head -1 | sed 's/.*: "\(.*\)"/\1/')
  if [[ "$got" == "$want" ]]; then ok "T4 '$raw' -> $want"; else ng "T4 '$raw' -> 实得 '$got'，期望 '$want'"; fi
done <<'EOF'
Revenues|Revenue
revenues|Revenue
sales|Revenue
营业收入|Revenue
毛利率|Gross_Margin
自由现金流|FCF
净债务/EBITDA|Net_Debt_EBITDA
Net Debt/EBITDA|Net_Debt_EBITDA
Net-Debt-EBITDA|Net_Debt_EBITDA
Cash Conversion|Cash_Conversion
fcf/revenue|Cash_Conversion
ROIC|ROIC
btb|Book_to_Bill
fv|FairValue
每股收益|EPS
EOF

# ---------- T5 P1-7: 估值类不计分 ----------
fresh
$L predict --ticker T --scenario Base --metric FairValue --period FY2030 --value 65 --unit USD >/dev/null
$L actual  --ticker T --metric FairValue --period FY2030 --value 70 --unit USD >/dev/null
out=$($L report --ticker T)
echo "$out" | grep -q "不计分（估值类）1 条" && ok "T5 估值类计数正确" || ng "T5 估值类计数错误"
echo "$out" | sed -n '/## 1\./,/## 2\./p' | grep -q "FairValue" && ng "T5 估值类混入主评分" || ok "T5 估值类未混入主评分"
echo "$out" | grep -q "| T | FairValue | 2030 | v1 | Base |" && ok "T5 估值类出现在第 4 节" || ng "T5 估值类未出现在第 4 节"

# ---------- T6 P2-17: 重复拒绝 ----------
fresh
$L predict --ticker T --scenario Base --metric Revenue --period FY2030 --value 10e9 --unit USD >/dev/null
if $L predict --ticker T --scenario Base --metric Revenue --period FY2030 --value 10e9 --unit USD >/dev/null 2>&1; then
  ng "T6 重复未被拒绝"; else ok "T6 重复被拒绝"; fi

# ---------- T7 单位分组 ----------
fresh
$L predict --ticker A --scenario Base --metric Revenue --period FY2027 --value 100e9 --unit USD >/dev/null
$L actual  --ticker A --metric Revenue --period FY2027 --value 104e9 --unit USD >/dev/null
$L predict --ticker B --scenario Base --metric Revenue --period FY2027 --value 1000e9 --unit TWD >/dev/null
$L actual  --ticker B --metric Revenue --period FY2027 --value 700e9 --unit TWD >/dev/null
out=$($L report)
echo "$out" | grep -q "| A | Revenue | USD | 1 | 4.0% | A |" && ok "T7 A: USD 4.0% A级" || ng "T7 A 错误"
echo "$out" | grep -q "| B | Revenue | TWD | 1 | 30.0% | D |" && ok "T7 B: TWD 30.0% D级（未与A混合）" || ng "T7 B 错误"

# ---------- T8 边界与健壮性 ----------
fresh
$L report >/dev/null 2>&1 && ok "T8 空库 report 不崩" || ng "T8 空库崩溃"
$L predict --ticker T --scenario Base --metric EPS --period Q3FY2027 --value 1.5 --unit USD 2>&1 | grep -q '"forecast_period": "Q32027"' && ok "T8 Q3FY2027 -> Q32027" || ng "T8 期间归一错误"
$L predict --ticker T --scenario Base --metric EPS --period 2028Q1 --value 1.6 --unit USD 2>&1 | grep -q '"forecast_period": "Q12028"' && ok "T8 2028Q1 -> Q12028" || ng "T8 期间归一错误"
$L predict --ticker T --scenario Base --metric Revenue --period FY2030 --value 1 --unit USD --prob 1.5 >/dev/null 2>&1 && ng "T8 prob 未校验" || ok "T8 prob 越界被拒"
$L predict --ticker T --scenario Base --metric 毛利率 --period FY2031 --value 38.9 --unit '%' >/dev/null 2>&1 && ok "T8 百分号单位可写" || ng "T8 百分号单位失败"
$L export >/dev/null && ok "T8 export 正常" || ng "T8 export 失败"
$L metrics >/dev/null && ok "T8 metrics 正常" || ng "T8 metrics 失败"

# ---------- T9 [D-05] Decision Database ----------
fresh
$L decision --ticker T --action Watch --price 88.62 --odds 0.5 --reason "赔率低" --date 2026-01-05 >/dev/null \
  && ok "T9 decision 写入成功" || ng "T9 decision 写入失败"
if $L decision --ticker T --action Buy --odds 2 >/dev/null 2>&1; then
  ng "T9 缺 --price 应报错却通过"; fi
$L decision --ticker T --action Bogus --price 10 2>&1 | grep -q "未知动作" && ok "T9 非法动作被拒" || ng "T9 非法动作未拒"
out=$($L decisions --ticker T); echo "$out" | grep -q "Watch" && ok "T9 decisions 列表可读" || ng "T9 decisions 列表失败"
out=$($L report --ticker T --price T=92.5)
echo "$out" | grep -q "## 8. 决策 vs 结果" && ok "T9 报告含第 8 节" || ng "T9 报告缺第 8 节"
# [D-30] 周期<90天不得年化：旧 bug 会把 1 天回报年化成 +620362019%
TODAY=$(date +%Y-%m-%d)
$L decision --ticker T --action Watch --price 90 --odds 2 --date "$TODAY" >/dev/null
out=$($L report --ticker T --price T=92.5)
echo "$out" | grep -q "n/a(" && ok "T9 [D-30] 周期过短不年化" || ng "T9 [D-30] 年化未加护栏"
if echo "$out" | grep -qE "[0-9]{6,}\.0%"; then
  ng "T9 [D-30] 仍出现天文数字年化"; else ok "T9 [D-30] 无天文数字年化"; fi
$L decision --ticker T --action StrongBuy --price 92 --odds 0.4 --date 2026-01-05 >/dev/null
out=$($L report --ticker T)
echo "$out" | grep -q "违反赔率纪律" && ok "T9 赔率<1 建仓被标违规" || ng "T9 赔率纪律未生效"

# ---------- T10 [D-06] due ----------
fresh
$L predict --ticker T --scenario Base --metric Revenue --period FY2027 --value 1e9 --unit USD >/dev/null
out=$($L due --asof 2030-06-01)
echo "$out" | grep -q "FY2027\|2027" && ok "T10 到期预测被列出" || ng "T10 due 未列出"
$L due --asof 2026-01-01 | grep -q "没有到期未复盘" && ok "T10 未到期时不误报" || ng "T10 due 误报"
$L actual --ticker T --metric Revenue --period FY2027 --value 1e9 --unit USD >/dev/null
$L due --asof 2030-06-01 | grep -q "没有到期未复盘" && ok "T10 已复盘后不再列出" || ng "T10 due 未销销"

# ---------- T11 [D-08] 概率加权预测 ----------
fresh
$L predict --ticker T --scenario Bear --metric Revenue --period FY2031 --value 30e9 --unit USD --prob 0.25 >/dev/null
$L predict --ticker T --scenario Base --metric Revenue --period FY2031 --value 45e9 --unit USD --prob 0.45 >/dev/null
$L predict --ticker T --scenario Bull --metric Revenue --period FY2031 --value 62e9 --unit USD --prob 0.30 >/dev/null
$L actual --ticker T --metric Revenue --period FY2031 --value 44e9 --unit USD >/dev/null
out=$($L report --ticker T)
# 0.25*30 + 0.45*45 + 0.30*62 = 7.5 + 20.25 + 18.6 = 46.35
echo "$out" | grep -q "USD 46.35B" && ok "T11 概率加权 = 46.35B（手算一致）" || ng "T11 概率加权算错"
echo "$out" | grep -q "## 2. 概率加权预测 vs 实际" && ok "T11 报告含第 2 节" || ng "T11 缺第 2 节"
# 缺概率时不计算
fresh
$L predict --ticker T --scenario Base --metric Revenue --period FY2031 --value 45e9 --unit USD >/dev/null
$L actual --ticker T --metric Revenue --period FY2031 --value 44e9 --unit USD >/dev/null
$L report --ticker T | grep -q "无三情景概率齐全" && ok "T11 缺概率时不乱算" || ng "T11 缺概率时仍然计算"

# ---------- T12 [D-09] 归因 ----------
fresh
$L predict --ticker T --scenario Base --metric Revenue --period FY2027 --value 1e9 --unit USD >/dev/null
$L actual --ticker T --metric Revenue --period FY2027 --value 1.1e9 --unit USD --attribution 需求 >/dev/null \
  && ok "T12 --attribution 中文别名归一" || ng "T12 归因录入失败"
if $L actual --ticker T --metric Revenue --period FY2028 --value 1e9 --unit USD --attribution Bogus >/dev/null 2>&1; then
  ng "T12 非法归因未拒"; fi
$L predict --ticker T --scenario Base --metric Revenue --period FY2028 --value 1e9 --unit USD >/dev/null
$L attribute --ticker T --metric Revenue --period FY2028 --attribution Margin --note "test" >/dev/null \
  && ok "T12 attribute 追记可用" || ng "T12 attribute 失败"
out=$($L report --ticker T)
echo "$out" | grep -q "## 7. 误差归因分布" && ok "T12 报告含第 7 节" || ng "T12 缺第 7 节"
echo "$out" | grep -q "Demand" && echo "$out" | grep -q "Margin" && ok "T12 两类归因均统计" || ng "T12 归因聚合不全"

# ---------- T13 alpha_score.py ----------
S="py scripts/alpha_score.py"
out=$($S score --revenue-growth 8 --organic-growth 6 --gross-margin 39 --operating-margin 28 \
      --fcf-growth 22 --fcf-margin 19 --roic 20.2 --net-debt-ebitda 2.1 --moat 4.2 --management 4.0)
out2=$($S score --revenue-growth 8 --organic-growth 6 --gross-margin 39 --operating-margin 28 \
      --fcf-growth 22 --fcf-margin 19 --roic 20.2 --net-debt-ebitda 2.1 --moat 4.2 --management 4.0)
[ "$out" = "$out2" ] && ok "T13 [D-10] 同输入同分数（可复现）" || ng "T13 [D-10] 分数不可复现"
echo "$out" | grep -q "77.7" && ok "T13 [D-10] 分数值符合预期（77.7）" || ng "T13 [D-10] 分数值异常"
$S size --odds 0.5 --confidence High | grep -q "不建仓" && ok "T13 [D-11] 赔率0.5 不建仓" || ng "T13 [D-11] 赔率硬规则失效"
$S size --odds 3.9 --confidence Medium --max-weight 25 | grep -q "16–25%" && ok "T13 [D-11] 赔率3.9 给 16-25%" || ng "T13 [D-11] 仓位计算错误"
$S lite --revenue-growth 55 --moat-trend up --valuation-pct 97 | grep -q "观察名单" && ok "T13 [D-12] Lite 高位→观察名单" || ng "T13 [D-12] Lite 判定错误"
$S lite --revenue-growth -5 --moat-trend down --valuation-pct 20 | grep -q "放弃" && ok "T13 [D-12] Lite 双降→放弃" || ng "T13 [D-12] Lite 放弃判定错误"
$S lite --revenue-growth 18 --moat-trend up --valuation-pct 45 | grep -q "升级到完整" && ok "T13 [D-12] Lite 三满足→升级" || ng "T13 [D-12] Lite 升级判定错误"

unset ALPHA_RADAR_HOME; rm -rf "$RUN_DIR" 2>/dev/null
echo
echo "════════════════════════════"
echo "  通过 $pass / 失败 $fail"
echo "════════════════════════════"
[[ $fail -eq 0 ]]