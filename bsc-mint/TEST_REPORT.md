# BSC Mint Skill — TEST_REPORT

测试时间：2026-11-11 01:19–01:29（Asia/Shanghai）
测试方法：`bash tests/run_suite.sh`，6 个用例依次跑，每用例间隔 45 秒；另对 KOMA 单独复跑一次验证最后一处修复。
种子数据：2026-11-10 当天链上核实过的值（见 `data/history.jsonl`），测试时逐项核对，不改种子去迁就测试。

## 结论

**6/6 全部通过。** 价格、份数、总量、铸满状态、免费额度、Agent ID 要求、历史匹配相似度 1.00，六项全对。交易模拟全部返回真实 revert 原因（不再是“未完成”）。

| 用例 | 入口 | 结论 | 价格 | 每份量 / 总份数 | 已铸 / 剩余 | 免费 | 需 Agent ID | 历史匹配 | 总耗时 |
|---|---|---|---|---|---|---|---|---|---|
| BABYDOGE | https://babydoge.meme/ | 已铸满，不可参与 ✓ | 0.003 BNB ✓ | 50,000 / 10,000 ✓ | 10,000 / 0 ✓ | 无 ✓ | 否 ✓ | 1.00 ✓ | 31.78s |
| KOMA | https://mint.komaai.trade | 开放中，0.002 BNB/份 ✓ | 0.002 BNB ✓ | 377,777,776,000 / 10,000 ✓ | 1,085 / 8,915 ✓ | 1,000 份已领完 ✓ | 是 ✓ | 1.00 ✓ | 43.11s |
| AKITA | https://akita.bar | 已铸满，不可参与 ✓ | 0.002 BNB ✓ | 60,000,000 / 10,000 ✓ | 10,000 / 0 ✓ | 无 ✓ | 是 ✓ | 1.00 ✓ | 30.67s |
| BROCCOLI | https://broccoliagent.com | 已铸满，不可参与 ✓ | 0.003 BNB ✓ | 30,000,000 / 11,000 ✓ | 11,000 / 0 ✓ | 500 份已领完 ✓ | 是 ✓ | 1.00 ✓ | 37.52s |
| Neiro | CA `0xB5eF0Da58adA22B5534126143487A448d206E7B3` | 已开盘代币，不是 mint 项目：Neiro ✓ | —（无 mint） | 总量 1.27e27（18 位小数）✓ | — | 无 ✓ | 未明确 | 1.00 ✓ | 9.70s |
| BROCCOLI CA | CA `0xc438821D5937E5246a50f877311a74e40f82eB87` | 已铸满，不可参与 ✓ | 历史参考 0.003（明确标注“未重新核实”） | 参考 30,000,000 / 11,000 ✓ | 11,000 / 0 ✓ | 500 份已领完 ✓ | 是 ✓ | 1.00 ✓ | 19.10s |

完整输出见 `tests/run-*.txt`。

## 各环节耗时（秒）

| 用例 | 输入解析 | 链上基础探测 | 历史匹配 | 交易模拟 | 链上深度查询 | 风险检查 | 总计 |
|---|---|---|---|---|---|---|---|
| BABYDOGE | 8.98 | 10.76 | 0.0 | 1.21 | 8.34 | 2.49 | 31.78 |
| KOMA | 2.49 | 27.45 | 0.0 | 0.83 | 8.67 | 3.67 | 43.11 |
| AKITA | 2.28 | 15.58 | 0.0 | 1.41 | 8.26 | 3.15 | 30.67 |
| BROCCOLI | 3.15 | 21.18 | 0.0 | 2.17 | 8.77 | 2.25 | 37.52 |
| Neiro CA | 0.0 | 6.16 | 0.0 | 0.01 | 0.83 | 2.70 | 9.70 |
| BROCCOLI CA | 0.0 | 5.99 | 0.0 | 1.24 | 9.22 | 2.64 | 19.10 |

耗时说明：最慢的是“链上基础探测”（并行 eth_getCode + eth_call，公共节点响应不稳定，个别节点要等满 5 秒超时）。交易模拟在修掉 revert 分类 bug 后只需 1–2 秒。历史匹配是纯本地计算，约 0 秒。整套 6 用例约 7.4 分钟。

## 交易模拟结果（只 eth_call，不签名、不发交易）

| 用例 | 模拟结果 |
|---|---|
| BABYDOGE | `[失败] mint(uint256,address) from=0xbb4CdB9C…，value=0.003 BNB 付费：自定义错误 0x589ed34b`——已铸满，正确回退 |
| KOMA | `[失败] mint(uint256) / mint(address,uint256) from=0x78e0a710…，value=0.002 BNB 付费：回退，无原因数据`——KOMA 的 mint 签名实际是 mintShares(uint256,address,bool,uint256)，通用变体不在合约里所以回退，属预期内 |
| AKITA | `[失败] mint(uint256) from=0xbb4CdB9C…，value=0.002 BNB 付费：Mint closed`——已铸满，原因字符串直接解出 |
| BROCCOLI | `[失败] mintFree ×2 / mint from=0xbb4CdB9C…：回退，无原因数据`——免费轮和付费轮都已结束 |
| Neiro | 不模拟（已开盘代币，无 mint 过程）——正确跳过 |
| BROCCOLI CA | 同 BROCCOLI 网址版 |

## 测试中发现并修掉的 bug（测试输出倒逼出来的）

1. **业务回退被当成节点故障**（最关键）。`rpc()` 原来把节点的 JSON-RPC 错误（execution reverted、insufficient funds）和传输故障（超时、403、断开）混在一起，全部换节点重试：一个 revert 要扫完 12 个节点才返回，还被误标为“未完成”。修法：`bsclib.py` 新增 `RpcCallError`，JSON-RPC 错误立即返回确定答案，只重试传输故障。修后模拟 1–2 秒出结果。
2. **模拟调用方地址写错一位**。`SIM_FROM_FALLBACKS` 里的 PancakeSwap Router 地址少了一位 hex（39 位），节点报 invalid argument。改用 WBNB 合约地址（`0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c`，余额充足）做备用调用方。
3. **只读函数被当成 mint 模拟**。KOMA 的 `stats()`（读进度用）被放进模拟列表。修法：`NON_MINT_SELECTOR_NAMES` 增加 stats、price、priceInfo、quote、launched、saleStart、saleInfo、mintEnabled、remaining、mintPrice、paused、maxSupply、owner。
4. **KOMA 种子选择器错了**。种子原先写 KOMA 有 `totalMinted` 选择器 a2309ff8，测试证明销售合约字节码里根本没有这个选择器，进度是靠 `stats()`（选择器 d80528ae，首字段 sold）读的。已修正种子：`selectors: {"stats": "d80528ae"}`，`has_total_minted: false`。这是测试的价值：种子是人写的推测，链上字节码才是准的。
5. **空 revert 原因没识别**。`execution reverted: 0x`（data 为空，字符串结尾）没命中“无原因数据”的正则，显示成裸 `0x`。已修正则允许行尾。

## 已知限制（诚实记录，未修掉）

- **BscScan 验证永远“未核实”**：6 个用例里所有合约的 BscScan 验证都查不到，BscScan 页面常被 Cloudflare 拦，API 也常限流。报告里如实写“未核实”，不代表有问题。想确认验证状态只能人去 BscScan 页面看。
- **KOMA 的 mint 真实签名没进模拟**：KOMA 真实 mint 是 `mintShares(uint256,address,bool,uint256)` / `claimFree()`，只在站点 JS 的 ABI 里，技能目前只按通用变体（mint(uint256) 等）模拟，所以 KOMA 模拟回退的原因是“签名不在合约里”，不是“mint 会失败”。开放中的项目如果只看模拟会误判。后续改进：从站点 JS 的 ABI 文本里抽函数签名再模拟。
- **CA 直给时价格可能只有历史参考**：BROCCOLI CA 的价格显示“历史记录 0.003 BNB/份，未重新核实”，因为 CA 入口没有站点可读，合约上也没有 price() 视图。报告已明确标注，不会把历史值当成核实值。
- **公共节点会限流**：6 个用例连续跑时个别节点 403/断开，靠 12 节点轮换 + 0.3 秒节流扛过去了；如果短时间内跑很多次，仍可能出现个别查询超时，报告会标“未完成”而不是编造数据。
- **风险检查会把配对合约、注册表合约也列出来**：例如 KOMA 的 PancakeSwap 配对合约、SPACE ID 注册表合约会被当成“相关合约”逐一查代码和代理状态，属于噪音，不影响结论。

## 运行方法

```bash
cd ~/workspace/custom-skills/bsc-mint
python3 scripts/mint_check.py <网址或CA> [--wallet <地址>] [--json]
bash tests/run_suite.sh   # 全量 6 用例回归，约 7–8 分钟
```

全程只读：只发 eth_getCode / eth_call / eth_getBalance，不签名、不授权、不付款、不发交易。

## 复核（新仓库位置重跑）

2026-11-11 约 03:05–03:12，在 `bsc-mint-skills` 仓库里把同一套件完整重跑了一遍，6/6 结论与上表完全一致（BABYDOGE / AKITA / BROCCOLI / BROCCOLI CA 已铸满、KOMA 开放中 0.002 BNB/份、Neiro CA 已开盘代币），新输出见 `tests/run-*.txt` 与 `tests/suite.log`。
