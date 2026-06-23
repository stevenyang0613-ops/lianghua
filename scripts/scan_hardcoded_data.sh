#!/bin/bash
set +e
cd "$(dirname "$0")/.."

echo "=== 规则 1: 000000 占位 ==="
result1=$(grep -rnE "(code|etf_code|stock_code)[:=]['\"]000000['\"]" backend/app/ --include="*.py" 2>/dev/null | grep -vE "# |\"\"\"|'''")
if [ -z "$result1" ]; then
  echo "✅ 通过"
else
  echo "❌ 失败:"
  echo "$result1"
  exit 1
fi

echo "=== 规则 2: price=100.0 默认值 ==="
result2=$(grep -rnE "['\"]price['\"]?[:=]100\.0\b" backend/app/ --include="*.py" 2>/dev/null | grep -vE "# |==|!=|<=|>=" | grep -vE "过滤|filter|仅当")
if [ -z "$result2" ]; then
  echo "✅ 通过"
else
  echo "❌ 失败:"
  echo "$result2"
  exit 1
fi

echo "=== 规则 3: 真实债券代码 (后端) ==="
for code in 110052 113052; do
  result3=$(grep -rnE "(code|etf_code)[:=]['\"]$code['\"]" backend/app/ --include="*.py" 2>/dev/null | grep -v "# ")
  if [ -z "$result3" ]; then
    echo "✅ $code 通过"
  else
    echo "❌ $code 失败:"
    echo "$result3"
    exit 1
  fi
done

echo "=== 规则 4: 真实债券代码 (前端) ==="
for code in 110052 113052; do
  result4=$(grep -rnE "code:['\"]$code['\"]" frontend/src/ --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v "__tests__\|test\.")
  if [ -z "$result4" ]; then
    echo "✅ $code 通过"
  else
    echo "❌ $code 失败:"
    echo "$result4"
    exit 1
  fi
done

echo "=== 规则 5: SECTOR_ETF_MAP 重复定义 ==="
count=$(grep -rln "sw_code.*etf_code.*etf_name" frontend/src/ --include="*.ts" --include="*.tsx" 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -le 1 ]; then
  echo "✅ 通过 (仅 1 个定义文件)"
else
  echo "❌ 失败: SECTOR_ETF_MAP 在 $count 个文件中重复定义"
  grep -rln "sw_code.*etf_code.*etf_name" frontend/src/ --include="*.ts" --include="*.tsx"
  exit 1
fi

echo ""
echo "🎉 所有硬编码扫描规则通过！"
