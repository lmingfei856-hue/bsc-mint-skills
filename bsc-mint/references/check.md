# 验收清单

每次改完脚本，按下面逐条验收，全部通过再交。

## 基础

- `python3 -c "import scripts.bsclib"` 不报错，`bsclib.selector("totalSupply()")` 等于 18160ddd。
- `python3 scripts/mint_check.py --help` 正常输出用法。

## 四个种子项目

对下面四个各跑一次 `python3 scripts/mint_check.py <网址>`，逐项核对种子数据：

- KOMA：https://mint.komaai.trade，价格 0.002 BNB/份，免费 1,000 份已领完，总份数 10,000，链上已铸约 1,085，需 Agent ID。
- AKITA：https://akita.bar，价格 0.002 BNB/份，每份 60,000,000 枚，总份数 10,000，已铸满，mint 合约 0xEC8E6ab3adf02F4002E9f0dba0A528c55e99b19c。
- BROCCOLI：https://broccoliagent.com，价格 0.003 BNB/份，每份 30,000,000 枚，总份数 11,000，免费 500 份，代币与铸造同一合约 0xc438821D5937E5246a50f877311a74e40f82eB87。
- BABYDOGE：https://babydoge.meme，价格 0.003 BNB/份，每份 50,000 枚，总份数 10,000，已铸满 10,000，销售合约 0x1208d95b0fff03e0efa818493ef615ebb3934fef。

## 逐项核对标准

- 价格、份数、总量、铸满状态至少要对上。对不上的先修脚本，修不好就写进 TEST_REPORT.md 讲明原因，不许改种子数据去凑测试。
- 历史匹配要命中对应的种子项目，相似度 0.9 以上（地址或域名命中）。
- 报告里每环节耗时都要有数字，总耗时写清。
- 模拟一节要有内容，成功或失败都写明原因。

## CA 输入

- `python3 scripts/mint_check.py 0xB5eF0Da58adA22B5534126143487A448d206E7B3` 应识别为已开盘代币 Neiro，不是 mint 项目。
- `python3 scripts/mint_check.py 0xc438821D5937E5246a50f877311a74e40f82eB87` 应识别为 BROCCOLI，代币与铸造同一合约。
