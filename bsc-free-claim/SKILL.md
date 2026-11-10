# BSC 免费领

`bsc-mint` 预检说某个项目可以免费领之后，用这套流程把免费份领到钱包里。**只做价格严格为 0 的免费领**，任何要花钱的 mint 都不走这里，只做投研。

## 前置条件

- 已安装币安官方 `baw` CLI（`@binance/agentic-wallet`）和 `binance-agentic-wallet` Skill，钱包状态 CONNECTED，Developer Mode 已开启，会话未过期。
- 钱包已领取 Agent ID（`.ai`），免费资格一般都挂在这个上面。
- 先跑过 `bsc-mint` 预检，结论是免费额度还在、钱包符合资格。

不满足就先停下，把缺的条件告诉用户，不硬领。

## 执行流程

### 1. 链上核对资格

按项目参考文档（`references/` 里已验证过的例子）读链上状态，逐项确认：

- 报价函数的 cost 严格为 0，freeShares ≥ 1；
- `isAgent(钱包地址)` 为 true；
- `freeUsed(钱包地址)` 为 false；
- `sharesOf(钱包地址)` 为 0（还没领过）。

任何一项不符就停下，告诉用户哪项不符，不执行。

### 2. 构造调用数据

按项目参考文档给出的函数选择器和参数布局拼 calldata。没有现成参考的新项目，先读合约源码或站点 JS 里的 ABI，确认函数签名、参数顺序和 referrer 处理方式（没有推荐人时一般用零地址），再拼。

不要抄别的项目的选择器。选择器错一个字节，交易就会失败或调错函数。

### 3. 预览（contract-call preview）

按币安官方 `binance-agentic-wallet` Skill 的 `references/external-sign.md` 走 preview：

- 先确认 `wallet settings` 里 `devMode.enabled=true`，没开就停下，告诉用户去币安 App 里开。
- preview 时 `--value` 用 wei（免费领一般是 0）。
- 检查 preview 返回的 `parsedTx`、`simulationResult` 和 `risks`：
  - `balanceChanges` 里只有目标代币进账，没有 BNB 或其他代币被扣；
  - `allowanceChanges` 为空；
  - `authorityChanges` 为空；
  - `risks` 为空；
  - `simulationCode` 为 `000000000`，没有 simulation 错误。

### 4. 确认并执行

- 把预览结果（目标合约、函数、数量、预演变化、风险）展示给用户，取得**该笔操作**的明确确认。
- 确认后用 preview 返回的 `requestId` 调 `contract-call execute`。
- preview 报错、有风险提示、或资格核对没过，立刻放弃并告诉用户原因，不重试、不换参数硬上。

### 5. 核对收据与余额

- 执行后读收据：确认 status 成功、记下区块号和 gas。
- 链上再读一次钱包的目标代币余额和份数，确认到账数量与预期一致。
- 把交易哈希、区块、到账数量报告给用户。

## 底线

- 免费才走这套流程。价格不是 0、或要先付 BNB 再退的模式，一律不自动执行。
- 不签名站内消息，不点站内授权，不在任何页面连接钱包。
- 不索要助记词、私钥、密码、API Key。交易仍需用户在币安 App 里确认的那一步由用户自己完成。
- 站内“先在 X 分享才能领”这类门槛如果只是前端校验、链上不校验，如实说明，不伪造分享行为。
- 不要把任何 key、密码写进技能文件。

## 已验证的例子

- [WNO（War Need Over）](references/wno.md)：免费 1 份 / 钱包，2026-11-11 两个钱包都已领到，交易哈希在文档里。
- [AGCC（Agentic Coin）领奖励](references/agcc.md)：`claimReward([])` 领已归属奖励，2026-11-11 两个钱包都已领到，交易哈希在文档里。

新项目先按这两个例子的格式写参考文档：合约地址、选择器、报价检查、calldata 布局、预演预期、实测交易哈希，缺一项就不算验证过。

## Available connectors

- 这个任务没有合适的连接器，资格核对走 BSC 公共 RPC，执行走官方 baw CLI。

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.
