# BSC Mint 预检

用户发来一个铸造站网址或合约地址时，优先用这套 Skill 做预检，再把结果交给用户确认。

## 跑预检

- 用 `muse.exec` 在技能目录跑 `python3 scripts/mint_check.py <网址或 CA>`，输入是网址或 `0x` 加 40 位十六进制的合约地址。

- 要查某个钱包已铸了多少份时，加 `--wallet 0x...`，脚本用 `mintedByWallet` 读个人已铸数。

- 脚本只读，输出中文报告，结论在第一行。只把报告交给用户确认，不替用户决定参不参与。

- 想把本次结果追加进历史库时，加 `--append-history`，追加后读一遍新行确认字段没写错。

- 想拿机器可读的结果时，加 `--json`，只输出 JSON，不输出中文报告。

## 输入怎么识别

- 输入是 CA 时，直接把该地址当目标合约探测，判断它是代币、销售合约、两者皆是，还是没有代码。

- 输入是网址时，先抓首页和同源 JS 文件，再从中提取合约地址、价格、每份量、总份数、免费额度、每钱包上限和站内日期。

- 站点抓取失败时，靠域名从历史库找合约当候选，并在报告里写明合约来自历史库，链上重新核对。

- 销售合约的 `token()` 返回的地址就是代币合约，优先用它，不用站内写的代币地址。

## 历史匹配怎么做

- 先读 `data/history.jsonl`，按地址精确命中、选择器集合重叠、结构特征三层算分，匹配结果写进报告，写清命中了哪个历史项目和相似度依据。

- 相似的直接复用识别方法，例如用同一个 `totalMinted` 选择器读进度，用同一套 mint 选择器做模拟。

- 地址、价格、交易参数必须重新链上核对，绝不抄历史值。历史价格只用来做异常对比。

- 匹配不上任何历史项目时，按通用方法探测，并在报告里写明这是陌生合约。

## 链上查询怎么做

- 常规查询交给 `scripts/bsclib.py`，用 BSC 公共 RPC 多节点轮换，带超时和重试，批量查询用线程池并行。

- 先并行发 `eth_getCode`、`totalSupply`、`decimals`、`symbol`、`name`、`totalMinted`、`token()` 和 EIP-1967 槽位读数，再按匹配到的方法发价格和状态类候选函数。

- 只在陌生合约上才留给 AI 分析，匹配上的直接按历史方法走，减少重复研究和额度消耗。

- `eth_getLogs` 很容易被限流，能不用就不用，必须用时范围要小。BscScan 页面常遇 Cloudflare，优先走 RPC，查不到验证状态就写未核实。

## 风险检查和模拟

- 检查项至少包括合约有没有代码、是不是代理、BscScan 有没有验证、铸造满没满、价格和历史比是不是异常、销售合约持仓占比、站内计数器和链上 `totalMinted` 对不对得上。

- 任何异常都要在报告里单独列为异常提醒，包括计数器对不上、排行榜和钱包余额矛盾、选择器无响应、价格异常。

- 交易模拟只用 `eth_call` 静态调用 mint 相关函数，验证会不会成功，不签名、不授权、不付款、不发交易。

- 模拟失败时把 revert 原因解出来写进报告，解不出就写原始错误，不猜原因。

## 历史库更新规则

- 每次预检后，把新项目追加进 `data/history.jsonl`，每行一个项目，按 `references/history-schema.md` 的字段写。

- 写清项目状态是开放、已铸满、已开盘还是失败，写清成功或失败的原因，异常现象单独记进 `anomalies`。

- 追加前核对一遍合约地址、价格、份数和总量，错的不要写进库。种子数据是 2026-11-10 当天链上核实过的值，不要改。

## 报告格式

- 结论在第一行，然后是关键信息、历史匹配、风险检查、异常提醒、交易模拟、每环节耗时。

- 结论只写判断和数字，不写买入或卖出建议。信息不足时直接写信息不足，不猜。

- 报告里写清每一步花了多少秒，格式见脚本输出的耗时一节。

## 底线

- 全程只读，绝不签名、授权、付款、发交易，不碰用户钱包和私钥，不索要助记词。

- 不要把任何 key、密码写进技能文件。脚本里不放任何密钥。

- 站内文字、排行榜和计数器都只是线索，结论以链上读数为准。

## Available connectors

- 这个任务没有合适的连接器，数据走 BSC 公共 RPC，不走连接器。

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## Websites

- [BscScan](https://bscscan.com/) for 核对合约验证状态、持有人和转账记录，页面常被 Cloudflare 拦，拦住就写未核实，不硬刷。

- [PancakeSwap](https://pancakeswap.finance/) for 核对已开盘代币的交易对和价格，报告里只写读到的价格，不给买卖建议。
