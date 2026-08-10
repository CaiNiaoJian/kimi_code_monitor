# Kimi Code 额度监控与自动恢复系统

> 实时监控 Kimi Code 的 **5小时滚动额度** 和 **7天周额度**，额度耗尽时智能等待，恢复时第一时间通知你继续开发，告别人工盯盘。

---

## 📦 文件下载

| 文件 | 说明 | 大小 | 推荐场景 |
|------|------|------|---------|
| `kimi_monitor.py` | **基础版** — 单文件，含全部核心逻辑 | 39 KB | 追求极简、快速上手 |
| `kimi_monitor_pro.py` | **Pro 版** — 额度预测 + 开发教练 + Web 仪表盘 + 成就系统 | 60 KB | 追求智能化、可视化、游戏化 |
| `README.md` | 本文档 | — | — |
| `start.bat` / `start.sh` | 一键启动脚本 | 1 KB | Windows / Linux / macOS |

**下载链接**:
- [kimi_monitor.py (基础版)](sandbox:///mnt/agents/output/kimi-code-monitor/kimi_monitor.py)
- [kimi_monitor_pro.py (Pro 版)](sandbox:///mnt/agents/output/kimi-code-monitor/kimi_monitor_pro.py)

> 💡 **新手建议**: 先用基础版跑通，熟悉后再升级 Pro 版。两个版本独立运行，互不冲突。

---

## 🎯 核心解决思路

你的痛点是"额度用完项目中断，一直等待浪费时间"。脚本用三层机制解决：

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

---

## 🚀 基础版快速上手

```bash
# 1. 初始化配置（创建 ~/.kimi-monitor/ 目录和 config.yaml）
python kimi_monitor.py --init

# 2. 确保已登录 CLI（脚本会读取凭证）
kimi-code login

# 3. 启动守护模式
python kimi_monitor.py --daemon
```

然后你就可以去干别的了。额度恢复时电脑会**响铃 + 弹窗**，告诉你"可以继续开发了"。

### 基础版 CLI 命令

```bash
python kimi_monitor.py --init          # 初始化配置
python kimi_monitor.py --once          # 单次查询额度状态
python kimi_monitor.py --daemon        # 后台守护模式
python kimi_monitor.py --add-task "重构utils.py"  # 添加开发任务
python kimi_monitor.py --list-tasks    # 查看任务队列
python kimi_monitor.py --debug         # 调试：查看原始API响应
```

---

## 🧠 Pro 版 — 智能开发辅助系统

Pro 版在基础版的"查询 + 通知"之上，升级为一套**额度感知的工作流调度系统**。不只是"告诉你额度没了"，而是**根据额度状态主动帮你规划该干什么**。

### Pro 版八大特性

| # | 特性 | 解决什么问题 |
|---|------|-------------|
| 1 | **额度预测引擎** | 基于历史曲线预测"还能用多久"、"什么时候恢复"，告别盲目等待 |
| 2 | **智能开发教练** | 根据实时额度推荐四种工作模式（深度/专注/轻量/离线），额度紧张时知道该干什么 |
| 3 | **Git 自动保存** | 额度 < 8% 时自动 `git commit`，工作成果零丢失 |
| 4 | **语音播报系统** | TTS 语音提醒 + 自定义音效，额度恢复时直接"喊"你回来 |
| 5 | **Web 仪表盘** | 本地暗色主题实时面板 `http://127.0.0.1:17421`，额度曲线、任务、成就一目了然 |
| 6 | **多账号轮询** | 支持配置多个 Kimi 账号，主号耗尽自动切备用号 |
| 7 | **额度感知番茄钟** | 额度充足 → 标准 25/5；额度紧张 → 自动缩短专注时间等恢复；耗尽 → 进入离线学习模式 |
| 8 | **成就系统** | 游戏化设计，解锁"节流专家""深夜战神""Git 救星"等称号 |

### Pro 版设计哲学

额度管理不应该只是"监控"，而应该是**"调度"**：

- **额度充足** → 火力全开，处理最难的架构问题（深度模式）
- **额度中等** → 专注实现，控制节奏（专注模式）
- **额度紧张** → 自动节流，只做轻量工作（轻量模式）
- **额度耗尽** → 不是干等，而是进入有价值的离线模式（读文档、写测试、理思路）

配合**预测引擎**提前知道"还能用多久"，配合**Git 自动保存**确保不丢成果，配合**语音 + Web 仪表盘**让你不错过恢复时机。

### Pro 版快速上手

```bash
# 1. 初始化（与基础版共用配置目录，但配置项更丰富）
python kimi_monitor_pro.py --init

# 2. 启动完整守护（含 Web 仪表盘 + 语音 + 预测）
python kimi_monitor_pro.py --daemon

# 3. 浏览器打开仪表盘
open http://127.0.0.1:17421   # macOS
start http://127.0.0.1:17421  # Windows
```

### Pro 版专属 CLI 命令

```bash
python kimi_monitor_pro.py --daemon              # 启动完整守护(含Web仪表盘)
python kimi_monitor_pro.py --daemon --no-web     # 纯后台模式（无仪表盘）
python kimi_monitor_pro.py --forecast            # 查看额度预测报告
python kimi_monitor_pro.py --coach               # 查看当前开发建议
python kimi_monitor_pro.py --dashboard-only      # 仅启动Web仪表盘
python kimi_monitor_pro.py --achievements        # 查看成就墙
python kimi_monitor_pro.py --add-task "重构utils" --task-priority 1
python kimi_monitor_pro.py --list-tasks
python kimi_monitor_pro.py --debug               # 调试原始API响应
```

### Pro 版配置亮点

编辑 `~/.kimi-monitor/config.yaml`，Pro 版支持更多配置项：

```yaml
# 额度预测
forecast:
  enabled: true
  history_max_points: 200        # 保留最近 200 个采样点
  window_minutes: 30             # 预测基于最近 30 分钟趋势

# 开发教练
coach:
  enabled: true
  auto_suggest: true

# Git 自动保存
git_autosave:
  enabled: true
  threshold: 0.08                  # 额度 < 8% 时自动 commit
  message_template: "[auto-checkpoint] quota {five_hour_pct:.0f}%5H {weekly_pct:.0f}%WK @ {timestamp}"
  auto_push: false                # 是否同时 push（谨慎开启）

# 语音播报
voice:
  enabled: true
  volume: 80
  phrases:
    quota_available: ["额度已恢复，可以继续开发了！", "开工啦，Kimi额度充足！"]
    quota_exhausted: ["额度耗尽，进入离线模式。", "弹药打光，建议休息或切换本地工作。"]

# Web 仪表盘
web_dashboard:
  enabled: true
  host: "127.0.0.1"
  port: 17421
  refresh_seconds: 5

# 多账号轮询（额度池化）
accounts:
  enabled: false
  rotation_strategy: "max_remaining"  # max_remaining | round_robin | priority
  accounts:
    - id: "account1"
      name: "主账号"
    - id: "account2"
      name: "备用号"

# 额度感知番茄钟
pomodoro:
  enabled: true
  quota_adaptive: true             # 根据额度动态调整时长
  focus_minutes: 25
  break_minutes: 5
```

---

## 🔧 首次使用如遇问题

### 提示"未找到凭证"

**原因**: 脚本找不到 `~/.kimi-code/credentials/kimi-code.json`

**解决**:
```bash
# 方法1: 使用 CLI 登录
kimi-code login

# 方法2: 手动创建凭证文件
mkdir -p ~/.kimi-code/credentials
cat > ~/.kimi-code/credentials/kimi-code.json << 'EOF'
{
  "access_token": "eyJhbG...你的token..."
}
EOF
```

获取 `access_token` 方法：
1. 浏览器打开 https://kimi.com/code/console
2. 按 `F12` → `Application` → `Local Storage` → `https://kimi.com`
3. 复制 `access_token` 的值（以 `eyJhbG` 开头）

### 查询返回数据为空或字段不对

**解决**: 使用 `--debug` 查看原始响应，然后反馈调整解析器：

```bash
# 基础版
python kimi_monitor.py --debug

# Pro 版
python kimi_monitor_pro.py --debug
```

### Windows 没有桌面通知

**解决**: 安装 `win10toast` 获得最佳体验：
```bash
pip install win10toast
```

不安装也能用，脚本会自动回退到 PowerShell 通知。

### Pro 版语音不工作

**解决**: 不同平台需要不同 TTS 后端

```bash
# macOS: 内置 say 命令，无需安装
# Linux: 安装以下任一
sudo apt install speech-dispatcher-espeak  # spd-say
sudo apt install espeak-ng                 # espeak-ng

# Windows: 内置 SAPI，无需安装
# 如果报错，确保 PowerShell 可用
```

### 我想在额度恢复时自动打开 VS Code

**解决**: 修改 `~/.kimi-monitor/config.yaml`：

```yaml
auto_recover:
  mode: "command"
  command: "code ~/my-project && start kimi-code"   # Windows
  # command: "code ~/my-project && open -a KimiCode" # macOS
```

---

## 💡 进阶玩法

### 任务断点续传（基础版 & Pro 版通用）

把大项目拆成小任务，额度耗尽自动保存断点：

```bash
# 添加任务
python kimi_monitor.py --add-task "重构 utils.py" --task-desc "拆分大函数" --task-priority 1
python kimi_monitor.py --add-task "写单元测试" --task-priority 2

# 查看队列
python kimi_monitor.py --list-tasks
```

额度恢复时，通知会告诉你"下一条待办是：重构 utils.py"，直接接着干。

### Pro 版：用预测规划开发节奏

```bash
python kimi_monitor_pro.py --forecast
```

输出示例：
```
📈 额度预测报告
========================================
数据置信度: high (47 个采样点)
5H 预计耗尽: 42 分钟后
周额度预计耗尽: 18.5 小时后
趋势: 5H rising | 周 stable

🔮 恢复预测:
  5h_rolling_release: 约 30~60 分钟后开始释放
  5h_full_recovery: 约 5 小时后完全恢复
========================================

🎯 开发教练建议 [专注模式]
----------------------------------------
当前额度: 5H 38.7% | 周 94.1%
推荐工作: 处理具体功能实现、Bug修复、代码Review
⚠️ 警告: 5H 额度约 42 分钟后耗尽，建议立即收尾
----------------------------------------
```

看到"42 分钟后耗尽"，你就知道：现在不适合开始一个需要 1 小时的大重构，但足够处理 3~4 个 10 分钟的小 Bug。

### Pro 版：挂在副屏的仪表盘

```bash
# 启动守护后，在浏览器打开
http://127.0.0.1:17421

# 同局域网手机/平板也能访问
http://你的电脑IP:17421
```

暗色主题，实时刷新，适合长期挂在显示器角落。

---

## 📜 版本对比

| 功能 | 基础版 | Pro 版 |
|------|--------|--------|
| 双端点额度查询 | ✅ | ✅ |
| 智能等待策略 | ✅ | ✅ |
| 桌面通知 + 响铃 | ✅ | ✅ |
| Webhook 通知 | ✅ | ✅ |
| 任务队列 + 断点续传 | ✅ | ✅ |
| 额度预测引擎 | ❌ | ✅ |
| 智能开发教练 | ❌ | ✅ |
| Git 自动保存 | ❌ | ✅ |
| 语音播报 | ❌ | ✅ |
| Web 仪表盘 | ❌ | ✅ |
| 多账号轮询 | ❌ | ✅ |
| 额度感知番茄钟 | ❌ | ✅ |
| 成就系统 | ❌ | ✅ |
| 代码体积 | 39 KB | 60 KB |
| 外部依赖 | 纯标准库可用 | 纯标准库可用（语音/Webhook 需可选依赖） |

---

## 📜 License

MIT License — 自由使用、修改、分发。

---

> 💡 **提示**: 两个版本均仅查询额度，**不消耗任何模型 Token**。可 7×24 小时安心运行。如有 API 响应字段解析问题，把 `--debug` 的输出发给我，我可以帮你调整适配。

---

**下载更新后的 README**: [README.md](sandbox:///mnt/agents/output/kimi-code-monitor/README.md)
