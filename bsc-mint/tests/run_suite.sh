#!/bin/bash
# 种子项目测试套件：依次跑 6 个用例，间隔 45 秒让公共节点限流恢复。
# 每个用例输出存 tests/run-<name>.txt，末尾打印结论行。
cd "$(dirname "$0")/.."
run_case() {
  local name="$1"; shift
  echo "=== $name : $* ==="
  sleep 45
  timeout 280 python3 scripts/mint_check.py "$@" > "tests/run-$name.txt" 2>&1
  echo "exit=$?"
  grep -m1 "^结论：" "tests/run-$name.txt" || echo "结论：无输出"
  grep -A9 "^耗时" "tests/run-$name.txt" | tr '\n' ' '; echo
}
run_case babydoge https://babydoge.meme/
run_case koma https://mint.komaai.trade
run_case akita https://akita.bar
run_case broccoli https://broccoliagent.com
run_case neiro-ca 0xB5eF0Da58adA22B5534126143487A448d206E7B3
run_case broccoli-ca 0xc438821D5937E5246a50f877311a74e40f82eB87
echo "ALL DONE"
