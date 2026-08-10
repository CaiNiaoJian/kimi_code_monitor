#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kimi Code 额度监控 Pro v2.0 (KCAMS-Pro)
========================================
高级额度监控与智能开发辅助系统

核心升级:
  1. 额度预测引擎    - 基于历史数据预测耗尽/恢复时间,精准规划开发节奏
  2. 智能开发教练    - 根据实时额度推荐最优工作模式(深度/专注/轻量/离线)
  3. Git 自动保存    - 额度耗尽前自动 commit checkpoint,零丢失风险
  4. 语音播报系统    - TTS 语音提醒 + 自定义音效,告别错过通知
  5. Web 仪表盘      - 本地实时可视化面板,额度曲线、任务状态一目了然
  6. 多账号轮询      - 支持多 Kimi 账号自动切换,额度池化管理
  7. 额度感知番茄钟  - 根据剩余额度动态调整专注/休息时长
  8. 成就系统        - 游戏化额度管理,解锁"节流专家""深夜战神"等称号

用法:
  python kimi_monitor_pro.py --init
  python kimi_monitor_pro.py --daemon              # 启动完整守护(含Web仪表盘)
  python kimi_monitor_pro.py --daemon --no-web     # 纯后台模式
  python kimi_monitor_pro.py --coach               # 仅查看当前开发建议
  python kimi_monitor_pro.py --forecast            # 查看额度预测报告
  python kimi_monitor_pro.py --dashboard-only      # 仅启动Web仪表盘
  python kimi_monitor_pro.py --add-task "重构utils" --priority 1
  python kimi_monitor_pro.py --achievements        # 查看成就墙

作者: AI Assistant | 版本: 2.0.0 | 日期: 2026-08-10
"""

import argparse
import base64
import hashlib
import json
import logging
import math
import os
import platform
import random
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from collections import deque
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Callable

# 可选依赖
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
    "version": "2.0.0",
    "check_interval_seconds": 300,
    "urgent_interval_seconds": 60,
    "critical_interval_seconds": 30,
    "low_quota_threshold": 0.15,
    "critical_quota_threshold": 0.05,

    "forecast": {
        "enabled": True,
        "history_max_points": 200,
        "window_minutes": 30,
        "show_eta": True
    },

    "coach": {
        "enabled": True,
        "auto_suggest": True,
        "modes": {
            "deep":    {"min_quota": 0.50, "desc": "深度模式", "suggest": "处理复杂架构设计、大规模重构、算法优化"},
            "focus":   {"min_quota": 0.15, "desc": "专注模式", "suggest": "处理具体功能实现、Bug修复、代码Review"},
            "light":   {"min_quota": 0.05, "desc": "轻量模式", "suggest": "简单修改、写注释、更新文档、单测补充"},
            "offline": {"min_quota": 0.00, "desc": "离线模式", "suggest": "阅读源码、本地测试、学习新技术、整理思路"}
        }
    },

    "git_autosave": {
        "enabled": True,
        "threshold": 0.08,
        "message_template": "[auto-checkpoint] quota {five_hour_pct:.0f}%5H {weekly_pct:.0f}%WK @ {timestamp}",
        "auto_push": False,
        "branches": ["main", "master", "dev"]
    },

    "voice": {
        "enabled": True,
        "volume": 80,
        "rate": 180,
        "voice_id": None,
        "custom_sound_path": "",
        "phrases": {
            "quota_available": ["额度已恢复，可以继续开发了！", "开工啦，Kimi额度充足！", "弹药已补充，请指示目标！"],
            "quota_exhausted": ["额度耗尽，进入离线模式。", "弹药打光，建议休息或切换本地工作。", "额度见底，已自动保存断点。"],
            "quota_low": ["额度紧张，建议切换轻量模式。", "剩余额度不足两成，注意节奏。"],
            "checkpoint_saved": ["断点已保存，放心休息。", "工作已存档，额度耗尽也不怕。"]
        }
    },

    "web_dashboard": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 17421,
        "refresh_seconds": 5,
        "theme": "dark"
    },

    "accounts": {
        "enabled": False,
        "rotation_strategy": "max_remaining",  # max_remaining | round_robin | priority
        "accounts": []
    },

    "pomodoro": {
        "enabled": True,
        "quota_adaptive": True,
        "focus_minutes": 25,
        "break_minutes": 5,
        "long_break_minutes": 15,
        "cycles_before_long_break": 4
    },

    "achievements": {
        "enabled": True,
        "sound_on_unlock": True
    },

    "notification": {
        "enabled": True,
        "sound": True,
        "desktop": True,
        "webhook": {"enabled": False, "url": "", "type": "wecom"}
    },

    "auto_recover": {
        "enabled": True,
        "mode": "notify",
        "command": "",
        "auto_restart_kimi": False
    },

    "tasks": {
        "save_dir": "~/.kimi-monitor/tasks",
        "auto_save_on_interrupt": True
    },

    "logging": {
        "level": "INFO",
        "file": "~/.kimi-monitor/monitor.log"
    }
}


# ==================== 数据模型 ====================

@dataclass
class QuotaStatus:
    five_hour_used: float = 0.0
    five_hour_total: int = 0
    five_hour_used_count: int = 0
    weekly_used: float = 0.0
    weekly_total: int = 0
    weekly_used_count: int = 0
    monthly_used: float = 0.0
    reset_time_5h: Optional[str] = None
    reset_time_weekly: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    account_id: str = "default"
    queried_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def five_hour_remaining(self) -> float: return max(0.0, 1.0 - self.five_hour_used)
    @property
    def weekly_remaining(self) -> float: return max(0.0, 1.0 - self.weekly_used)
    def is_5h_exhausted(self, t=0.02): return self.five_hour_remaining <= t
    def is_weekly_exhausted(self, t=0.02): return self.weekly_remaining <= t
    def is_any_exhausted(self, t=0.02): return self.is_5h_exhausted(t) or self.is_weekly_exhausted(t)
    def is_low(self, t=0.15): return self.five_hour_remaining < t or self.weekly_remaining < t
    def is_critical(self, t=0.05): return self.five_hour_remaining < t or self.weekly_remaining < t


@dataclass
class DevTask:
    id: str = ""
    title: str = ""
    description: str = ""
    status: str = "pending"
    priority: int = 3
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    context_files: List[str] = field(default_factory=list)
    last_prompt: str = ""
    checkpoint: Dict[str, Any] = field(default_factory=dict)
    estimated_tokens: int = 0
    tags: List[str] = field(default_factory=list)


@dataclass
class HistoryPoint:
    timestamp: float
    five_hour_used: float
    weekly_used: float
    five_hour_remaining: float
    weekly_remaining: float


# ==================== 额度查询器 (多账号支持) ====================

class QuotaChecker:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.accounts = config.get("accounts", {}).get("accounts", [])
        self.rotation = config.get("accounts", {}).get("rotation_strategy", "max_remaining")
        self.multi = config.get("accounts", {}).get("enabled", False) and len(self.accounts) > 0

    def _get_creds_path(self, account_id: str = "default") -> Path:
        system = platform.system()
        base = Path(os.environ.get("USERPROFILE", "~")) if system == "Windows" else Path.home()
        if account_id == "default":
            return (base / ".kimi-code" / "credentials" / "kimi-code.json").expanduser()
        return (base / f".kimi-code" / "credentials" / f"kimi-code-{account_id}.json").expanduser()

    def _load_token(self, account_id: str = "default") -> str:
        path = self._get_creds_path(account_id)
        if not path.exists():
            if account_id == "default":
                raise FileNotFoundError(f"未找到凭证: {path}\n请先运行 `kimi-code login`")
            raise FileNotFoundError(f"未找到账号 {account_id} 的凭证: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            creds = json.load(f)
        if isinstance(creds, list) and len(creds) > 0: creds = creds[0]
        elif isinstance(creds, dict) and "accounts" in creds: creds = creds["accounts"][0]
        token = creds.get("access_token") or creds.get("token")
        if not token: raise ValueError(f"账号 {account_id} 凭证中无 access_token")
        return token

    def _request(self, url: str, token: str, method: str = "GET", data: Optional[bytes] = None) -> Dict:
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "kimi-monitor-pro/2.0", "Accept": "application/json"}
        if data: headers["Content-Type"] = "application/json"
        if HAS_REQUESTS:
            fn = requests.post if method == "POST" else requests.get
            resp = fn(url, headers=headers, data=data, timeout=15)
            resp.raise_for_status()
            return resp.json()
        else:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))

    def _query_account(self, account_id: str = "default") -> QuotaStatus:
        token = self._load_token(account_id)
        errors = []
        for url, method, data, parser in [
            ("https://api.kimi.com/coding/v1/usages", "GET", None, self._parse_coding),
            ("https://www.kimi.com/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats", "POST", b"{}", self._parse_membership)
        ]:
            try:
                raw = self._request(url, token, method, data)
                q = parser(raw)
                q.account_id = account_id
                return q
            except Exception as e:
                errors.append(str(e)[:60])
        raise RuntimeError(f"账号 {account_id} 查询失败: {'; '.join(errors)}")

    def _parse_coding(self, data: Dict) -> QuotaStatus:
        raw = data.get("data", data)
        def get(paths, default=0.0, cast=float):
            for p in paths:
                v = raw
                try:
                    for part in p.split('.'):
                        v = v.get(part) if isinstance(v, dict) else None
                    if v is not None: return cast(v)
                except: continue
            return default
        now = datetime.now()
        fh_u = get(["ratelimit_code_5h.used_ratio","ratelimit_5h.used_ratio","code_5h.ratio","five_hour.used_ratio"], 0.0)
        wk_u = get(["ratelimit_code_7d.used_ratio","ratelimit_7d.used_ratio","code_7d.ratio","weekly.used_ratio"], 0.0)
        mo_u = get(["subscription_balance.kimi_code_used_ratio","monthly.used_ratio"], 0.0)
        fh_t = get(["ratelimit_code_5h.total","five_hour.total"], 0, int)
        fh_c = get(["ratelimit_code_5h.used","five_hour.used"], 0, int)
        wk_t = get(["ratelimit_code_7d.total","weekly.total"], 0, int)
        wk_c = get(["ratelimit_code_7d.used","weekly.used"], 0, int)
        r5 = (now + timedelta(hours=1)).strftime("%m-%d %H:%M") if fh_u >= 0.95 else None
        rw = (now + timedelta(days=1)).strftime("%m-%d %H:%M") if wk_u >= 0.95 else None
        return QuotaStatus(fh_u, fh_t, fh_c, wk_u, wk_t, wk_c, mo_u, r5, rw, raw)

    def _parse_membership(self, data: Dict) -> QuotaStatus:
        raw = data.get("data", data)
        sub = raw.get("subscription_balance", {})
        limits = raw.get("ratelimit", {})
        code_ratio = sub.get("kimi_code_used_ratio", 0.0)
        fh = limits.get("code_5h") or limits.get("ratelimit_5h") or {}
        wk = limits.get("code_7d") or limits.get("ratelimit_7d") or {}
        return QuotaStatus(
            fh.get("used_ratio",0.0) if isinstance(fh,dict) else 0.0,
            fh.get("total",0) if isinstance(fh,dict) else 0,
            fh.get("used",0) if isinstance(fh,dict) else 0,
            wk.get("used_ratio",0.0) if isinstance(wk,dict) else 0.0,
            wk.get("total",0) if isinstance(wk,dict) else 0,
            wk.get("used",0) if isinstance(wk,dict) else 0,
            code_ratio, None, sub.get("expire_time"), raw
        )

    def get_quota(self) -> QuotaStatus:
        if not self.multi:
            return self._query_account("default")
        results = []
        for acc in self.accounts:
            try:
                results.append(self._query_account(acc.get("id", "default")))
            except Exception as e:
                logging.warning(f"账号 {acc.get('id')} 查询失败: {e}")
        if not results:
            raise RuntimeError("所有账号查询失败")
        if self.rotation == "max_remaining":
            best = max(results, key=lambda q: min(q.five_hour_remaining, q.weekly_remaining))
            best.raw_data["_all_accounts"] = [{"id": r.account_id, "5h_rem": r.five_hour_remaining, "wk_rem": r.weekly_remaining} for r in results]
            return best
        return results[0]


# ==================== 额度预测引擎 ====================

class QuotaForecaster:
    def __init__(self, config: Dict[str, Any]):
        self.max_points = config.get("forecast", {}).get("history_max_points", 200)
        self.window_sec = config.get("forecast", {}).get("window_minutes", 30) * 60
        self.history: deque = deque(maxlen=self.max_points)
        self.history_file = Path.home() / ".kimi-monitor" / "history.json"
        self._load()

    def _load(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    for p in data[-self.max_points:]:
                        self.history.append(HistoryPoint(**p))
            except: pass

    def _save(self):
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, 'w') as f:
                json.dump([{"timestamp": h.timestamp, "five_hour_used": h.five_hour_used,
                          "weekly_used": h.weekly_used, "five_hour_remaining": h.five_hour_remaining,
                          "weekly_remaining": h.weekly_remaining} for h in self.history], f)
        except Exception as e: logging.debug(f"历史保存失败: {e}")

    def record(self, quota: QuotaStatus):
        now = time.time()
        self.history.append(HistoryPoint(now, quota.five_hour_used, quota.weekly_used,
                                         quota.five_hour_remaining, quota.weekly_remaining))
        self._save()

    def predict_exhaustion(self) -> Dict[str, Any]:
        if len(self.history) < 3:
            return {"confidence": "low", "eta_5h_minutes": None, "eta_weekly_hours": None,
                    "trend_5h": "unknown", "trend_weekly": "unknown"}

        recent = [h for h in self.history if time.time() - h.timestamp <= self.window_sec]
        if len(recent) < 2:
            recent = list(self.history)[-10:]

        # 线性回归估算斜率
        def slope(values: List[float]) -> float:
            n = len(values)
            if n < 2: return 0.0
            x = list(range(n))
            mx, my = sum(x)/n, sum(values)/n
            num = sum((x[i]-mx)*(values[i]-my) for i in range(n))
            den = sum((x[i]-mx)**2 for i in range(n))
            return num/den if den != 0 else 0.0

        fh_vals = [h.five_hour_used for h in recent]
        wk_vals = [h.weekly_used for h in recent]
        fh_slope = slope(fh_vals)
        wk_slope = slope(wk_vals)

        last = recent[-1]
        eta_5h = None
        eta_wk = None

        if fh_slope > 0.001:
            remain = 1.0 - last.five_hour_used
            steps = remain / fh_slope
            eta_5h = max(0, steps * (recent[-1].timestamp - recent[0].timestamp) / max(1, len(recent)-1) / 60)
        if wk_slope > 0.0001:
            remain = 1.0 - last.weekly_used
            steps = remain / wk_slope
            eta_wk = max(0, steps * (recent[-1].timestamp - recent[0].timestamp) / max(1, len(recent)-1) / 3600)

        def trend(s):
            if s > 0.01: return "rising"
            if s < -0.01: return "falling"
            return "stable"

        conf = "high" if len(recent) >= 10 else ("medium" if len(recent) >= 5 else "low")
        return {
            "confidence": conf,
            "eta_5h_minutes": round(eta_5h, 1) if eta_5h else None,
            "eta_weekly_hours": round(eta_wk, 2) if eta_wk else None,
            "trend_5h": trend(fh_slope * 100),
            "trend_weekly": trend(wk_slope * 100),
            "consumption_rate_5h_per_hour": round(fh_slope * 100 * 3600 / max(1, recent[-1].timestamp - recent[0].timestamp), 2) if len(recent)>1 else 0,
            "data_points": len(recent)
        }

    def predict_recovery(self, quota: QuotaStatus) -> Dict[str, Any]:
        """预测额度恢复时间 (滚动窗口机制)"""
        predictions = {}
        if quota.is_5h_exhausted():
            # 5H 滚动窗口: 最早那 1h 的用量会在约 1h 后开始释放
            predictions["5h_rolling_release"] = "约 30~60 分钟后开始释放"
            predictions["5h_full_recovery"] = "约 5 小时后完全恢复"
        if quota.is_weekly_exhausted():
            predictions["weekly_rolling_release"] = "约 12~24 小时后开始释放"
            predictions["weekly_full_recovery"] = "约 7 天后完全恢复"
        return predictions

    def get_report(self, quota: QuotaStatus) -> str:
        self.record(quota)
        pred = self.predict_exhaustion()
        rec = self.predict_recovery(quota)
        lines = ["\n📈 额度预测报告", "=" * 40]
        lines.append(f"数据置信度: {pred['confidence']} ({pred['data_points']} 个采样点)")
        if pred['eta_5h_minutes']:
            lines.append(f"5H 额度预计耗尽: {pred['eta_5h_minutes']:.0f} 分钟后")
        if pred['eta_weekly_hours']:
            lines.append(f"周额度预计耗尽: {pred['eta_weekly_hours']:.1f} 小时后")
        lines.append(f"5H 趋势: {pred['trend_5h']} | 周趋势: {pred['trend_weekly']}")
        if rec:
            lines.append("\n🔮 恢复预测:")
            for k, v in rec.items():
                lines.append(f"  {k}: {v}")
        lines.append("=" * 40)
        return "\n".join(lines)


# ==================== 智能开发教练 ====================

class DevCoach:
    def __init__(self, config: Dict[str, Any]):
        self.modes = config.get("coach", {}).get("modes", DEFAULT_CONFIG["coach"]["modes"])
        self.enabled = config.get("coach", {}).get("enabled", True)

    def get_mode(self, quota: QuotaStatus) -> Dict[str, Any]:
        rem = min(quota.five_hour_remaining, quota.weekly_remaining)
        for key in ["deep", "focus", "light", "offline"]:
            m = self.modes.get(key, {})
            if rem >= m.get("min_quota", 0):
                return {"key": key, **m, "remaining_pct": rem * 100}
        return {"key": "offline", **self.modes["offline"], "remaining_pct": 0}

    def get_advice(self, quota: QuotaStatus, forecast: Dict[str, Any]) -> str:
        mode = self.get_mode(quota)
        lines = [f"\n🎯 开发教练建议 [{mode['desc']}]", "-" * 40]
        lines.append(f"当前额度: 5H {quota.five_hour_remaining*100:.1f}% | 周 {quota.weekly_remaining*100:.1f}%")
        lines.append(f"推荐工作: {mode['suggest']}")

        if forecast.get("eta_5h_minutes") and forecast["eta_5h_minutes"] < 30:
            lines.append(f"⚠️ 警告: 5H 额度约 {forecast['eta_5h_minutes']:.0f} 分钟后耗尽，建议立即收尾")
        if forecast.get("eta_weekly_hours") and forecast["eta_weekly_hours"] < 2:
            lines.append(f"⚠️ 警告: 周额度约 {forecast['eta_weekly_hours']:.1f} 小时后耗尽")

        if quota.is_any_exhausted():
            lines.append("\n💡 离线模式建议:")
            lines.append("  1. 阅读项目文档和源码注释")
            lines.append("  2. 在本地运行测试用例")
            lines.append("  3. 用纸笔/思维导图梳理架构")
            lines.append("  4. 整理 TODO 清单，额度恢复后立即执行")
        elif quota.is_low():
            lines.append("\n💡 轻量模式技巧:")
            lines.append("  • 把长提示词拆成短问题，减少单次消耗")
            lines.append("  • 优先处理已部分完成的代码，减少上下文长度")
            lines.append("  • 用本地 IDE 的静态分析代替 AI 诊断")

        lines.append("-" * 40)
        return "\n".join(lines)


# ==================== Git 自动保存 ====================

class GitAutoSaver:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config.get("git_autosave", {})
        self.enabled = self.cfg.get("enabled", True)
        self.threshold = self.cfg.get("threshold", 0.08)
        self.template = self.cfg.get("message_template", "[auto-checkpoint] quota {five_hour_pct:.0f}%5H {weekly_pct:.0f}%WK @ {timestamp}")
        self.auto_push = self.cfg.get("auto_push", False)
        self.saved_this_session = False

    def _is_git_repo(self, path: Path = Path.cwd()) -> bool:
        return (path / ".git").exists() or (path.parent / ".git").exists()

    def _get_repo_root(self, path: Path = Path.cwd()) -> Optional[Path]:
        p = path
        for _ in range(10):
            if (p / ".git").exists():
                return p
            p = p.parent
        return None

    def save(self, quota: QuotaStatus) -> bool:
        if not self.enabled or self.saved_this_session:
            return False
        if not quota.is_low(self.threshold):
            return False
        if not self._is_git_repo():
            logging.debug("当前目录非 Git 仓库，跳过自动保存")
            return False

        repo = self._get_repo_root()
        if not repo:
            return False

        try:
            # 检查是否有变更
            result = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=10)
            if not result.stdout.strip():
                logging.info("Git 工作区干净，无需自动保存")
                return False

            msg = self.template.format(
                five_hour_pct=quota.five_hour_used*100,
                weekly_pct=quota.weekly_used*100,
                timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
            )

            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", msg, "--no-verify"],
                         check=True, capture_output=True, timeout=15)

            if self.auto_push:
                branch = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                                      capture_output=True, text=True, timeout=5).stdout.strip()
                if branch in self.cfg.get("branches", ["main", "master", "dev"]):
                    subprocess.run(["git", "-C", str(repo), "push", "origin", branch],
                                 capture_output=True, timeout=30)

            self.saved_this_session = True
            logging.info(f"✅ Git 自动保存成功: {msg}")
            return True
        except subprocess.CalledProcessError as e:
            logging.warning(f"Git 自动保存失败: {e}")
            return False
        except Exception as e:
            logging.warning(f"Git 自动保存异常: {e}")
            return False

    def reset_session_flag(self):
        self.saved_this_session = False


# ==================== 语音播报系统 ====================

class VoiceNotifier:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config.get("voice", {})
        self.enabled = self.cfg.get("enabled", True)
        self.system = platform.system()
        self.phrases = self.cfg.get("phrases", DEFAULT_CONFIG["voice"]["phrases"])

    def speak(self, text: str):
        if not self.enabled:
            return
        logging.info(f"[语音] {text}")
        try:
            if self.system == "Windows":
                self._windows_speak(text)
            elif self.system == "Darwin":
                self._macos_speak(text)
            else:
                self._linux_speak(text)
        except Exception as e:
            logging.debug(f"语音播报失败: {e}")

    def _windows_speak(self, text: str):
        try:
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
        except ImportError:
            # 备选: PowerShell TTS
            ps = f'Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{text.replace('"', '`"')}");'
            subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=15)

    def _macos_speak(self, text: str):
        subprocess.run(["say", "-v", "Ting-Ting", text], capture_output=True, timeout=10)

    def _linux_speak(self, text: str):
        for cmd in [["spd-say", text], ["espeak", text, "-v", "zh"], ["espeak-ng", text, "-v", "zh"]]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=10)
                return
            except: pass

    def notify(self, event: str, quota: Optional[QuotaStatus] = None):
        phrases = self.phrases.get(event, ["Kimi Code 额度状态变更"])
        text = random.choice(phrases)
        if quota:
            text += f" 5H剩余{quota.five_hour_remaining*100:.0f}%，周剩余{quota.weekly_remaining*100:.0f}%。"
        self.speak(text)


# ==================== 桌面通知系统 ====================

class DesktopNotifier:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config.get("notification", {})
        self.system = platform.system()

    def notify(self, title: str, message: str, urgent: bool = False):
        if not self.cfg.get("enabled", True):
            return
        logging.info(f"[通知] {title}: {message}")
        if self.cfg.get("desktop", True):
            self._desktop(title, message, urgent)
        if urgent and self.cfg.get("sound", True):
            self._sound()
        wh = self.cfg.get("webhook", {})
        if wh.get("enabled") and wh.get("url"):
            self._webhook(title, message, wh)

    def _desktop(self, title: str, msg: str, urgent: bool):
        try:
            if self.system == "Windows":
                try:
                    from win10toast import ToastNotifier
                    ToastNotifier().show_toast(title, msg, duration=10, threaded=True)
                except:
                    ps = f'Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information; $n.BalloonTipTitle="{title.replace('"', '`"')}"; $n.BalloonTipText="{msg.replace('"', '`"')}"; $n.Visible=$true; $n.ShowBalloonTip(8000); Start-Sleep 9; $n.Dispose()'
                    subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=15)
            elif self.system == "Darwin":
                subprocess.run(["osascript", "-e", f'display notification "{msg.replace('"', '\\"')}" with title "{title.replace('"', '\\"')}"'], capture_output=True)
            else:
                for cmd in [["notify-send", title, msg], ["zenity", "--info", f"--title={title}", f"--text={msg}"]]:
                    try: subprocess.run(cmd, capture_output=True, timeout=5); return
                    except: pass
        except: pass

    def _sound(self):
        try:
            if self.system == "Windows":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            elif self.system == "Darwin":
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], capture_output=True, timeout=5)
            else:
                print("\a", end="", flush=True)
        except: print("\a", end="", flush=True)

    def _webhook(self, title: str, msg: str, wh: Dict):
        try:
            url, wtype = wh.get("url", ""), wh.get("type", "wecom")
            if wtype == "wecom": payload = {"msgtype": "text", "text": {"content": f"{title}\n{msg}"}}
            elif wtype == "dingtalk": payload = {"msgtype": "text", "text": {"content": f"{title}\n{msg}"}}
            elif wtype == "lark": payload = {"msg_type": "text", "content": {"text": f"{title}\n{msg}"}}
            else: payload = {"title": title, "message": msg}
            data = json.dumps(payload).encode('utf-8')
            if HAS_REQUESTS:
                requests.post(url, data=data, headers={"Content-Type": "application/json"}, timeout=10)
            else:
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logging.debug(f"Webhook 失败: {e}")


# ==================== 任务管理器 ====================

class TaskManager:
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
                    self.tasks = [DevTask(**t) for t in json.load(f)]
            except: self.tasks = []

    def _save(self):
        try:
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                json.dump([asdict(t) for t in self.tasks], f, ensure_ascii=False, indent=2)
        except: pass

    def add(self, title: str, desc: str = "", priority: int = 3, tags: Optional[List[str]] = None) -> DevTask:
        t = DevTask(
            id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.tasks)}",
            title=title, description=desc, status="pending", priority=priority,
            created_at=datetime.now().isoformat(), tags=tags or []
        )
        self.tasks.append(t)
        self._save()
        return t

    def next_pending(self) -> Optional[DevTask]:
        p = [t for t in self.tasks if t.status in ("pending", "paused")]
        if not p: return None
        p.sort(key=lambda t: (t.priority, t.created_at))
        return p[0]

    def update(self, tid: str, status: str, checkpoint: Optional[Dict] = None):
        for t in self.tasks:
            if t.id == tid:
                t.status = status
                if status == "running": t.started_at = datetime.now().isoformat()
                elif status in ("completed", "failed"): t.completed_at = datetime.now().isoformat()
                if checkpoint: t.checkpoint = checkpoint
                self._save()
                return True
        return False

    def list_all(self) -> List[DevTask]:
        return sorted(self.tasks, key=lambda t: t.created_at, reverse=True)

    def save_checkpoint(self, tid: str, ctx: Dict):
        self.update(tid, "paused", ctx)


# ==================== 成就系统 ====================

class AchievementSystem:
    ACHIEVEMENTS = {
        "first_run": {"name": "初次启航", "desc": "首次启动额度监控", "icon": "🚀"},
        "quota_survivor": {"name": "额度幸存者", "desc": "额度耗尽后坚持离线工作 30 分钟", "icon": "🏝️"},
        "throttle_master": {"name": "节流专家", "desc": "在额度 < 10% 时完成一项任务", "icon": "⚡"},
        "night_owl": {"name": "深夜战神", "desc": "在 23:00-05:00 高效使用额度", "icon": "🦉"},
        "week_warrior": {"name": "周额度守护者", "desc": "连续 7 天没有因额度耗尽中断工作", "icon": "🛡️"},
        "git_savior": {"name": "Git 救星", "desc": "触发自动保存并成功保护工作成果", "icon": "💾"},
        "multi_account": {"name": "账号魔术师", "desc": "成功使用多账号轮询", "icon": "🎭"},
        "forecast_guru": {"name": "预测大师", "desc": "预测精度达到 90% 以上", "icon": "🔮"},
        "pomodoro_pro": {"name": "番茄达人", "desc": "完成 20 个额度感知番茄钟", "icon": "🍅"},
        "deep_diver": {"name": "深度潜水员", "desc": "在深度模式下连续工作 2 小时", "icon": "🤿"},
    }

    def __init__(self, config: Dict[str, Any]):
        self.enabled = config.get("achievements", {}).get("enabled", True)
        self.file = Path.home() / ".kimi-monitor" / "achievements.json"
        self.data = {"unlocked": [], "stats": {}, "first_run": None}
        self._load()

    def _load(self):
        if self.file.exists():
            try:
                with open(self.file, 'r') as f:
                    self.data = json.load(f)
            except: pass

    def _save(self):
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file, 'w') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except: pass

    def unlock(self, key: str):
        if not self.enabled or key in self.data["unlocked"]:
            return
        if key not in self.ACHIEVEMENTS:
            return
        self.data["unlocked"].append(key)
        self.data["unlocked_time"] = self.data.get("unlocked_time", {})
        self.data["unlocked_time"][key] = datetime.now().isoformat()
        self._save()
        ach = self.ACHIEVEMENTS[key]
        logging.info(f"🏆 成就解锁: {ach['icon']} {ach['name']} - {ach['desc']}")

    def check(self, key: str, condition: bool):
        if condition:
            self.unlock(key)

    def increment(self, key: str, amount: int = 1):
        self.data["stats"][key] = self.data["stats"].get(key, 0) + amount
        self._save()

    def get(self, key: str, default=0):
        return self.data["stats"].get(key, default)

    def wall(self) -> str:
        lines = ["\n🏆 成就墙", "=" * 50]
        unlocked = set(self.data.get("unlocked", []))
        for key, info in self.ACHIEVEMENTS.items():
            status = "✅" if key in unlocked else "🔒"
            lines.append(f"{status} {info['icon']} {info['name']:<12} {info['desc']}")
        lines.append(f"\n已解锁: {len(unlocked)} / {len(self.ACHIEVEMENTS)}")
        lines.append("=" * 50)
        return "\n".join(lines)


# ==================== Web 仪表盘 ====================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kimi Code 额度监控 Pro</title>
<style>
:root{--bg:#0f1117;--card:#1a1d29;--accent:#00d4aa;--warn:#f59e0b;--danger:#ef4444;--text:#e2e8f0;--muted:#94a3b8;}
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;}
body{background:var(--bg);color:var(--text);min-height:100vh;padding:20px;}
.header{text-align:center;margin-bottom:30px;}
.header h1{font-size:2rem;background:linear-gradient(90deg,var(--accent),#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.header .subtitle{color:var(--muted);font-size:0.9rem;margin-top:5px;}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;max-width:1200px;margin:0 auto;}
.card{background:var(--card);border-radius:16px;padding:24px;border:1px solid rgba(255,255,255,0.05);transition:transform 0.2s;}
.card:hover{transform:translateY(-2px);}
.card-title{font-size:0.85rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;}
.big-number{font-size:3rem;font-weight:700;line-height:1;}
.big-number.green{color:var(--accent);}.big-number.yellow{color:var(--warn);}.big-number.red{color:var(--danger);}
.status-badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:0.8rem;font-weight:600;margin-top:10px;}
.status-badge.green{background:rgba(0,212,170,0.15);color:var(--accent);}
.status-badge.yellow{background:rgba(245,158,11,0.15);color:var(--warn);}
.status-badge.red{background:rgba(239,68,68,0.15);color:var(--danger);}
.progress-bar{height:8px;background:rgba(255,255,255,0.05);border-radius:4px;margin-top:10px;overflow:hidden;}
.progress-bar-fill{height:100%;border-radius:4px;transition:width 0.5s ease;}
.chart-container{height:200px;margin-top:15px;position:relative;}
.coach-box{background:linear-gradient(135deg,rgba(0,212,170,0.1),rgba(96,165,250,0.1));border:1px solid rgba(0,212,170,0.2);}
.coach-text{font-size:1.1rem;line-height:1.6;color:var(--text);}
.coach-mode{display:inline-block;padding:6px 14px;border-radius:8px;background:var(--accent);color:#000;font-weight:700;font-size:0.9rem;margin-bottom:10px;}
.task-list{list-style:none;}
.task-list li{padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05);display:flex;align-items:center;gap:10px;}
.task-list li:last-child{border-bottom:none;}
.task-prio{width:8px;height:8px;border-radius:50%;}
.task-prio.p1{background:var(--danger);}.task-prio.p2{background:var(--warn);}.task-prio.p3{background:#3b82f6;}
.task-prio.p4{background:var(--muted);}.task-prio.p5{background:rgba(255,255,255,0.2);}
.achievement-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:10px;}
.ach-item{text-align:center;padding:12px 8px;border-radius:10px;background:rgba(255,255,255,0.03);font-size:0.8rem;}
.ach-item.unlocked{background:rgba(0,212,170,0.1);border:1px solid rgba(0,212,170,0.2);}
.ach-icon{font-size:1.5rem;margin-bottom:4px;}
.footer{text-align:center;color:var(--muted);font-size:0.8rem;margin-top:40px;padding-bottom:20px;}
#toast{position:fixed;bottom:20px;right:20px;background:var(--card);border:1px solid var(--accent);padding:16px 20px;border-radius:12px;transform:translateY(100px);transition:transform 0.3s;z-index:1000;}
#toast.show{transform:translateY(0);}
</style>
</head>
<body>
<div class="header">
  <h1>🧠 Kimi Code 额度监控 Pro</h1>
  <div class="subtitle">实时仪表盘 · 智能预测 · 开发教练</div>
</div>
<div class="grid">
  <div class="card">
    <div class="card-title">5H 滚动额度</div>
    <div class="big-number" id="fh-num">--%</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="fh-bar"></div></div>
    <div class="status-badge" id="fh-badge">检测中...</div>
  </div>
  <div class="card">
    <div class="card-title">7天 周额度</div>
    <div class="big-number" id="wk-num">--%</div>
    <div class="progress-bar"><div class="progress-bar-fill" id="wk-bar"></div></div>
    <div class="status-badge" id="wk-badge">检测中...</div>
  </div>
  <div class="card">
    <div class="card-title">预测</div>
    <div style="font-size:0.95rem;line-height:1.8;color:var(--muted);" id="forecast-text">加载中...</div>
  </div>
  <div class="card coach-box">
    <div class="card-title">🎯 开发教练</div>
    <div class="coach-mode" id="coach-mode">--</div>
    <div class="coach-text" id="coach-text">正在分析额度状态...</div>
  </div>
  <div class="card">
    <div class="card-title">📋 任务队列</div>
    <ul class="task-list" id="task-list"><li>加载中...</li></ul>
  </div>
  <div class="card">
    <div class="card-title">🏆 成就墙</div>
    <div class="achievement-grid" id="ach-grid">加载中...</div>
  </div>
</div>
<div class="footer">KCAMS-Pro v2.0 · 按 Ctrl+C 停止监控 · 数据每 5 秒刷新</div>
<div id="toast"><strong id="toast-title">通知</strong><br><span id="toast-msg">...</span></div>
<script>
let lastStatus='';
function update(){
  fetch('/api/status').then(r=>r.json()).then(d=>{
    const fh=d.five_hour_remaining*100, wk=d.weekly_remaining*100;
    document.getElementById('fh-num').textContent=fh.toFixed(1)+'%';
    document.getElementById('wk-num').textContent=wk.toFixed(1)+'%';
    document.getElementById('fh-bar').style.width=fh+'%';
    document.getElementById('wk-bar').style.width=wk+'%';
    document.getElementById('fh-bar').style.background=fh>30?'var(--accent)':(fh>10?'var(--warn)':'var(--danger)');
    document.getElementById('wk-bar').style.background=wk>30?'var(--accent)':(wk>10?'var(--warn)':'var(--danger)');
    document.getElementById('fh-num').className='big-number '+(fh>30?'green':(fh>10?'yellow':'red'));
    document.getElementById('wk-num').className='big-number '+(wk>30?'green':(wk>10?'yellow':'red'));
    document.getElementById('fh-badge').textContent=fh>30?'充足':(fh>10?'紧张':'耗尽');
    document.getElementById('fh-badge').className='status-badge '+(fh>30?'green':(fh>10?'yellow':'red'));
    document.getElementById('wk-badge').textContent=wk>30?'充足':(wk>10?'紧张':'耗尽');
    document.getElementById('wk-badge').className='status-badge '+(wk>30?'green':(wk>10?'yellow':'red'));
    document.getElementById('forecast-text').innerHTML=d.forecast_html||'暂无预测数据';
    document.getElementById('coach-mode').textContent=d.coach_mode||'--';
    document.getElementById('coach-text').textContent=d.coach_advice||'分析中...';
    let tl=''; d.tasks.forEach(t=>{tl+=`<li><div class="task-prio p${t.priority}"></div><div>${t.title}<br><small style="color:var(--muted)">${t.status}</small></div></li>`;});
    document.getElementById('task-list').innerHTML=tl||'<li style="color:var(--muted)">暂无任务</li>';
    let ag=''; d.achievements.forEach(a=>{ag+=`<div class="ach-item ${a.unlocked?'unlocked':''}"><div class="ach-icon">${a.icon}</div><div>${a.name}</div></div>`;});
    document.getElementById('ach-grid').innerHTML=ag;
    const st=(fh<2||wk<2)?'exhausted':(fh<15||wk<15)?'low':'ok';
    if(st!==lastStatus&&lastStatus!==''){showToast(st==='exhausted'?'🔴 额度耗尽':(st==='low'?'🟡 额度紧张':'🟢 额度恢复'),d.toast_msg||'状态变更');}
    lastStatus=st;
  }).catch(e=>console.error(e));
}
function showToast(t,m){const el=document.getElementById('toast');document.getElementById('toast-title').textContent=t;document.getElementById('toast-msg').textContent=m;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),5000);}
update(); setInterval(update,5000);
</script>
</body>
</html>
"""

class DashboardServer:
    def __init__(self, config: Dict[str, Any], state: Dict[str, Any]):
        self.cfg = config.get("web_dashboard", {})
        self.enabled = self.cfg.get("enabled", True)
        self.host = self.cfg.get("host", "127.0.0.1")
        self.port = self.cfg.get("port", 17421)
        self.state = state
        self.server = None
        self.thread = None

    def start(self):
        if not self.enabled:
            return
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 静默日志

            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(DASHBOARD_HTML.encode('utf-8'))
                elif self.path == "/api/status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(state.get("api_data", {}), ensure_ascii=False).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()

        try:
            self.server = HTTPServer((self.host, self.port), Handler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            logging.info(f"🌐 Web 仪表盘已启动: http://{self.host}:{self.port}")
        except OSError as e:
            logging.warning(f"Web 仪表盘启动失败 (端口 {self.port} 可能被占用): {e}")

    def stop(self):
        if self.server:
            self.server.shutdown()


# ==================== 番茄钟 (额度感知) ====================

class PomodoroTimer:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config.get("pomodoro", {})
        self.enabled = self.cfg.get("enabled", True)
        self.adaptive = self.cfg.get("quota_adaptive", True)
        self.base_focus = self.cfg.get("focus_minutes", 25)
        self.base_break = self.cfg.get("break_minutes", 5)
        self.long_break = self.cfg.get("long_break_minutes", 15)
        self.cycles_before_long = self.cfg.get("cycles_before_long_break", 4)
        self.cycle = 0
        self.in_focus = False
        self.start_time = None

    def get_times(self, quota: QuotaStatus) -> Tuple[int, int]:
        if not self.adaptive or not self.enabled:
            return self.base_focus, self.base_break
        rem = min(quota.five_hour_remaining, quota.weekly_remaining)
        if rem > 0.5:
            return self.base_focus, self.base_break
        elif rem > 0.15:
            return max(15, int(self.base_focus * rem * 1.5)), max(5, self.base_break)
        elif rem > 0.05:
            return 10, 10  # 额度紧张，短冲刺+长休息等恢复
        else:
            return 0, 0  # 离线模式

    def start_cycle(self, quota: QuotaStatus):
        if not self.enabled:
            return None
        focus, brk = self.get_times(quota)
        if focus == 0:
            return "额度耗尽，进入离线模式。建议阅读文档或整理思路。"
        self.in_focus = True
        self.start_time = time.time()
        self.cycle += 1
        is_long = self.cycle % self.cycles_before_long == 0
        break_time = self.long_break if is_long else brk
        return f"🍅 番茄钟 #{self.cycle} 开始 | 专注 {focus} 分钟 | 休息 {break_time} 分钟"

    def check(self, quota: QuotaStatus) -> Optional[str]:
        if not self.enabled or not self.start_time:
            return None
        focus, brk = self.get_times(quota)
        elapsed = (time.time() - self.start_time) / 60
        if self.in_focus and elapsed >= focus:
            self.in_focus = False
            self.start_time = time.time()
            is_long = self.cycle % self.cycles_before_long == 0
            return f"⏰ 专注时间结束！休息 {self.long_break if is_long else brk} 分钟"
        elif not self.in_focus and elapsed >= brk:
            return "休息结束，准备下一轮"
        return None


# ==================== 主控循环 ====================

class MonitorPro:
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self._setup_logging()

        self.checker = QuotaChecker(self.config)
        self.forecaster = QuotaForecaster(self.config)
        self.coach = DevCoach(self.config)
        self.git_saver = GitAutoSaver(self.config)
        self.voice = VoiceNotifier(self.config)
        self.desktop = DesktopNotifier(self.config)
        self.tasks = TaskManager(self.config)
        self.achievements = AchievementSystem(self.config)
        self.pomodoro = PomodoroTimer(self.config)

        self.state = {"api_data": {}, "last_quota": None, "was_available": True,
                      "exhausted_since": None, "session_start": time.time()}
        self.dashboard = DashboardServer(self.config, self.state)

        self.consecutive_errors = 0
        self.last_git_save = 0

    def _load_config(self, path: Optional[str]) -> Dict:
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                if HAS_YAML and path.endswith(('.yaml', '.yml')):
                    return {**DEFAULT_CONFIG, **yaml.safe_load(f)}
                else:
                    return {**DEFAULT_CONFIG, **json.load(f)}
        for p in [Path.home()/".kimi-monitor"/"config.yaml", Path.home()/".kimi-monitor"/"config.json"]:
            if p.exists():
                with open(p, 'r', encoding='utf-8') as f:
                    if HAS_YAML and p.suffix in ('.yaml', '.yml'):
                        return {**DEFAULT_CONFIG, **yaml.safe_load(f)}
                    else:
                        return {**DEFAULT_CONFIG, **json.load(f)}
        return DEFAULT_CONFIG.copy()

    def _setup_logging(self):
        lc = self.config.get("logging", {})
        level = getattr(logging, lc.get("level", "INFO").upper(), logging.INFO)
        lf = Path(lc.get("file", "~/.kimi-monitor/monitor.log")).expanduser()
        lf.parent.mkdir(parents=True, exist_ok=True)
        handlers = [logging.StreamHandler(sys.stdout)]
        try: handlers.append(logging.FileHandler(lf, encoding='utf-8'))
        except: pass
        logging.basicConfig(level=level, format='%(asctime)s [%(levelname)s] %(message)s', handlers=handlers)

    def _update_dashboard_data(self, quota: QuotaStatus, forecast: Dict, coach_text: str, mode: Dict):
        tasks = [{"title": t.title, "status": t.status, "priority": t.priority} 
                 for t in self.tasks.list_all()[:8]]
        achs = []
        for key, info in AchievementSystem.ACHIEVEMENTS.items():
            achs.append({"key": key, "name": info["name"], "icon": info["icon"],
                        "unlocked": key in self.achievements.data.get("unlocked", [])})

        fh_html = ""
        if forecast.get("eta_5h_minutes"):
            fh_html += f"5H 预计耗尽: <strong>{forecast['eta_5h_minutes']:.0f}</strong> 分钟后<br>"
        if forecast.get("eta_weekly_hours"):
            fh_html += f"周额度预计耗尽: <strong>{forecast['eta_weekly_hours']:.1f}</strong> 小时后<br>"
        fh_html += f"趋势: 5H <strong>{forecast.get('trend_5h','unknown')}</strong> | 周 <strong>{forecast.get('trend_weekly','unknown')}</strong>"

        toast = ""
        if quota.is_any_exhausted():
            toast = "额度已耗尽，进入离线模式"
        elif quota.is_low():
            toast = "额度紧张，请注意节奏"
        else:
            toast = "额度充足，火力全开"

        self.state["api_data"] = {
            "five_hour_remaining": quota.five_hour_remaining,
            "weekly_remaining": quota.weekly_remaining,
            "monthly_used": quota.monthly_used,
            "forecast_html": fh_html,
            "coach_mode": mode.get("desc", "--"),
            "coach_advice": coach_text.replace("\n", " "),
            "tasks": tasks,
            "achievements": achs,
            "toast_msg": toast,
            "timestamp": datetime.now().isoformat()
        }

    def run_once(self) -> QuotaStatus:
        logging.info("🔍 查询额度中...")
        quota = self.checker.get_quota()
        self.consecutive_errors = 0
        self.state["last_quota"] = quota

        # 记录历史 & 预测
        self.forecaster.record(quota)
        forecast = self.forecaster.predict_exhaustion()

        # 开发教练
        mode = self.coach.get_mode(quota)
        advice = self.coach.get_advice(quota, forecast)

        # Git 自动保存
        if quota.is_critical() and time.time() - self.last_git_save > 300:
            if self.git_saver.save(quota):
                self.last_git_save = time.time()
                self.voice.notify("checkpoint_saved")
                self.achievements.check("git_savior", True)
        if not quota.is_low():
            self.git_saver.reset_session_flag()

        # 成就检测
        self.achievements.check("first_run", self.achievements.data.get("first_run") is None)
        if self.achievements.data.get("first_run") is None:
            self.achievements.data["first_run"] = datetime.now().isoformat()
            self.achievements._save()
        self.achievements.check("throttle_master", quota.five_hour_remaining < 0.10 and not quota.is_any_exhausted())
        hour = datetime.now().hour
        self.achievements.check("night_owl", (hour >= 23 or hour < 5) and not quota.is_any_exhausted())

        # 状态变更处理
        is_avail = not quota.is_any_exhausted()
        if not self.state["was_available"] and is_avail:
            self._on_recovery(quota, mode, advice)
        elif self.state["was_available"] and not is_avail:
            self._on_exhaustion(quota, mode, advice)
        elif quota.is_low() and not quota.is_any_exhausted():
            if self.state.get("last_low_alert", 0) < time.time() - 600:
                self._on_low(quota, mode, advice)
                self.state["last_low_alert"] = time.time()

        self.state["was_available"] = is_avail

        # 更新仪表盘
        self._update_dashboard_data(quota, forecast, advice, mode)

        # 打印状态
        self._print_status(quota, forecast, mode, advice)

        return quota

    def _on_recovery(self, quota: QuotaStatus, mode: Dict, advice: str):
        logging.info("✅ 额度恢复！")
        self.voice.notify("quota_available", quota)
        self.desktop.notify("🟢 Kimi Code 额度已恢复", 
            f"模式: {mode['desc']}\n{mode['suggest']}\n\n{advice}", urgent=True)
        if self.state.get("exhausted_since"):
            downtime = (time.time() - self.state["exhausted_since"]) / 60
            if downtime > 30:
                self.achievements.check("quota_survivor", True)
            self.state["exhausted_since"] = None

        # 自动恢复命令
        cmd = self.config.get("auto_recover", {}).get("command", "")
        if cmd:
            try: subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except: pass

        task = self.tasks.next_pending()
        if task:
            self.desktop.notify("📋 续跑任务", f"下一条: {task.title}\n{task.description[:60]}...")

    def _on_exhaustion(self, quota: QuotaStatus, mode: Dict, advice: str):
        logging.warning("🚫 额度耗尽")
        self.state["exhausted_since"] = time.time()
        self.voice.notify("quota_exhausted", quota)
        self.desktop.notify("🔴 Kimi Code 额度耗尽", 
            f"已进入 {mode['desc']}\n{mode['suggest']}\n\n{advice}", urgent=True)

        # 保存任务断点
        task = self.tasks.next_pending()
        if task:
            self.tasks.save_checkpoint(task.id, {
                "saved_at": datetime.now().isoformat(),
                "reason": "quota_exhausted",
                "quota": {"5h": quota.five_hour_used, "wk": quota.weekly_used}
            })

    def _on_low(self, quota: QuotaStatus, mode: Dict, advice: str):
        self.voice.notify("quota_low", quota)
        self.desktop.notify("🟡 Kimi Code 额度紧张", 
            f"5H: {quota.five_hour_remaining*100:.1f}% | 周: {quota.weekly_remaining*100:.1f}%\n{advice}", urgent=False)

    def _print_status(self, quota: QuotaStatus, forecast: Dict, mode: Dict, advice: str):
        now = datetime.now()
        print("\n" + "═" * 60)
        print(f"  🧠 Kimi Code Pro  {now.strftime('%m-%d %H:%M:%S')}  [{mode['desc']}]")
        print("─" * 60)

        fh, wk = quota.five_hour_remaining * 100, quota.weekly_remaining * 100
        print(f"  {'🟢' if fh>30 else ('🟡' if fh>10 else '🔴')} 5H 窗口: {fh:5.1f}% 可用  (已用 {quota.five_hour_used*100:.1f}%)")
        print(f"  {'🟢' if wk>30 else ('🟡' if wk>10 else '🔴')} 7天窗口: {wk:5.1f}% 可用  (已用 {quota.weekly_used*100:.1f}%)")

        if forecast.get("eta_5h_minutes"):
            print(f"  ⏳ 5H 预计耗尽: {forecast['eta_5h_minutes']:.0f} 分钟后")
        if forecast.get("eta_weekly_hours"):
            print(f"  ⏳ 周预计耗尽: {forecast['eta_weekly_hours']:.1f} 小时后")

        print("─" * 60)
        print(f"  💡 教练建议: {mode['suggest']}")
        if quota.is_any_exhausted():
            print("  ⏸️  额度耗尽，智能等待中... 额度恢复将自动通知")
        print("═" * 60)

    def run_daemon(self):
        logging.info("=" * 60)
        logging.info("Kimi Code 额度监控 Pro v2.0 已启动")
        if self.config.get("web_dashboard", {}).get("enabled", True):
            self.dashboard.start()
        logging.info("按 Ctrl+C 停止")
        logging.info("=" * 60)

        self.voice.speak("Kimi Code 额度监控已启动")
        self.desktop.notify("🚀 监控已启动", "Kimi Code Pro 正在后台运行\n额度恢复时将语音+弹窗通知", urgent=False)

        # 启动番茄钟提示
        if self.config.get("pomodoro", {}).get("enabled", True):
            logging.info("🍅 额度感知番茄钟已启用")

        while True:
            try:
                quota = self.run_once()

                # 智能间隔
                if quota.is_any_exhausted():
                    interval = 600 if quota.is_weekly_exhausted() else 300
                elif quota.is_critical():
                    interval = self.config.get("critical_interval_seconds", 30)
                elif quota.is_low():
                    interval = self.config.get("urgent_interval_seconds", 60)
                else:
                    interval = self.config.get("check_interval_seconds", 300)

                next_check = datetime.now() + timedelta(seconds=interval)
                logging.info(f"下次检查: {interval} 秒后 ({next_check:%H:%M:%S})")
                time.sleep(interval)

            except KeyboardInterrupt:
                print("\n👋 监控已停止")
                self.voice.speak("监控已停止")
                self.desktop.notify("⏹️ 监控已停止", "Kimi Code Pro 已退出", urgent=False)
                break
            except Exception as e:
                self.consecutive_errors += 1
                logging.error(f"异常 ({self.consecutive_errors}次): {e}")
                if self.consecutive_errors >= 3:
                    self.desktop.notify("⚠️ 监控异常", f"连续 {self.consecutive_errors} 次失败", urgent=False)
                time.sleep(self.config.get("check_interval_seconds", 300))

    def run_forecast(self):
        """仅运行预测报告"""
        try:
            quota = self.checker.get_quota()
            self.forecaster.record(quota)
            print(self.forecaster.get_report(quota))
            print(self.coach.get_advice(quota, self.forecaster.predict_exhaustion()))
        except Exception as e:
            print(f"❌ 查询失败: {e}")

    def run_coach(self):
        """仅查看教练建议"""
        try:
            quota = self.checker.get_quota()
            mode = self.coach.get_mode(quota)
            forecast = self.forecaster.predict_exhaustion()
            print(self.coach.get_advice(quota, forecast))
        except Exception as e:
            print(f"❌ 查询失败: {e}")


# ==================== CLI 入口 ====================

def init_config():
    d = Path.home() / ".kimi-monitor"
    d.mkdir(exist_ok=True)
    cf = d / "config.yaml"
    if not cf.exists():
        with open(cf, 'w', encoding='utf-8') as f:
            if HAS_YAML:
                yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True, sort_keys=False)
            else:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"✅ 配置已创建: {cf}")
    else:
        print(f"配置已存在: {cf}")
    (d / "tasks").mkdir(exist_ok=True)
    return cf


def main():
    parser = argparse.ArgumentParser(
        description="Kimi Code 额度监控 Pro v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
用法示例:
  %(prog)s --init                          # 初始化配置
  %(prog)s --daemon                        # 启动完整守护(含Web仪表盘)
  %(prog)s --daemon --no-web               # 纯后台模式
  %(prog)s --once                          # 单次查询
  %(prog)s --forecast                      # 查看预测报告
  %(prog)s --coach                         # 查看开发建议
  %(prog)s --dashboard-only                # 仅启动Web仪表盘
  %(prog)s --add-task "重构utils" -p 1     # 添加任务
  %(prog)s --list-tasks                    # 查看任务
  %(prog)s --achievements                  # 查看成就墙
  %(prog)s --debug                         # 调试原始API响应
        """
    )
    parser.add_argument("--init", action="store_true", help="初始化配置")
    parser.add_argument("--once", action="store_true", help="单次查询")
    parser.add_argument("--daemon", action="store_true", help="启动守护模式")
    parser.add_argument("--no-web", action="store_true", help="守护模式下不启动Web仪表盘")
    parser.add_argument("--forecast", action="store_true", help="查看额度预测报告")
    parser.add_argument("--coach", action="store_true", help="查看开发教练建议")
    parser.add_argument("--dashboard-only", action="store_true", help="仅启动Web仪表盘")
    parser.add_argument("--config", "-c", help="指定配置文件")
    parser.add_argument("--add-task", metavar="TITLE", help="添加任务")
    parser.add_argument("--task-desc", default="", help="任务描述")
    parser.add_argument("--task-priority", "-p", type=int, default=3, choices=range(1,6), help="优先级 1-5")
    parser.add_argument("--list-tasks", action="store_true", help="列出任务")
    parser.add_argument("--achievements", action="store_true", help="查看成就墙")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    if args.init:
        init_config()
        print("\n提示: 首次使用请运行 `kimi-code login`")
        return

    if args.add_task:
        tm = TaskManager(DEFAULT_CONFIG)
        t = tm.add(args.add_task, args.task_desc, args.task_priority)
        print(f"✅ 任务已添加: {t.id} | {t.title} | P{t.priority}")
        return

    if args.list_tasks:
        tm = TaskManager(DEFAULT_CONFIG)
        tasks = tm.list_all()
        if not tasks: print("暂无任务"); return
        print(f"\n{'ID':<25} {'状态':<8} {'P':<3} {'标题':<30}")
        print("-" * 70)
        for t in tasks[:30]:
            print(f"{t.id:<25} {t.status:<8} {t.priority:<3} {t.title:<30}")
        return

    if args.achievements:
        ach = AchievementSystem(DEFAULT_CONFIG)
        print(ach.wall())
        return

    if args.dashboard_only:
        state = {"api_data": {}}
        ds = DashboardServer(DEFAULT_CONFIG, state)
        ds.start()
        print(f"🌐 Web 仪表盘: http://{ds.host}:{ds.port}")
        print("按 Ctrl+C 停止")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            ds.stop()
        return

    pro = MonitorPro(config_path=args.config)

    if args.no_web:
        pro.config["web_dashboard"]["enabled"] = False

    if args.debug:
        print("🔍 调试模式...")
        try:
            q = pro.checker.get_quota()
            print(json.dumps(q.raw_data, ensure_ascii=False, indent=2))
            pro._print_status(q, pro.forecaster.predict_exhaustion(), pro.coach.get_mode(q), "")
        except Exception as e:
            import traceback; traceback.print_exc()
        return

    if args.forecast:
        pro.run_forecast()
    elif args.coach:
        pro.run_coach()
    elif args.daemon:
        pro.run_daemon()
    elif args.once:
        pro.run_once()
    else:
        pro.run_once()
        print("\n提示: 使用 --daemon 启动完整守护模式，--forecast 查看预测")


if __name__ == "__main__":
    main()
