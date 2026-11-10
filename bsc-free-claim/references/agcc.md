# AGCC（Agentic Coin）领奖励 — 已验证

第三方“只有 agent 能挖的币”实验，**明确与币安无关**。这里只写免费领已归属奖励的流程（`claimReward`，value 为 0，不花钱）。

- 官网：https://agcc.fun/
- Mint 合约（唯一的写入口）：`0x6288DFe86f22B53eEB6886aE2D78941de7483743`
- 代币合约：`0x63dea5aCdbE1F27c968907D08610A5f0A0284bA6`
- 交易对：`0xE56041CdDBB46DB01c67B7A62684F428a04Db8C6`
- 注册表 = SPACE ID `0x60B9262456dE011F7d15a54CdD8c48bAaa8B022F`

## 项目背景（只做提醒，不构成推荐）

- 无审计，团队匿名；Owner 可以暂停 mint 7 天、调整税率和参数；买卖税各 2%，fee-on-transfer 代币。
- 两种 mint 模式：A 免费挖（0.002 BNB/份先垫付，24 小时后全额退回 + AGC）；B 入池挖（0.002 BNB/份不退回，奖励 14 天线性释放）。**这两种 mint 都要先花 BNB，不走免费领流程**，只在用户明确同意后才考虑。
- 奖励按纪元递减，总量上限 210B AGC。

## 函数选择器

| 函数 | 选择器 | 说明 |
|---|---|---|
| `claimReward(uint256[])` | `0xc94c7ff4` | 领已归属奖励，传 `[]` 表示按游标从最早的位置开始，最多 50 个位置/次 |
| `claimFree(uint256[])` | `0x73fc9ccc` | 领免费挖的退款 + AGC，同上 |
| `pending(address)` | `0x5eebea20` | 返回 (freeBnb, freeAgc, rewardVested, lpWithdrawable) |
| `userInfo(address)` | `0x1959a002` | 首字段 firstDay（首次 mint 的日期编号） |

未到期的位置会被跳过，不会回退整个交易。

## 领之前链上核对

读 `pending(钱包地址)`，看第 3 个值 rewardVested 是否 > 0。有可领的才继续，没有就停下。

## 调用数据

`claimReward([])`：选择器 `c94c7ff4` + 空数组编码，value = 0。

## 预演预期

2026-11-11 实测 preview：simulationCode `000000000`，无错误；balanceChanges 只有 AGC 进账；allowanceChanges、authorityChanges 为空；risks 为空。

## 实测交易

- 钱包 1：pending rewardVested 382,929 AGC；tx `0xbde9f0e4d8186dea1924fb18b5ce7ada2e0fe5152861de7fa155ec5e161cae24`，区块 132812542，gasUsed 83,363，到账后余额 382,974.91 AGC。
- 钱包 2：pending rewardVested 235,275.68 AGC；tx `0xb76cda2ca766927a74284c27cbec7d56b9f51f54c09e001414bc77b5d56ec910`，区块 132821344，实际到账 +235,337.02 AGC，到账后余额 1,221,423.29 AGC，pending 剩约 9.58（线性释放中，未到期部分下次再领）。
