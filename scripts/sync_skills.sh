#!/usr/bin/env bash
# Alpha Radar — skill 同步（P2-16）
# 项目内文件是唯一真源；安装目录是副本。
# 用法: bash scripts/sync_skills.sh [--check]
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${HOME:-/c/Users/Administrator}/.pi/agent/skills"

PAIRS=(
  "Alpha_Radar_SKILL.md:alpha-radar"
  "Investment_Bottom_Up_Research_SKILL.md:investment-bottom-up-research"
)

CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1
rc=0

for pair in "${PAIRS[@]}"; do
  src="$SRC_DIR/${pair%%:*}"
  dest="$DEST_DIR/${pair##*:}/SKILL.md"

  if [[ ! -f "$src" ]]; then
    echo "✗ 源文件缺失: $src"; rc=1; continue
  fi

  if [[ ! -d "$(dirname "$dest")" ]]; then
    mkdir -p "$(dirname "$dest")"
  fi

  if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
    echo "= 已一致: ${pair##*:}"
    continue
  fi

  if [[ $CHECK -eq 1 ]]; then
    echo "⚠ 不一致: ${pair##*:}  (源 $src 与副本 $dest 不同)"
    rc=1
  else
    cp "$src" "$dest"
    echo "✓ 已同步: ${pair##*:} -> $dest"
  fi
done

exit $rc