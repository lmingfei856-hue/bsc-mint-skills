# bsc-mint-skills

给币安 Agent ID 持有者的 BSC 免费打新技能包：先预检，再领，再管钱包。全程只读打底，写操作先预览、再确认。

English summary: Agent skills for BSC free mints gated by Binance Agent ID. Pre-check a mint site or contract address, claim free shares through the official `baw` CLI preview-then-execute flow, and manage multiple Agentic Wallets by number. Read-only by default; every write is previewed and confirmed per transaction. Free and open source (MIT). Not affiliated with Binance.

## 包含的三个技能

| 技能 | 做什么 | 状态 |
|---|---|---|
| [bsc-mint](bsc-mint/) | 发网址或合约地址，自动识别 mint 合约、价格、钱包资格、剩余额度和开放状态，匹配历史经验库，跑风险检查和静态交易模拟，输出中文预检报告 | 已实测，6/6 通过（2026-11-11） |
| [bsc-free-claim](bsc-free-claim/) | 免费领的执行流程：链上核对免费资格与价格严格为 0，走官方 baw `contract-call` 预览，预演干净才执行，核对收据与余额后报告交易哈希 | 已实测，WNO、AGCC 各两个钱包 |
| [bsc-wallet-ops](bsc-wallet-ops/) | 多钱包操作规则：按编号管理钱包会话，默认只读，写操作先预览再取得该笔确认 | 已实测，双钱包配对 + pin 通过 |

## 快速开始

前置条件：Node.js、Python 3.10+、币安 App 里已开 Agentic Wallet 并领取 Agent ID（`.ai`）。

```bash
# 1. 装官方 baw CLI 和官方 Skill 包
npm install -g @binance/agentic-wallet
npx skills add binance/binance-skills-hub --all

# 2. 装本仓库
npx skills add lmingfei856-hue/bsc-mint-skills --all
# 或直接克隆到技能目录
git clone https://github.com/lmingfei856-hue/bsc-mint-skills.git

# 3. 多钱包管理脚本（社区项目，MIT）
git clone https://github.com/0xMulight/binance-wallet-multi.git
```

## 典型流程

```
用户发来一个 mint 网址或合约地址
  → bsc-mint 预检：价格、资格、剩余额度、风险、模拟
  → 免费份还在、价格严格为 0
  → bsc-free-claim：链上核对资格 → preview → 确认 → 执行 → 核对到账
  → 多钱包时用 bsc-wallet-ops 按编号操作
```

花钱的 mint 不自动执行，只做投研简报，等用户明确回复“确认买入 XX 金额”才动手。

## 安全底线

- 默认只读：预检全程只发 `eth_getCode` / `eth_call` / `eth_getBalance`，不签名、不授权、不付款、不发交易。
- 写操作三件套：先 preview 看 `parsedTx`、模拟变化和风险 → 展示给用户并取得该笔确认 → 再 execute；preview 报错或有风险立刻放弃。
- 不索要助记词、私钥、密码、API Key；不把任何凭证写进文件、聊天记录或仓库。
- 站内文字、排行榜和计数器都只是线索，结论以链上读数为准。

## 实测证据

- `bsc-mint`：2026-11-11 全量 6 用例回归通过，价格、份数、总量、铸满状态、免费额度、历史匹配全部对上，见 [bsc-mint/TEST_REPORT.md](bsc-mint/TEST_REPORT.md)。
- WNO 免费领：钱包 1 交易 `0x859527f8fe0f45c5f0ec0d2614e5805409624f5ea3f4a13e3c1e2e467e3bd7e5`，钱包 2 交易 `0x54e740f4819094405d043019bb0c676f1a9f8fdb2a02878862620a53679fa021`，各到账 1,000,000 WNO。
- AGCC 领奖励：钱包 1 交易 `0xbde9f0e4d8186dea1924fb18b5ce7ada2e0fe5152861de7fa155ec5e161cae24`（+382,974.91 AGC），钱包 2 交易 `0xb76cda2ca766927a74284c27cbec7d56b9f51f54c09e001414bc77b5d56ec910`（+235,337.02 AGC）。

## 付费服务

技能本身免费开源。需要人手帮忙的付费服务：代搭 99 元/次（按这套流程帮你配好钱包和技能）、代跑 29 元/次（定期预检 + 免费领执行）、进阶版 199 元（更多项目模板、私有历史库）。新用户首单可先免费预检，预检不通过不收费。

下单入口：
- GitHub：在本仓库提 Issue（说明要代搭、代跑还是进阶版）
- 闲鱼代跑服务：https://www.goofish.com/item?id=1098241950077
- 币安广场接单帖：https://app.binance.com/uni-qr/cpos/386858835552072?r=Y78Y7HKB&l=en

## 致谢

- 币安官方 [binance-skills-hub](https://github.com/binance/binance-skills-hub)：`baw` CLI 与官方 Skill。
- [0xMulight/binance-wallet-multi](https://github.com/0xMulight/binance-wallet-multi)（MIT）：多钱包会话管理脚本。

## 免责声明

- 与币安、SPACE ID、PancakeSwap 无任何隶属、合作或背书关系。
- 覆盖的项目多为第三方实验 memecoin，无审计、团队匿名，价格可能归零；本仓库只提供信息和工具，不构成任何投资建议，DYOR。
- 免费领不代表代币有价值：已领到的 KOMA、WNO 在写这份文档时都还没有可交易市场。

## License

MIT，见 [LICENSE](LICENSE)。
