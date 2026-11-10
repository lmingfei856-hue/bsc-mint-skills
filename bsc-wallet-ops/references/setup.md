# 安装与环境

## 装什么

| 组件 | 来源 | 备注 |
|---|---|---|
| 官方 baw CLI | `npm install -g @binance/agentic-wallet` | 已验证 1.12.0；每次命令加 `--json` |
| 官方 Skill 包 | `npx skills add binance/binance-skills-hub --all` | 含 `binance-agentic-wallet` 等 21 个 Skill |
| 多钱包脚本 | `git clone https://github.com/0xMulight/binance-wallet-multi` | 社区项目，MIT；见下方注意事项 |

## 安装多钱包脚本

优先用 git clone 装到 Skill 目录：

```bash
git clone https://github.com/0xMulight/binance-wallet-multi <skills-dir>/binance-wallet-multi
```

实测教训：`npx skills add` 装这个包时可能长时间零输出（曾卡死 45 分钟），不要干等，直接改 git clone。

装好先跑 `doctor`，确认 ready=true、backend=file（文件存储才能隔离多钱包）再继续。

## 环境要求

- Python 3.10+，Node.js，官方 baw CLI 能正常运行。
- 能持久保存本地私有文件。纯聊天环境做不了钱包操作。
- 在 1 号钱包最初登录的同一用户、同一机器、相同环境变量下工作。来源不明的 BINANCE_BAW_DIR / BINANCE_INSTANCE_ID 先查清，不要猜、不要改值、不要试登录。
- 官方 baw 1.12.0 的钥匙串条目是全局共享的，BINANCE_INSTANCE_ID 隔离不了它；只在文件存储环境下继续本流程。

## 常见问题

- **配对码过期**：重新 signin，拿新的 qrCodeId 再 verify，不用旧的。
- **两个编号查到同一个地址**：配错了，停下重查，不要把两个编号当两个钱包用。
- **会话到期**：48 小时无操作自动退出，只重新配对对应编号。
- **Developer Mode 过期**：去币安 App 的 Agentic Wallet 管理页 → 设置 → Developer Mode 重新开。
- **doctor 报告钥匙串可用或版本未审核**：停下，不要改源码、注入 preload、伪造设备身份、关闭钥匙串或自动降级绕过检查。
