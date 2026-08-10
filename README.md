# **Kimi Code 额度监控与自动恢复系统**
核心思路是：**后台轮询查额度 → 耗尽时智能等待 → 恢复时强通知提醒**，彻底告别人工盯盘。
## 📦 文件下载


| 文件 | 说明 | 大小 |
|------|------|------|
| `kimi_monitor.py` | 主脚本（单文件，含全部逻辑） | 39 KB |
| `README.md` | 详细使用文档 | 8 KB |
| `start.bat`（Windows） / `start.sh` （Linux / macOS）| 一键启动脚本 | 1 KB |

**下载链接**: [kimi-code-monitor 完整包](sandbox:///mnt/agents/output/kimi-code-monitor/kimi_monitor.py)  
（建议直接下载整个目录使用）


## 🎯 核心解决思路

你的痛点是"额度用完项目中断，一直等待浪费时间"。这个脚本用三层机制解决：

### 1. 额度查询层 — 双端点自动降级
脚本同时尝试两个官方接口获取额度：
- `api.kimi.com/coding/v1/usages` — Kimi Code 专用用量接口（最准确）
- `www.kimi.com/apiv2/.../GetSubscriptionStats` — 会员统计 Connect RPC（备选）

自动读取你本地 `~/.kimi-code/credentials/kimi-code.json` 的 CLI 登录凭证，无需手动填 Token。

### 2. 智能等待层 — 不同额度不同策略
Kimi 的额度是**滚动窗口**，不是固定时间重置：
- **5H 额度耗尽** → 脚本进入短等待（约 5~10 分钟检查一次），因为最早那 1 小时的用量会在约 1 小时后释放
- **周额度耗尽** → 进入长等待（约 1 小时检查一次），因为最早那 1 天的用量会在约 1 天后释放
- 额度紧张时（<15%）→ 加密检查（1 分钟一次），提前预警

### 3. 自动恢复层 — 四种模式可选
| 模式 | 额度恢复后的行为 | 推荐度 |
|------|----------------|--------|
| `notify`（默认）| **弹窗 + 响铃 + 显示下一个待办任务**，提醒你自己继续 | ⭐⭐⭐ 最稳定 |
| `command` | 执行你配置的命令，如 `code ~/project && start kimi-code` | ⭐⭐ 需配置 |
| `api` | 通过 Moonshot API 自动跑非交互式任务 | ⭐ 需 API Key |
| `cli` | 尝试自动打开新的 Kimi Code CLI 窗口 | ⭐ 实验性 |

> 为什么默认用 `notify` 而不是全自动？因为 Kimi Code CLI 是**交互式工具**，真正的"继续开发"需要人的上下文判断。脚本负责**第一时间叫醒你**，而不是越俎代庖。


## 🚀 三步上手

```bash
# 1. 初始化配置（创建 ~/.kimi-monitor/ 目录和 config.yaml）
python kimi_monitor.py --init

# 2. 确保已登录 CLI（脚本会读取凭证）
kimi-code login

# 3. 启动守护模式
python kimi_monitor.py --daemon
```

然后你就可以去干别的了。额度恢复时电脑会**响铃 + 弹窗**，告诉你"可以继续开发了"。


## 🔧 首次使用如遇问题

**如果提示"未找到凭证"**，但你没有装 CLI：
1. 浏览器打开 [kimi.com/code/console](https://kimi.com/code/console)
2. 按 `F12` → `Application` → `Local Storage` → `https://kimi.com`
3. 复制 `access_token` 的值（`eyJhbG...` 开头）
4. 创建文件 `~/.kimi-code/credentials/kimi-code.json`：
   ```json
   {"access_token": "eyJhbG..."}
   ```

**如果想看原始 API 响应**（用于调试字段解析）：
```bash
python kimi_monitor.py --debug
```


## 💡 进阶玩法：任务断点续传

把大项目拆成任务队列，额度耗尽自动保存断点：

```bash
# 添加任务
python kimi_monitor.py --add-task "重构 utils.py" --task-desc "拆分大函数" --task-priority 1
python kimi_monitor.py --add-task "写单元测试" --task-priority 2

# 查看队列
python kimi_monitor.py --list-tasks
```
额度恢复时，通知会告诉你"下一条待办是：重构 utils.py"，直接接着干。

这个脚本纯查询不消耗 Token，可以 7×24 小时挂在后台。如果有 API 响应字段解析问题，把 `--debug` 的输出发给我，我可以帮你调整适配。
