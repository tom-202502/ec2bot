#!/usr/bin/env python3
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
from datetime import datetime
from typing import Callable, Awaitable

import aws_manager_secure as aws
from state_store import StateStore

log = logging.getLogger("monitor")


def now_local(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S")


class MonitorEngine:
    def __init__(self, cfg: dict, notify_func: Callable[[list, str], Awaitable]):
        self.cfg = cfg
        self.accounts = cfg["aws_accounts"]
        self.notify = notify_func
        self.chat_ids = cfg["telegram"]["alert_chat_ids"]
        mc = cfg.get("monitor", {})
        self.interval = mc.get("check_interval", 120)
        self.cpu_threshold = mc.get("cpu_alert_threshold", 85)
        self.consecutive_req = mc.get("alert_consecutive", 2)
        self.cooldown = mc.get("alert_cooldown", 600)
        self.notify_change = mc.get("notify_state_change", True)
        self.cw_period = mc.get("cloudwatch_period", 300)
        self.tz = mc.get("timezone", "Asia/Shanghai")
        self.enable_recovery = mc.get("enable_recovery_notice", True)
        self.enable_cpu_alarm = mc.get("enable_cpu_alarm", True)
        self._state_cache = {}
        self._cpu_count = {}
        self._cooldown = {}
        self._stop_event = asyncio.Event()
        self.state_store = StateStore(cfg.get("storage", {}).get("sqlite_path", "/opt/ec2bot/run/ec2bot.db"))

    def _cooldown_ok(self, key: str) -> bool:
        last = self._cooldown.get(key, 0)
        if time.time() - last > self.cooldown:
            self._cooldown[key] = time.time()
            return True
        return False

    def _fetch_instance_status(self, acc, inst_id):
        """同步获取单个实例状态（在线程池中执行）"""
        return aws.get_instance_status(acc, inst_id, self.tz)

    def _fetch_cpu(self, acc, inst_id):
        """同步获取CPU数据（在线程池中执行）"""
        return aws.get_cpu_utilization(acc, inst_id, self.cw_period, 3)

    async def _check_once(self):
        # 并发获取所有实例状态
        tasks = []
        task_meta = []  # (acc, inst) 与 tasks 一一对应
        for acc in self.accounts:
            for inst in acc.get("instances", []):
                tasks.append(asyncio.to_thread(self._fetch_instance_status, acc, inst["id"]))
                task_meta.append((acc, inst))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 需要查 CPU 的实例
        cpu_tasks = []
        cpu_meta = []  # (acc, inst, info) 与 cpu_tasks 一一对应

        for (acc, inst), result in zip(task_meta, results):
            iid = inst["id"]
            iname = inst["name"]

            if isinstance(result, Exception):
                log.warning("巡检失败 %s: %s", iname, result)
                continue

            info = result
            state = info["state"]
            old = self._state_cache.get(iid)

            if self.notify_change and old is not None and old != state and self._cooldown_ok(f"state:{iid}"):
                text = (
                    f"*[状态变化告警]*\n"
                    f"账户: `{acc['alias']}`\n实例: `{iname}`\nID: `{iid}`\n"
                    f"变化: `{old}` => `{state}`\n时间: `{now_local(self.tz)}`"
                )
                await self.notify(self.chat_ids, text)
            elif self.enable_recovery and old == "stopped" and state == "running" and self._cooldown_ok(f"recovery:{iid}"):
                text = (
                    f"*[恢复通知]*\n账户: `{acc['alias']}`\n实例: `{iname}`\nID: `{iid}`\n"
                    f"状态: `running`\n时间: `{now_local(self.tz)}`"
                )
                await self.notify(self.chat_ids, text)
            self._state_cache[iid] = state

            if state != "running":
                self._cpu_count[iid] = 0
                self.state_store.upsert(iid, state, 0, now_local(self.tz))
                continue

            if self.enable_cpu_alarm:
                cpu_tasks.append(asyncio.to_thread(self._fetch_cpu, acc, iid))
                cpu_meta.append((acc, inst, info))
            else:
                self._cpu_count[iid] = 0
                self.state_store.upsert(iid, state, self._cpu_count.get(iid, 0), now_local(self.tz))

        # 并发获取所有 CPU 数据
        if cpu_tasks:
            cpu_results = await asyncio.gather(*cpu_tasks, return_exceptions=True)
            for (acc, inst, info), cpu_result in zip(cpu_meta, cpu_results):
                iid = inst["id"]
                iname = inst["name"]
                state = info["state"]

                if isinstance(cpu_result, Exception):
                    log.warning("获取CPU失败 %s: %s", iname, cpu_result)
                    self.state_store.upsert(iid, state, self._cpu_count.get(iid, 0), now_local(self.tz))
                    continue

                cpu_pts = cpu_result
                if not cpu_pts:
                    self.state_store.upsert(iid, state, self._cpu_count.get(iid, 0), now_local(self.tz))
                    continue

                latest = cpu_pts[-1]
                if latest >= self.cpu_threshold:
                    self._cpu_count[iid] = self._cpu_count.get(iid, 0) + 1
                    if self._cpu_count[iid] >= self.consecutive_req and self._cooldown_ok(f"cpu:{iid}"):
                        await self.notify(
                            self.chat_ids,
                            f"*[CPU 告警]*\n账户: `{acc['alias']}`\n实例: `{iname}`\n公网IP: `{', '.join(info.get('public_ips', [])) or info.get('ip','N/A')}`\n内网IP: `{', '.join(info.get('private_ips', [])) or info.get('private_ip','N/A')}`\nCPU: `{latest}%`\n时间: `{now_local(self.tz)}`"
                        )
                else:
                    self._cpu_count[iid] = 0

                self.state_store.upsert(iid, state, self._cpu_count.get(iid, 0), now_local(self.tz))

    def stop(self):
        self._stop_event.set()

    async def run(self):
        # 初始化：并发获取所有实例状态（不阻塞事件循环）
        init_tasks = []
        init_meta = []
        for acc in self.accounts:
            for inst in acc.get("instances", []):
                init_tasks.append(asyncio.to_thread(self._fetch_instance_status, acc, inst["id"]))
                init_meta.append((acc, inst))

        results = await asyncio.gather(*init_tasks, return_exceptions=True)
        for (acc, inst), result in zip(init_meta, results):
            iid = inst["id"]
            if isinstance(result, Exception):
                cached = self.state_store.get_state(iid)
                if cached:
                    self._state_cache[iid] = cached
            else:
                self._state_cache[iid] = result["state"]
                self.state_store.upsert(iid, result["state"], 0, now_local(self.tz))

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
                break
            except asyncio.TimeoutError:
                pass
            try:
                await self._check_once()
            except asyncio.CancelledError:
                log.info("巡检任务收到取消信号，准备退出")
                raise
            except Exception as e:
                log.error("巡检异常: %s", e)
        log.info("巡检任务已退出")
