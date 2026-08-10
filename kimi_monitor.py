#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kimi Code 额度监控与自动恢复系统 (KCAMS) v1.0
===============================================
实时监控 Kimi Code 5H/周额度，额度恢复自动提醒/续跑开发任务。

用法:
    python kimi_monitor.py --init          # 初始化配置
    python kimi_monitor.py --once          # 单次查询额度
    python kimi_monitor.py --daemon        # 后台守护模式
    python kimi_monitor.py --add-task "重构utils.py"  # 添加任务
    python kimi_monitor.py --list-tasks    # 查看任务队列
    python kimi_monitor.py --debug         # 调试：查看原始API响应

作者: AI Assistant
日期: 2026-08-10
"""

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import urllib.request
import urllib.error

# 尝试导入可选依赖
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ==================== 默认配置 ====================

DEFAULT_CONFIG = {
    "check_interval_seconds": 300,      # 正常检查间隔 5 分钟
    "urgent_interval_seconds": 60,      # 额度紧张时检查间隔 1 分钟
    "low_quota_threshold": 0.15,        # 额度低于 15% 视为紧张
    "notification": {
        "enabled": True,
        "sound": True,
        "desktop": True,
        "webhook": {                     # 企业微信/钉钉/飞书等
            "enabled": False,
            "url": "",
            "type": "wecom"              # wecom | dingtalk | lark
        }
    },
    "auto_recover": {
        "enabled": True,                 # 是否启用自动恢复逻辑
        "mode": "notify",                # notify | api | cli | command
        "api_key": "",                   # 用于 api 模式 (sk-...)
        "model": "kimi-k2.5",            # API 模型
        "cli_timeout_seconds": 300,    # CLI 任务超时
        "command": "",                   # command 模式: 额度恢复时执行的系统命令
        "auto_restart_kimi": False     # 是否尝试自动重启 Kimi Code CLI
    },
    "tasks": {
        "save_dir": "~/.kimi-monitor/tasks",
        "auto_save_on_interrupt": True   # 额度用完前自动保存断点
    },
    "logging": {
        "level": "INFO",
        "file": "~/.kimi-monitor/monitor.log"
    }
}


# ==================== 数据模型 ====================

@dataclass
class QuotaStatus:
    """额度状态"""
    five_hour_used: float = 0.0         # 5H 已用比例 (0-1)
    five_hour_total: int = 0            # 5H 总额度 (tokens 或次数)
    five_hour_used_count: int = 0       # 5H 已用量
    weekly_used: float = 0.0            # 周额度已用比例
    weekly_total: int = 0               # 周额度总额度
    weekly_used_count: int = 0          # 周额度已用量
    monthly_used: float = 0.0           # 月度已用比例 (如有)
    reset_time_5h: Optional[str] = None      # 5H 预计完全重置时间
    reset_time_weekly: Optional[str] = None   # 周额度预计完全重置时间
    raw_data: Dict[str, Any] = field(default_factory=dict)  # 原始响应

    @property
    def five_hour_remaining(self) -> float:
        return max(0.0, 1.0 - self.five_hour_used)

    @property
    def weekly_remaining(self) -> float:
        return max(0.0, 1.0 - self.weekly_used)

    def is_5h_exhausted(self, threshold: float = 0.02) -> bool:
        return self.five_hour_remaining <= threshold

    def is_weekly_exhausted(self, threshold: float = 0.02) -> bool:
        return self.weekly_remaining <= threshold

    def is_any_exhausted(self, threshold: float = 0.02) -> bool:
        return self.is_5h_exhausted(threshold) or self.is_weekly_exhausted(threshold)

    def is_low(self, threshold: float = 0.15) -> bool:
        return self.five_hour_remaining < threshold or self.weekly_remaining < threshold


@dataclass
class DevTask:
    """开发任务"""
    id: str
    title: str
    description: str = ""
    status: str = "pending"             # pending | running | paused | completed | failed
    priority: int = 3                 # 1-5, 数字越小优先级越高
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    context_files: List[str] = field(default_factory=list)
    last_prompt: str = ""
    checkpoint: Dict[str, Any] = field(default_factory=dict)


# ==================== 额度查询器 ====================

class QuotaChecker:
    """Kimi Code 额度查询器 - 支持多种查询方式"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.credentials_path = self._get_credentials_path()

    def _get_credentials_path(self) -> Path:
        """获取 Kimi Code CLI 凭证路径"""
        system = platform.system()
        if system == "Windows":
            base = Path(os.environ.get("USERPROFILE", "~"))
        else:
            base = Path.home()
        return (base / ".kimi-code" / "credentials" / "kimi-code.json").expanduser()

    def _load_credentials(self) -> Dict[str, Any]:
        """加载 CLI 凭证"""
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"\n❌ 未找到 Kimi Code CLI 凭证: {self.credentials_path}\n"
                f"请先运行 `kimi-code login` 登录 CLI，或手动配置 access_token。\n"
                f"你也可以通过浏览器登录 kimi.com 后从 LocalStorage 获取 access_token。"
            )

        with open(self.credentials_path, 'r', encoding='utf-8') as f:
            creds = json.load(f)

        # 凭证文件可能是对象或数组
        if isinstance(creds, list) and len(creds) > 0:
            creds = creds[0]
        elif isinstance(creds, dict) and "accounts" in creds:
            creds = creds["accounts"][0]

        return creds

    def _get_access_token(self) -> str:
        """获取有效的 access_token"""
        creds = self._load_credentials()
        token = creds.get("access_token") or creds.get("token")
        if not token:
            raise ValueError("凭证文件中未找到 access_token 字段")
        return token

    def _request(self, url: str, method: str = "GET", 
                 data: Optional[bytes] = None,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """发送 HTTP 请求"""
        token = self._get_access_token()

        default_headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "kimi-monitor/1.0",
            "Accept": "application/json"
        }
        if headers:
            default_headers.update(headers)

        if HAS_REQUESTS:
            if method == "POST":
                resp = requests.post(url, headers=default_headers, data=data, timeout=15)
            else:
                resp = requests.get(url, headers=default_headers, timeout=15)
            resp.raise_for_status()
            return resp.json()
        else:
            req = urllib.request.Request(url, data=data, headers=default_headers, method=method)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))

    def get_quota(self) -> QuotaStatus:
        """查询当前额度状态 - 尝试多种端点"""
        errors = []

        # 方式1: Kimi Code 专用用量接口 (最准确)
        try:
            data = self._request("https://api.kimi.com/coding/v1/usages")
            return self._parse_coding_api(data)
        except Exception as e:
            errors.append(f"coding/v1/usages: {e}")

        # 方式2: 会员统计 Connect RPC 接口
        try:
            data = self._request(
                "https://www.kimi.com/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats",
                method="POST",
                data=b"{}",
                headers={"Content-Type": "application/json"}
            )
            return self._parse_membership_api(data)
        except Exception as e:
            errors.append(f"MembershipService: {e}")

        # 方式3: 开放平台余额接口 (仅反映按量计费余额，非订阅额度)
        api_key = self.config.get("auto_recover", {}).get("api_key", "")
        if api_key and api_key.startswith("sk-"):
            try:
                data = self._request(
                    "https://api.moonshot.cn/v1/users/me/balance",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                return self._parse_openapi_balance(data)
            except Exception as e:
                errors.append(f"openapi balance: {e}")

        raise RuntimeError(f"所有额度查询方式均失败: {'; '.join(errors)}")

    def _parse_coding_api(self, data: Dict[str, Any]) -> QuotaStatus:
        """解析 /coding/v1/usages 响应"""
        raw = data.get("data", data)

        # 灵活字段解析 - 尝试多种可能的字段路径
        def get_val(paths, default=None, cast=float):
            for path in paths:
                val = raw
                try:
                    for part in path.split('.'):
                        if isinstance(val, dict):
                            val = val.get(part)
                        else:
                            break
                    if val is not None:
                        return cast(val)
                except (TypeError, ValueError):
                    continue
            return default

        five_hour_used = get_val([
            "ratelimit_code_5h.used_ratio",
            "ratelimit_5h.used_ratio",
            "code_5h.ratio",
            "five_hour.used_ratio",
            "usage.code_5h_ratio",
            "rate_limits.code_5h"
        ], 0.0)

        weekly_used = get_val([
            "ratelimit_code_7d.used_ratio",
            "ratelimit_7d.used_ratio",
            "code_7d.ratio",
            "weekly.used_ratio",
            "usage.code_7d_ratio",
            "rate_limits.code_7d"
        ], 0.0)

        monthly_used = get_val([
            "subscription_balance.kimi_code_used_ratio",
            "subscription_balance.amount_used_ratio",
            "monthly.used_ratio"
        ], 0.0)

        fh_total = get_val([
            "ratelimit_code_5h.total", "five_hour.total", "code_5h.total"
        ], 0, int)
        fh_used = get_val([
            "ratelimit_code_5h.used", "five_hour.used", "code_5h.used"
        ], 0, int)
        wk_total = get_val([
            "ratelimit_code_7d.total", "weekly.total", "code_7d.total"
        ], 0, int)
        wk_used = get_val([
            "ratelimit_code_7d.used", "weekly.used", "code_7d.used"
        ], 0, int)

        # 估算重置时间 (滚动窗口机制)
        now = datetime.now()
        reset_5h = None
        reset_wk = None

        if five_hour_used >= 0.95:
            # 5小时滚动窗口，最坏情况约1小时后开始释放
            reset_5h = (now + timedelta(hours=1)).strftime("%m-%d %H:%M")
        if weekly_used >= 0.95:
            # 7天滚动窗口，最坏情况约1天后开始释放  
            reset_wk = (now + timedelta(days=1)).strftime("%m-%d %H:%M")

        return QuotaStatus(
            five_hour_used=five_hour_used,
            five_hour_total=fh_total,
            five_hour_used_count=fh_used,
            weekly_used=weekly_used,
            weekly_total=wk_total,
            weekly_used_count=wk_used,
            monthly_used=monthly_used,
            reset_time_5h=reset_5h,
            reset_time_weekly=reset_wk,
            raw_data=raw
        )

    def _parse_membership_api(self, data: Dict[str, Any]) -> QuotaStatus:
        """解析会员统计 Connect RPC 响应"""
        raw = data.get("data", data)
        sub = raw.get("subscription_balance", {})
        limits = raw.get("ratelimit", {})

        code_ratio = sub.get("kimi_code_used_ratio", 0.0)

        # 从 ratelimit 字段提取 5h/7d 数据
        fh = limits.get("code_5h") or limits.get("ratelimit_5h") or {}
        wk = limits.get("code_7d") or limits.get("ratelimit_7d") or {}

        return QuotaStatus(
            five_hour_used=fh.get("used_ratio", 0.0) if isinstance(fh, dict) else 0.0,
            five_hour_total=fh.get("total", 0) if isinstance(fh, dict) else 0,
            five_hour_used_count=fh.get("used", 0) if isinstance(fh, dict) else 0,
            weekly_used=wk.get("used_ratio", 0.0) if isinstance(wk, dict) else 0.0,
            weekly_total=wk.get("total", 0) if isinstance(wk, dict) else 0,
            weekly_used_count=wk.get("used", 0) if isinstance(wk, dict) else 0,
            monthly_used=code_ratio,
            reset_time_5h=None,
            reset_time_weekly=sub.get("expire_time"),
            raw_data=raw
        )

    def _parse_openapi_balance(self, data: Dict[str, Any]) -> QuotaStatus:
        """解析开放平台余额 (仅作参考，非订阅额度)"""
        raw = data.get("data", {})
        avail = raw.get("available_balance", 0)
        # 开放平台余额无法直接映射到 5h/周额度，仅作兜底显示
        return QuotaStatus(
            five_hour_used=0.0,
            five_hour_total=0,
            five_hour_used_count=0,
            weekly_used=0.0,
            weekly_total=0,
            weekly_used_count=0,
            monthly_used=0.0,
            raw_data={"openapi_balance": avail, "note": "此为API按量计费余额，非订阅额度"}
        )


# ==================== 通知系统 ====================

class Notifier:
    """跨平台通知系统"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("notification", {})
        self.system = platform.system()

    def notify(self, title: str, message: str, urgent: bool = False):
        """发送通知"""
        if not self.config.get("enabled", True):
            return

        logging.info(f"[通知] {title}: {message}")

        if self.config.get("desktop", True):
            self._desktop_notify(title, message, urgent)

        if self.config.get("sound", True) and urgent:
            self._play_sound()

        webhook = self.config.get("webhook", {})
        if webhook.get("enabled") and webhook.get("url"):
            self._webhook_notify(title, message, webhook)

    def _desktop_notify(self, title: str, message: str, urgent: bool = False):
        """桌面通知"""
        try:
            if self.system == "Windows":
                self._windows_notify(title, message)
            elif self.system == "Darwin":
                self._macos_notify(title, message)
            else:
                self._linux_notify(title, message)
        except Exception as e:
            logging.debug(f"桌面通知失败: {e}")

    def _windows_notify(self, title: str, message: str):
        """Windows 通知 - 优先使用 win10toast，备选 PowerShell"""
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=10, threaded=True)
        except ImportError:
            try:
                script = f'''
                Add-Type -AssemblyName System.Windows.Forms
                $balloon = New-Object System.Windows.Forms.NotifyIcon
                $balloon.Icon = [System.Drawing.SystemIcons]::Information
                $balloon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
                $balloon.BalloonTipText = "{message.replace('"', '`"')}"
                $balloon.BalloonTipTitle = "{title.replace('"', '`"')}"
                $balloon.Visible = $true
                $balloon.ShowBalloonTip(8000)
                Start-Sleep -Milliseconds 8500
                $balloon.Dispose()
                '''
                subprocess.run(["powershell", "-Command", script], 
                           capture_output=True, timeout=15)
            except Exception as e2:
                logging.debug(f"PowerShell 通知失败: {e2}")

    def _macos_notify(self, title: str, message: str):
        """macOS 通知"""
        script = f'display notification "{message.replace('"', '\\"')}" with title "{title.replace('"', '\\"')}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], capture_output=True)

    def _linux_notify(self, title: str, message: str):
        """Linux 通知"""
        for cmd in [["notify-send", title, message], 
                    ["zenity", "--info", f"--title={title}", f"--text={message}"]]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=5)
                return
            except Exception:
                continue

    def _play_sound(self):
        """播放提示音"""
        try:
            if self.system == "Windows":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            elif self.system == "Darwin":
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], 
                           capture_output=True, timeout=5)
            else:
                subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"], 
                           capture_output=True, timeout=5)
        except Exception:
            print("\a", end="", flush=True)  # 终端响铃

    def _webhook_notify(self, title: str, message: str, webhook: Dict[str, str]):
        """Webhook 通知（企业微信/钉钉/飞书）"""
        url = webhook.get("url", "")
        wtype = webhook.get("type", "wecom")

        try:
            if wtype == "wecom":
                payload = {"msgtype": "text", "text": {"content": f"{title}\n{message}"}}
            elif wtype == "dingtalk":
                payload = {"msgtype": "text", "text": {"content": f"{title}\n{message}"}}
            elif wtype == "lark":
                payload = {"msg_type": "text", "content": {"text": f"{title}\n{message}"}}
            else:
                payload = {"title": title, "message": message}

            headers = {"Content-Type": "application/json"}
            data = json.dumps(payload).encode('utf-8')

            if HAS_REQUESTS:
                requests.post(url, data=data, headers=headers, timeout=10)
            else:
                req = urllib.request.Request(url, data=data, headers=headers)
                urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logging.warning(f"Webhook 通知失败: {e}")


# ==================== 任务管理器 ====================

class TaskManager:
    """开发任务队列管理 - 支持断点续传"""

    def __init__(self, config: Dict[str, Any]):
        self.save_dir = Path(config.get("tasks", {}).get("save_dir", "~/.kimi-monitor/tasks")).expanduser()
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_file = self.save_dir / "queue.json"
        self.tasks: List[DevTask] = []
        self._load()

    def _load(self):
        if self.tasks_file.exists():
            try:
                with open(self.tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.tasks = [DevTask(**t) for t in data]
            except Exception as e:
                logging.error(f"加载任务队列失败: {e}")
                self.tasks = []

    def _save(self):
        try:
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                json.dump([asdict(t) for t in self.tasks], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存任务队列失败: {e}")

    def add_task(self, title: str, description: str = "", priority: int = 3,
                 context_files: Optional[List[str]] = None, prompt: str = "") -> DevTask:
        """添加新任务"""
        task = DevTask(
            id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.tasks)}",
            title=title,
            description=description,
            status="pending",
            priority=priority,
            created_at=datetime.now().isoformat(),
            context_files=context_files or [],
            last_prompt=prompt
        )
        self.tasks.append(task)
        self._save()
        return task

    def get_next_pending(self) -> Optional[DevTask]:
        """获取下一个待执行的高优先级任务"""
        pending = [t for t in self.tasks if t.status in ("pending", "paused")]
        if not pending:
            return None
        pending.sort(key=lambda t: (t.priority, t.created_at))
        return pending[0]

    def update_status(self, task_id: str, status: str, checkpoint: Optional[Dict[str, Any]] = None):
        """更新任务状态"""
        for t in self.tasks:
            if t.id == task_id:
                t.status = status
                if status == "running":
                    t.started_at = datetime.now().isoformat()
                elif status in ("completed", "failed"):
                    t.completed_at = datetime.now().isoformat()
                if checkpoint:
                    t.checkpoint = checkpoint
                self._save()
                return True
        return False

    def list_tasks(self) -> List[DevTask]:
        return sorted(self.tasks, key=lambda t: t.created_at, reverse=True)

    def save_checkpoint(self, task_id: str, context: Dict[str, Any]):
        """保存断点"""
        self.update_status(task_id, "paused", context)
        logging.info(f"任务 {task_id} 断点已保存。")


# ==================== 自动恢复器 ====================

class AutoRecover:
    """额度恢复后的自动恢复逻辑"""

    def __init__(self, config: Dict[str, Any], checker: QuotaChecker,
                 notifier: Notifier, task_manager: TaskManager):
        self.config = config.get("auto_recover", {})
        self.checker = checker
        self.notifier = notifier
        self.task_manager = task_manager
        self.mode = self.config.get("mode", "notify")

    def on_quota_available(self, quota: QuotaStatus):
        """额度可用时的回调"""
        title = "🟢 Kimi Code 额度已恢复"
        msg = (
            f"5H 额度: {quota.five_hour_remaining*100:.1f}% 可用\n"
            f"周额度: {quota.weekly_remaining*100:.1f}% 可用\n"
            f"可以继续开发了！"
        )
        self.notifier.notify(title, msg, urgent=True)

        # 执行用户配置的恢复命令
        command = self.config.get("command", "")
        if command:
            self._run_command(command)

        if self.mode == "api":
            self._try_api_recover()
        elif self.mode == "cli":
            self._try_cli_recover()
        else:
            self._show_next_task()

    def on_quota_exhausted(self, quota: QuotaStatus):
        """额度耗尽时的回调"""
        # 自动保存断点
        if self.config.get("auto_save_on_interrupt", True):
            task = self.task_manager.get_next_pending()
            if task:
                self.task_manager.save_checkpoint(task.id, {
                    "saved_at": datetime.now().isoformat(),
                    "reason": "quota_exhausted",
                    "quota_snapshot": {
                        "five_hour_used": quota.five_hour_used,
                        "weekly_used": quota.weekly_used
                    }
                })

        # 计算预计恢复时间
        estimates = []
        if quota.is_5h_exhausted():
            estimates.append("5H 额度约 1 小时内滚动释放")
        if quota.is_weekly_exhausted():
            estimates.append("周额度约 1 天内滚动释放")

        msg = "额度已用完，开发任务已暂停，进入智能等待。\n"
        if estimates:
            msg += "预计恢复: " + "；".join(estimates)
        msg += "\n监控脚本将继续轮询，恢复后第一时间通知你。"

        self.notifier.notify("🔴 Kimi Code 额度耗尽", msg, urgent=True)

    def _show_next_task(self):
        task = self.task_manager.get_next_pending()
        if task:
            self.notifier.notify(
                "📋 待续跑任务",
                f"下一条: {task.title}\n"
                f"描述: {task.description[:80]}...\n"
                f"请打开 Kimi Code CLI 继续开发！"
            )

    def _run_command(self, command: str):
        """执行用户配置的恢复命令"""
        try:
            logging.info(f"执行恢复命令: {command}")
            subprocess.Popen(command, shell=True, 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logging.error(f"恢复命令执行失败: {e}")

    def _try_api_recover(self):
        """尝试通过 Moonshot API 自动恢复"""
        api_key = self.config.get("api_key", "")
        if not api_key or not api_key.startswith("sk-"):
            logging.warning("API 模式未配置有效的 API Key")
            return

        task = self.task_manager.get_next_pending()
        if not task:
            return

        logging.info(f"尝试通过 API 自动执行任务: {task.title}")
        self.notifier.notify("🤖 自动恢复", f"正在通过 API 执行任务: {task.title}")

        # 这里可以实现通过 Moonshot API 调用
        # 实际调用需要用户根据需求自行扩展
        # 示例框架:
        # headers = {"Authorization": f"Bearer {api_key}"}
        # payload = {"model": self.config.get("model"), "messages": [...]}

    def _try_cli_recover(self):
        """尝试通过 CLI 自动恢复"""
        task = self.task_manager.get_next_pending()
        if not task:
            return

        if self.config.get("auto_restart_kimi"):
            try:
                # 尝试在新的终端窗口启动 kimi-code
                # 实际命令因平台而异
                cmd = "kimi-code"
                if platform.system() == "Windows":
                    subprocess.Popen(["start", "cmd", "/k", cmd], shell=True)
                else:
                    subprocess.Popen(["osascript", "-e", 
                                    f'tell app "Terminal" to do script "{cmd}"'] 
                                   if platform.system() == "Darwin" else
                                   ["gnome-terminal", "--", cmd])
                self.notifier.notify("💻 CLI 已启动", "Kimi Code CLI 已自动打开，请继续开发！")
            except Exception as e:
                logging.error(f"自动启动 CLI 失败: {e}")
        else:
            self._show_next_task()


# ==================== 主控循环 ====================

class MonitorDaemon:
    """监控守护进程"""

    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self._setup_logging()

        self.checker = QuotaChecker(self.config)
        self.notifier = Notifier(self.config)
        self.task_manager = TaskManager(self.config)
        self.recover = AutoRecover(self.config, self.checker, self.notifier, self.task_manager)

        self.last_status: Optional[QuotaStatus] = None
        self.was_available: bool = True
        self.consecutive_errors: int = 0

    def _load_config(self, path: Optional[str]) -> Dict[str, Any]:
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                if HAS_YAML and path.endswith(('.yaml', '.yml')):
                    return {**DEFAULT_CONFIG, **yaml.safe_load(f)}
                else:
                    return {**DEFAULT_CONFIG, **json.load(f)}

        for p in [Path.home() / ".kimi-monitor" / "config.yaml",
                  Path.home() / ".kimi-monitor" / "config.json"]:
            if p.exists():
                with open(p, 'r', encoding='utf-8') as f:
                    if HAS_YAML and p.suffix in ('.yaml', '.yml'):
                        return {**DEFAULT_CONFIG, **yaml.safe_load(f)}
                    else:
                        return {**DEFAULT_CONFIG, **json.load(f)}

        return DEFAULT_CONFIG.copy()

    def _setup_logging(self):
        log_config = self.config.get("logging", {})
        level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
        log_file = Path(log_config.get("file", "~/.kimi-monitor/monitor.log")).expanduser()
        log_file.parent.mkdir(parents=True, exist_ok=True)

        handlers = [logging.StreamHandler(sys.stdout)]
        try:
            handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
        except Exception as e:
            print(f"警告: 无法创建日志文件: {e}")

        logging.basicConfig(
            level=level,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=handlers
        )

    def run_once(self):
        """单次检查"""
        logging.info("正在查询 Kimi Code 额度...")
        try:
            quota = self.checker.get_quota()
            self.consecutive_errors = 0
            self._process_status(quota)
            self._print_status(quota)
            return quota
        except Exception as e:
            self.consecutive_errors += 1
            logging.error(f"查询失败 ({self.consecutive_errors}次连续错误): {e}")
            if self.consecutive_errors >= 3:
                self.notifier.notify("⚠️ 额度查询异常", 
                    f"连续 {self.consecutive_errors} 次查询失败: {str(e)[:100]}", 
                    urgent=False)
            raise

    def run_daemon(self):
        """守护模式主循环"""
        logging.info("=" * 60)
        logging.info("Kimi Code 额度监控守护进程已启动")
        logging.info("按 Ctrl+C 停止")
        logging.info("=" * 60)

        self.notifier.notify("🚀 监控已启动", 
            "Kimi Code 额度监控正在后台运行\n"
            "额度恢复时将自动通知你", 
            urgent=False)

        while True:
            try:
                quota = self.run_once()

                # 根据额度状态调整检查间隔
                if quota.is_any_exhausted():
                    interval = self._smart_wait_interval(quota)
                elif quota.is_low(self.config.get("low_quota_threshold", 0.15)):
                    interval = self.config.get("urgent_interval_seconds", 60)
                else:
                    interval = self.config.get("check_interval_seconds", 300)

                logging.info(f"下次检查: {interval} 秒后 ({datetime.now() + timedelta(seconds=interval):%H:%M:%S})")
                time.sleep(interval)

            except KeyboardInterrupt:
                print("\n👋 监控已停止")
                self.notifier.notify("⏹️ 监控已停止", "Kimi Code 额度监控已退出", urgent=False)
                break
            except Exception as e:
                logging.error(f"监控循环异常: {e}")
                time.sleep(self.config.get("check_interval_seconds", 300))

    def _process_status(self, quota: QuotaStatus):
        """处理额度状态变化"""
        is_available = not quota.is_any_exhausted()

        # 从耗尽恢复到可用
        if not self.was_available and is_available:
            logging.info("✅ 额度已从耗尽状态恢复！")
            self.recover.on_quota_available(quota)

        # 从可用变为耗尽
        elif self.was_available and not is_available:
            logging.warning("🚫 额度已耗尽！")
            self.recover.on_quota_exhausted(quota)

        # 持续低额度警告
        elif quota.is_low(self.config.get("low_quota_threshold", 0.15)):
            if self.last_status and quota.five_hour_used > self.last_status.five_hour_used:
                logging.warning(f"⚠️ 5H 额度紧张: 已用 {quota.five_hour_used*100:.1f}%，剩余 {quota.five_hour_remaining*100:.1f}%")

        self.was_available = is_available
        self.last_status = quota

    def _smart_wait_interval(self, quota: QuotaStatus) -> int:
        """根据额度类型计算智能等待间隔"""
        if quota.is_5h_exhausted() and not quota.is_weekly_exhausted():
            # 5H 耗尽但周额度还有：滚动窗口约 1 小时释放一部分
            # 前 15 分钟密集检查（可能早期释放），之后放宽
            if self.last_status and self.last_status.is_5h_exhausted():
                # 已经等了一段时间，放宽检查
                return 600  # 10 分钟
            return 300    # 5 分钟（初始密集检查）
        elif quota.is_weekly_exhausted():
            # 周额度耗尽：滚动窗口约 1 天释放
            logging.info("周额度耗尽，进入长等待模式（约 1 天滚动释放）...")
            return 3600   # 1 小时检查一次

        return self.config.get("check_interval_seconds", 300)

    def _print_status(self, quota: QuotaStatus):
        """打印额度状态到控制台"""
        now = datetime.now()
        print("\n" + "=" * 56)
        print(f"📊 Kimi Code 额度状态  {now.strftime('%m-%d %H:%M:%S')}")
        print("-" * 56)

        fh_rem = quota.five_hour_remaining * 100
        wk_rem = quota.weekly_remaining * 100
        mo_rem = (1 - quota.monthly_used) * 100 if quota.monthly_used else 100

        # 5H 额度
        fh_icon = "🟢" if fh_rem > 30 else ("🟡" if fh_rem > 10 else "🔴")
        print(f"{fh_icon} 5H 窗口: {fh_rem:5.1f}% 可用  (已用 {quota.five_hour_used*100:.1f}%)")
        if quota.five_hour_total > 0:
            print(f"   计数: {quota.five_hour_used_count:,} / {quota.five_hour_total:,}")
        if quota.reset_time_5h:
            print(f"   滚动释放: ~{quota.reset_time_5h}")

        # 周额度
        wk_icon = "🟢" if wk_rem > 30 else ("🟡" if wk_rem > 10 else "🔴")
        print(f"{wk_icon} 7天窗口: {wk_rem:5.1f}% 可用  (已用 {quota.weekly_used*100:.1f}%)")
        if quota.weekly_total > 0:
            print(f"   计数: {quota.weekly_used_count:,} / {quota.weekly_total:,}")
        if quota.reset_time_weekly:
            print(f"   滚动释放: ~{quota.reset_time_weekly}")

        # 月度额度
        if quota.monthly_used > 0:
            print(f"📅 月度额度: {mo_rem:5.1f}% 可用")

        # 状态提示
        if quota.is_any_exhausted():
            print("-" * 56)
            print("⏸️  当前额度耗尽，监控脚本正在智能等待...")
            print("     额度恢复后将自动通知你继续开发")
        elif quota.is_low():
            print("-" * 56)
            print("⚠️  额度紧张，建议控制使用节奏")

        print("=" * 56)


# ==================== CLI 入口 ====================

def init_config():
    """初始化配置文件"""
    config_dir = Path.home() / ".kimi-monitor"
    config_dir.mkdir(exist_ok=True)

    config_file = config_dir / "config.yaml"
    if not config_file.exists():
        with open(config_file, 'w', encoding='utf-8') as f:
            if HAS_YAML:
                yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True, sort_keys=False)
            else:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"✅ 配置文件已创建: {config_file}")
        print("   请根据需要编辑配置（如添加 Webhook、API Key、恢复命令等）")
    else:
        print(f"配置文件已存在: {config_file}")

    # 同时创建任务目录
    tasks_dir = config_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)

    return config_file


def main():
    parser = argparse.ArgumentParser(
        description="Kimi Code 额度监控与自动恢复系统 v1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s --init                    # 初始化配置文件
  %(prog)s --once                    # 单次查询额度状态
  %(prog)s --daemon                  # 后台守护模式（推荐）
  %(prog)s --add-task "重构utils.py" --task-desc "拆分大函数"  # 添加任务
  %(prog)s --list-tasks              # 查看任务队列
  %(prog)s --debug                   # 调试：查看原始API响应结构
        """
    )
    parser.add_argument("--init", action="store_true", help="初始化配置文件和目录")
    parser.add_argument("--once", action="store_true", help="单次查询额度状态")
    parser.add_argument("--daemon", action="store_true", help="启动守护模式（持续监控）")
    parser.add_argument("--config", "-c", help="指定配置文件路径")
    parser.add_argument("--add-task", metavar="TITLE", help="添加开发任务到队列")
    parser.add_argument("--task-desc", default="", help="任务描述")
    parser.add_argument("--task-priority", type=int, default=3, choices=range(1,6),
                       help="任务优先级 1=最高, 5=最低 (默认: 3)")
    parser.add_argument("--list-tasks", action="store_true", help="列出所有任务")
    parser.add_argument("--debug", action="store_true", help="调试模式：显示原始 API 响应")

    args = parser.parse_args()

    if args.init:
        init_config()
        print("\n提示: 首次使用前请确保已运行 `kimi-code login` 登录 CLI")
        return

    if args.add_task:
        tm = TaskManager(DEFAULT_CONFIG)
        task = tm.add_task(
            title=args.add_task,
            description=args.task_desc,
            priority=args.task_priority
        )
        print(f"✅ 任务已添加")
        print(f"   ID:   {task.id}")
        print(f"   标题: {task.title}")
        print(f"   状态: {task.status}")
        print(f"   优先级: {task.priority}")
        return

    if args.list_tasks:
        tm = TaskManager(DEFAULT_CONFIG)
        tasks = tm.list_tasks()
        if not tasks:
            print("暂无开发任务")
            return

        print(f"\n{'ID':<25} {'状态':<8} {'优先级':<6} {'标题':<30}")
        print("-" * 75)
        for t in tasks[:30]:
            prio_str = "█" * (6 - t.priority) + "░" * (t.priority - 1)
            print(f"{t.id:<25} {t.status:<8} {prio_str:<6} {t.title:<30}")
        if len(tasks) > 30:
            print(f"... 还有 {len(tasks)-30} 条任务")
        return

    # 创建监控实例
    daemon = MonitorDaemon(config_path=args.config)

    if args.debug:
        print("🔍 调试模式：正在获取原始额度数据...")
        try:
            quota = daemon.checker.get_quota()
            print("\n✅ 查询成功！原始响应数据:")
            print(json.dumps(quota.raw_data, ensure_ascii=False, indent=2))
            print("\n📊 解析后的额度状态:")
            daemon._print_status(quota)
        except Exception as e:
            print(f"\n❌ 获取失败: {e}")
            import traceback
            traceback.print_exc()
        return

    if args.once:
        daemon.run_once()
    elif args.daemon:
        daemon.run_daemon()
    else:
        # 默认单次查询
        daemon.run_once()
        print("\n提示: 使用 --daemon 启动后台持续监控")


if __name__ == "__main__":
    main()
