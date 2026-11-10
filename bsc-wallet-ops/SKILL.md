# BSC 多钱包管理

币安 Agentic Wallet 多钱包的操作规则：按编号管理钱包会话，默认只读，任何 Mint、转账、兑换、授权、签名都要先预览再取得该笔确认。

多钱包会话管理脚本来自社区项目 [0xMulight/binance-wallet-multi](https://github.com/0xMulight/binance-wallet-multi)（MIT），本技能只写操作规则，不复制它的代码。先按该仓库的说明装好，再按下面流程走。安装细节见 [安装与环境](references/setup.md)。

前置条件：官方 `baw` CLI（`@binance/agentic-wallet`，已验证 1.12.0）、`binance-agentic-wallet` Skill、Python 3.10+、文件存储的运行环境（`doctor` 报告 ready=true 才能继续）。

## 建编号

```bash
python3 <skill-dir>/scripts/wallet_profiles.py doctor
python3 <skill-dir>/scripts/wallet_profiles.py init
python3 <skill-dir>/scripts/wallet_profiles.py add --wallet 2
python3 <skill-dir>/scripts/wallet_profiles.py list
```

- `init` 只登记原钱包目录和原 INSTANCE_ID，不读、不覆盖、不清理原会话。
- 新钱包默认用 `~/.baw-wallet2`、`~/.baw-wallet3` 这类独立目录，各自有固定的随机 INSTANCE_ID。不要把所有钱包设成同一个示例名，登录后不要更换。
- 配置默认存于 `~/.config/baw-multi/profiles.json`，里面含实例密钥材料。留在运行机器上，**绝不读给用户、贴进聊天、提交 GitHub、复制进 Skill 或放进跨设备同步文件夹**。

## 逐个配对验收

1. 先只读检查 1 号钱包，不重新登录已连接的钱包：

```bash
python3 <skill-dir>/scripts/wallet_profiles.py run --wallet 1 status
python3 <skill-dir>/scripts/wallet_profiles.py run --wallet 1 address
```

2. 连接 2 号钱包：

```bash
python3 <skill-dir>/scripts/wallet_profiles.py run --wallet 2 signin
```

把实际返回的 pairingCode 和链接原样交给用户，标注这是 2 号钱包，只让用户在币安 App 里核对配对码并确认。不索取密码、私钥、助记词或 API Key。

3. 用本次 signin 实际返回的 qrCodeId：

```bash
python3 <skill-dir>/scripts/wallet_profiles.py run --wallet 2 verify --qr-code-id <实际的 qrCodeId>
```

保持 verify 进程运行至成功、拒绝或约五分钟超时。配对码过期就重新 signin，不反复用旧 qrCodeId。一次只配对一个钱包。

4. 检查所有钱包：

```bash
python3 <skill-dir>/scripts/wallet_profiles.py check
```

要求每个钱包 status 均为 CONNECTED，地址各不相同（同一链上两个编号出现同一个地址就是配错了，停下）。

5. 请用户在 App 里核对编号与地址，再登记用户确认过的真实地址：

```bash
python3 <skill-dir>/scripts/wallet_profiles.py pin --wallet 1 --chain 56 --address <用户确认的地址>
python3 <skill-dir>/scripts/wallet_profiles.py pin --wallet 2 --chain 56 --address <用户确认的地址>
```

脚本会再读一次地址，匹配后才保存。按实际使用的链绑定地址。

6. 再开一个全新命令进程跑一次 `check`。只有状态、地址、用户确认的对应关系全部验证后才报告完成。

## 以后按编号调用

例如“查 2 号余额”：

```bash
python3 <skill-dir>/scripts/wallet_profiles.py run --wallet 2 balance
```

只读操作：status、address、balance、agent-id、settings、chains、tx-history。每次回复都写明编号；编号有歧义时让用户选定，不默认用最近操作的钱包。

会话有期限（48 小时无操作自动退出）和 Developer Mode 有效期，到期只重新配对对应编号，不承诺永久在线。

## 写操作（Mint / 转账 / 兑换 / 授权 / 签名）

脚本本身**不提供**这些入口。需要时按以下顺序：

1. 读币安官方 `binance-agentic-wallet` Skill 的当前命令文档，重新核对指定编号的状态、已绑定地址、链和 Developer Mode。
2. 只在内存里取得目标钱包的环境，不打印、不生成带 INSTANCE_ID 的命令文件。每次 preview 与 execute 用同一编号的环境，串行调用。
3. 展示编号、完整地址、操作、目标合约/收款方、数量、费用和官方 preview 风险。即使免费 Mint 也须获得**该笔操作**的明确确认，不由“配过多钱包”推断交易授权。
4. preview 返回错误就停下。确认后才按官方流程执行；参数、钱包或 requestId 变了就重新预览。交易哈希只表示已提交，确认链上状态后再报告完成。

## 底线

- 默认只读。任何写操作都要先预览、再取得该笔确认。
- 绝不输出 profiles.json、INSTANCE_ID、会话文件里的任何内容；绝不索要助记词、私钥、密码。
- 每次只向当前子进程传入该钱包的环境，不全局 export 一个钱包的变量，不改其他 Bot 的启动环境。
- 不同链出现同一个钱包地址属于正常；检测重复只比较同一链上的地址。

## 子 Bot 交接

需要一个专门的钱包 Bot 时，按一个 Bot 管所有编号的方式建，交接内容不含任何凭证，写清：读哪个 Skill、先自验 doctor/list/check、按编号查询、默认只读、写操作先预览再取得该笔确认、不输出凭证。

## Available connectors

- 这个任务没有合适的连接器，会话管理走本地脚本，链上操作走官方 baw CLI。

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.
