# 历史库字段说明

`data/history.jsonl` 每行一个项目 JSON。字段含义：

- project：项目名，例如 KOMA。
- date：首次核实的日期，格式 YYYY-MM-DD。
- status：open（铸造进行中）、filled（已铸满）、listed（已开盘代币，非 mint 项目）、failed（失败或跑路）、checked（只预检过，未跟踪到底）。
- kind：mint 或 listed_token。listed_token 只做开盘案例，不当 mint 项目匹配。
- sale_contract / mint_contract：销售或铸造合约地址，两个一样时都填。
- token_contract：代币合约地址。
- token_decimals：代币小数位。
- total_supply：代币总量原始值（未除小数位），例如 1000000000000。
- price_bnb：每份价格，单位 BNB，例如 0.002。
- per_lot：每份得多少枚代币原始值，例如 60000000。
- free_per_lot：免费份每份得多少枚，没有免费份填 null。
- total_lots：总份数，例如 10000。
- free_lots：免费份数，没有填 0。
- free_per_id：每个 Agent ID 能领几份免费，没有填 0。
- paid_cap_per_id：每个钱包或 ID 付费上限份数。
- requires_agent_id：true 要求 .ai Agent ID，false 不要求，null 未明确。
- window_start / window_end：铸造窗口，格式 YYYY-MM-DD HH:MM，没有填 null。
- refund_rule：没满额时的退款规则，站内没写填 null。
- sell_tax / buy_tax：买卖税，站内没写填 null。
- selectors：已知函数选择器，例如 {"totalMinted": "a2309ff8"}，键是站内 JS 里的名字或通用名，值是 8 位 hex。
- has_total_minted / has_token_fn / is_proxy：合约结构特征，匹配时用。
- domains：项目站点的域名列表，例如 ["akita.bar"]。
- mint_method：怎么铸造，一句话。
- tx_params：交易参数，例如 {"value_bnb_per_lot": 0.002}。
- fail_reason：失败原因，成功项目填 null。
- anomalies：异常现象列表，每条一句话，只写观测到的事实，不写推断。
- notes：其他备注，例如总量分配、开池情况、审计情况。

## 追加规则

- 每次预检后追加新项目，先核对合约地址、价格、份数和总量。
- 同一个项目重复预检时，更新原行而不是另起一行，改 status、total_supply、anomalies 和 notes。
- 只写核实过的值，没核实到的填 null，不要猜。
