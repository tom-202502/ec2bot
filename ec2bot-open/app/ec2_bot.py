#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

import aws_manager_secure as aws
from audit_store import AuditStore
from monitor_secure import MonitorEngine
from config_manager import ConfigManager
from secret_manager import SecretEnvManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ec2bot")

CFG_PATH = os.getenv("EC2BOT_CONFIG", "/opt/ec2bot/config/config.yaml")
ENV_PATH = os.getenv("EC2BOT_ENV", "/opt/ec2bot/config/.env")
CFG_MGR = ConfigManager(CFG_PATH)
SECRET_MGR = SecretEnvManager(ENV_PATH)
with open(CFG_PATH, "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

TZ = CFG.get("monitor", {}).get("timezone", os.getenv("BOT_TIMEZONE", "Asia/Shanghai"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN 未配置")

ADMINS = set(CFG["telegram"].get("admins", []))
OPERATORS = set(CFG["telegram"].get("operators", []))
VIEWERS = set(CFG["telegram"].get("viewers", []))
ALLOWED = ADMINS | OPERATORS | VIEWERS
ACCOUNTS = CFG["aws_accounts"]
AUDIT = AuditStore(CFG.get("storage", {}).get("sqlite_path", "/opt/ec2bot/run/ec2bot.db"), TZ)
SECRET_SESSIONS = {}
CONFIG_SESSIONS = {}
FAST_INDEX = {"ip": {}, "ts": 0}
FAST_INDEX_TTL = 86400


def now_local() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M:%S")


def role_of(uid: int) -> str:
    if uid in ADMINS:
        return "admin"
    if uid in OPERATORS:
        return "operator"
    if uid in VIEWERS:
        return "viewer"
    return "none"


def auth(update: Update) -> bool:
    return update.effective_user.id in ALLOWED


def can_operate(uid: int, action: str) -> bool:
    role = role_of(uid)
    if action in ("status", "detail", "dashboard", "check", "log"):
        return role in ("viewer", "operator", "admin")
    if action == "reboot":
        return role in ("operator", "admin")
    if action in ("start", "stop"):
        return role == "admin"
    return False


def state_badge(state: str) -> str:
    return {"running": "[ ON ]", "stopped": "[OFF]", "pending": "[...]", "stopping": "[-->]"}.get(state, f"[{state[:4]}]")


def acc_kb(prefix: str):
    return InlineKeyboardMarkup([[InlineKeyboardButton(a["alias"], callback_data=f"{prefix}{i}")] for i, a in enumerate(ACCOUNTS)])


def paged_inst_kb(acc_idx: int, mode: str, page: int = 0, page_size: int = 15):
    acc = ACCOUNTS[acc_idx]
    insts = acc.get("instances", [])
    total = len(insts)
    start = page * page_size
    end = min(start + page_size, total)
    rows = []
    for i in insts[start:end]:
        cb = f"{mode}inst_{acc_idx}_{i['id']}"
        rows.append([InlineKeyboardButton(i['name'], callback_data=cb)])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"{mode}page_{acc_idx}_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"{mode}page_{acc_idx}_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 返回账户", callback_data=f"{mode}_{acc_idx}")])
    return InlineKeyboardMarkup(rows), total, start, end


def build_status_page(acc_idx: int, page: int = 0, page_size: int = 15):
    acc = ACCOUNTS[acc_idx]
    rs = get_account_status_live(acc_idx)
    total = len(rs)
    start = page * page_size
    end = min(start + page_size, total)
    text = [f"{acc['alias']} - {now_local()}", f"第 {page+1} 页 | {start+1}-{end}/{total}"]
    for i in rs[start:end]:
        if i.get("ok"):
            text.append(f"{state_badge(i['state'])} {i['cfg_name']} {i.get('ip','N/A')}")
        else:
            text.append(f"[ERR] {i['cfg_name']} {str(i.get('error','?'))[:40]}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"stspage_{acc_idx}_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"stspage_{acc_idx}_{page+1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("🔙 返回账户", callback_data="sts_back")])
    return "\n".join(text), InlineKeyboardMarkup(rows)


def find_inst(acc_idx: int, inst_id: str):
    acc = ACCOUNTS[acc_idx]
    inst = next((i for i in acc.get("instances", []) if i["id"] == inst_id), None)
    return acc, inst


def denied_policy(account: dict, inst_cfg: dict, action: str):
    if action not in inst_cfg.get("allow_actions", ["status", "detail", "reboot", "start", "stop"]):
        return f"实例 `{inst_cfg['name']}` 不允许执行 `{action}`"
    pol = CFG.get("policy", {})
    if account.get("environment") == "prod" and inst_cfg.get("critical") and action == "stop" and pol.get("protect_stop_in_production", True):
        return "生产关键实例已开启 stop 保护，拒绝停止"
    return ""


def reload_runtime_config():
    global CFG, ADMINS, OPERATORS, VIEWERS, ALLOWED, ACCOUNTS, TZ
    CFG = CFG_MGR.load()
    TZ = CFG.get("monitor", {}).get("timezone", os.getenv("BOT_TIMEZONE", "Asia/Shanghai"))
    ADMINS = set(CFG["telegram"].get("admins", []))
    OPERATORS = set(CFG["telegram"].get("operators", []))
    VIEWERS = set(CFG["telegram"].get("viewers", []))
    ALLOWED = ADMINS | OPERATORS | VIEWERS
    ACCOUNTS = CFG["aws_accounts"]


_STATUS_CACHE = {}
_STATUS_CACHE_TTL = 30


def get_account_status_live(acc_idx: int):
    now = time.time()
    cached = _STATUS_CACHE.get(acc_idx)
    if cached and now - cached["ts"] < _STATUS_CACHE_TTL:
        return cached["data"]
    acc = ACCOUNTS[acc_idx]
    data = aws.get_all_instances_status(acc, TZ)
    _STATUS_CACHE[acc_idx] = {"data": data, "ts": now}
    return data


def invalidate_account_cache(acc_idx: int = None):
    if acc_idx is not None:
        _STATUS_CACHE.pop(acc_idx, None)
    else:
        _STATUS_CACHE.clear()
    FAST_INDEX["ip"].clear()
    FAST_INDEX["ts"] = 0


def rebuild_fast_ip_index():
    from concurrent.futures import ThreadPoolExecutor
    index = {}

    def _fetch(acc_idx):
        return acc_idx, get_account_status_live(acc_idx)

    with ThreadPoolExecutor(max_workers=len(ACCOUNTS)) as pool:
        results = list(pool.map(_fetch, range(len(ACCOUNTS))))

    for acc_idx, rs in results:
        acc = ACCOUNTS[acc_idx]
        for i in rs:
            rec = (acc_idx, acc, i)
            # 索引所有公网/内网 IP（含多网卡多IP场景）
            for ip in i.get('public_ips', []):
                index[ip] = rec
            for ip in i.get('private_ips', []):
                index[ip] = rec
            # 兜底：旧字段
            if i.get('ip') and i.get('ip') != 'N/A' and i['ip'] not in index:
                index[i['ip']] = rec
            if i.get('private_ip') and i.get('private_ip') != 'N/A' and i['private_ip'] not in index:
                index[i['private_ip']] = rec
    FAST_INDEX['ip'] = index
    FAST_INDEX['ts'] = time.time()


def get_fast_ip_match(ip: str):
    now = time.time()
    if not FAST_INDEX['ip'] or now - FAST_INDEX['ts'] > FAST_INDEX_TTL:
        rebuild_fast_ip_index()
    return FAST_INDEX['ip'].get(ip)


def set_cpu_alarm_enabled(enabled: bool):
    cfg = CFG_MGR.load()
    cfg.setdefault("monitor", {})["enable_cpu_alarm"] = enabled
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    reload_runtime_config()


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        await update.message.reply_text("无权限访问。")
        return
    await update.message.reply_text(
        "EC2 Bot Secure Edition\n"
        "/dashboard 全局概览(含详情)\n/status 状态\n/control 控制\n/searchip IP搜索主机\n/searchhost 主机名搜索\n/check 巡检\n/log 审计\n/audit 我的审计\n/whoami 查看权限\n/cpualarm CPU告警开关(admin)\n/account_list 账户列表(admin)\n/account_show 别名(admin)\n/account_reload 重载配置(admin)\n/account_add 别名(admin私聊)\n/account_delete 别名(admin)\n/instance_add 别名(admin私聊)\n/instance_delete 别名 实例ID(admin)\n/account_import 别名(admin,自动扫描导入)\n/secret_add 前缀(admin私聊)\n/secret_status 前缀(admin)\n/secret_cancel 取消录入"
    )


async def cmd_whoami(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"用户ID: {uid}\n角色: {role_of(uid)}\n时间: {now_local()}")


async def cmd_cpualarm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("仅 admin 可执行")
        return
    enabled = CFG.get("monitor", {}).get("enable_cpu_alarm", True)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("开启 CPU 告警", callback_data="cpualarm_on"), InlineKeyboardButton("关闭 CPU 告警", callback_data="cpualarm_off")]
    ])
    await update.message.reply_text(f"当前 CPU 告警状态: {'开启' if enabled else '关闭'}", reply_markup=kb)


async def cmd_account_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("仅 admin 可查看账户配置")
        return
    accounts = CFG_MGR.list_accounts()
    if not accounts:
        await update.message.reply_text("当前没有配置账户")
        return
    import unicodedata

    def _dw(s):
        return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)

    def _pad(s, w):
        return s + ' ' * (w - _dw(s))

    accounts = sorted(accounts, key=lambda a: a.get('alias', ''))
    total_instances = sum(len(a.get('instances', [])) for a in accounts)
    # 计算各列最大宽度
    aliases = [a.get('alias', '?') for a in accounts]
    regions = [a.get('region', '?') for a in accounts]
    col_no = len(str(len(accounts)))
    col_alias = max(_dw(a) for a in aliases) + 1
    col_region = max(len(r) for r in regions) + 1
    lines = [
        f"  账户总览  {len(accounts)} 个账户 / {total_instances} 台实例",
        "-" * (col_no + col_alias + col_region + 12),
        f"{_pad('#', col_no+1)}{_pad('账户', col_alias)}{_pad('Region', col_region)}{'实例':>4}",
        "-" * (col_no + col_alias + col_region + 12),
    ]
    for idx, acc in enumerate(accounts, 1):
        alias = acc.get('alias', '?')
        region = acc.get('region', '?')
        count = len(acc.get('instances', []))
        no = _pad(str(idx), col_no + 1)
        lines.append(f"{no}{_pad(alias, col_alias)}{_pad(region, col_region)}{count:>4}")
    lines.append("-" * (col_no + col_alias + col_region + 12))
    lines.append(now_local())
    await update.message.reply_text(f"<pre>{chr(10).join(lines)}</pre>", parse_mode="HTML")


async def cmd_account_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("仅 admin 可查看账户详情")
        return
    if not ctx.args:
        await update.message.reply_text("用法: /account_show <alias>")
        return
    alias = " ".join(ctx.args).strip()
    accounts = CFG_MGR.list_accounts()
    acc = next((a for a in accounts if a.get('alias') == alias), None)
    if not acc:
        await update.message.reply_text(f"账户不存在: {alias}")
        return
    instances = acc.get('instances', [])
    preview_limit = 20
    lines = [
        f"账户: {acc.get('alias')}",
        f"region: {acc.get('region')}",
        f"environment: {acc.get('environment')}",
        f"auth: {acc.get('auth')}",
        f"access_key_env: {acc.get('access_key_env','')}",
        f"secret_key_env: {acc.get('secret_key_env','')}",
        f"session_token_env: {acc.get('session_token_env','')}",
        f"instances: {len(instances)}",
        "",
    ]
    for inst in instances[:preview_limit]:
        lines.append(f"- {inst.get('name')} | {inst.get('id')} | role={inst.get('role')} | critical={inst.get('critical')}")
    remain = len(instances) - min(len(instances), preview_limit)
    if remain > 0:
        lines.append(f"... 其余 {remain} 台已省略")
    await update.message.reply_text("\n".join(lines))


async def cmd_account_reload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("仅 admin 可执行配置重载")
        return
    reload_runtime_config()
    await update.message.reply_text(f"配置已重载\n账户数: {len(ACCOUNTS)}\n时间: {now_local()}")


async def cmd_secret_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("仅 admin 可执行")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("安全限制：只允许在私聊中录入凭据")
        return
    if not ctx.args:
        await update.message.reply_text("用法: /secret_add AWS_ACC_NEW")
        return
    prefix = ctx.args[0].strip().upper()
    SECRET_SESSIONS[uid] = {"step": "ak", "prefix": prefix}
    await update.message.reply_text(
        f"开始录入凭据前缀: {prefix}\n请发送 Access Key。\n可随时发送 /secret_cancel 取消。"
    )


async def cmd_secret_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    SECRET_SESSIONS.pop(uid, None)
    CONFIG_SESSIONS.pop(uid, None)
    await update.message.reply_text("已取消当前录入/配置会话。")


async def cmd_secret_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("仅 admin 可执行")
        return
    if not ctx.args:
        await update.message.reply_text("用法: /secret_status AWS_ACC_NEW")
        return
    prefix = ctx.args[0].strip().upper()
    exists = SECRET_MGR.exists_prefix(prefix)
    await update.message.reply_text(f"前缀 {prefix}: {'已存在' if exists else '不存在'}")


async def cmd_account_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("仅 admin 可执行")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("安全限制：请在私聊中执行 /account_add")
        return
    if not ctx.args:
        await update.message.reply_text("用法: /account_add <alias>")
        return
    alias = " ".join(ctx.args).strip()
    CONFIG_SESSIONS[uid] = {"type": "account_add", "step": "region", "data": {"alias": alias}}
    await update.message.reply_text(f"开始创建账户: {alias}\n请输入 region，例如 ap-southeast-1")


async def cmd_account_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("仅 admin 可执行")
        return
    if not ctx.args:
        await update.message.reply_text("用法: /account_delete <alias>")
        return
    alias = " ".join(ctx.args).strip()
    try:
        CFG_MGR.delete_account(alias)
        AUDIT.write(uid, alias, "-", "-", "account_delete", "OK", "")
        await update.message.reply_text(f"账户已删除: {alias}\n请执行 /account_reload 生效。")
    except Exception as e:
        AUDIT.write(uid, alias, "-", "-", "account_delete", "FAIL", str(e))
        await update.message.reply_text(f"删除失败: {e}")


async def cmd_instance_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("仅 admin 可执行")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("安全限制：请在私聊中执行 /instance_add")
        return
    if not ctx.args:
        await update.message.reply_text("用法: /instance_add <alias>")
        return
    alias = " ".join(ctx.args).strip()
    CONFIG_SESSIONS[uid] = {"type": "instance_add", "step": "id", "data": {"alias": alias}}
    await update.message.reply_text(f"开始给账户 {alias} 新增实例\n请输入 instance_id")


async def cmd_instance_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("仅 admin 可执行")
        return
    if len(ctx.args) < 2:
        await update.message.reply_text("用法: /instance_delete <alias> <instance_id>")
        return
    alias = ctx.args[0]
    instance_id = ctx.args[1]
    try:
        CFG_MGR.delete_instance(alias, instance_id)
        AUDIT.write(uid, alias, "-", instance_id, "instance_delete", "OK", "")
        await update.message.reply_text(f"实例已删除: {alias} / {instance_id}\n请执行 /account_reload 生效。")
    except Exception as e:
        AUDIT.write(uid, alias, "-", instance_id, "instance_delete", "FAIL", str(e))
        await update.message.reply_text(f"删除失败: {e}")


async def cmd_account_import(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """自动扫描 AWS 账户下所有实例并导入 config.yaml"""
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("仅 admin 可执行")
        return
    if not ctx.args:
        await update.message.reply_text("用法: /account_import <alias>\n将自动扫描该账户下所有 EC2 实例并导入（保守模式：仅 status/detail 权限）")
        return
    alias = " ".join(ctx.args).strip()
    accounts = CFG_MGR.list_accounts()
    acc = next((a for a in accounts if a.get('alias') == alias), None)
    if not acc:
        await update.message.reply_text(f"账户不存在: {alias}\n请先用 /account_add 创建账户")
        return
    wait_msg = await show_processing(update, f"正在扫描 {alias} 下所有 EC2 实例...")

    def _scan():
        return aws.discover_all_instances(acc)

    try:
        discovered = await asyncio.to_thread(_scan)
    except Exception as e:
        if wait_msg:
            try:
                await wait_msg.delete()
            except Exception:
                pass
        await update.message.reply_text(f"扫描失败: {e}")
        return

    existing_ids = {i.get("id") for i in acc.get("instances", [])}
    new_count = 0
    for inst in discovered:
        if inst["id"] in existing_ids:
            continue
        try:
            CFG_MGR.add_instance(alias, {
                "id": inst["id"],
                "name": inst["name"],
                "role": "app",
                "critical": False,
                "allow_actions": ["status", "detail"],
            })
            new_count += 1
        except Exception:
            pass

    if wait_msg:
        try:
            await wait_msg.delete()
        except Exception:
            pass

    AUDIT.write(uid, alias, "-", "-", "account_import", "OK", f"scanned={len(discovered)} new={new_count}")
    lines = [
        f"扫描完成: {alias}",
        f"发现实例: {len(discovered)} 个",
        f"新增导入: {new_count} 个",
        f"已存在跳过: {len(discovered) - new_count} 个",
        f"默认策略: 保守模式（仅 status/detail）",
        "",
        "请执行 /account_reload 生效。",
    ]
    await update.message.reply_text("\n".join(lines))


def dashboard_home_text():
    total = sum(len(a.get("instances", [])) for a in ACCOUNTS)
    return f"EC2 管理面板\n{now_local()}\n共 {len(ACCOUNTS)} 个账户 / {total} 台实例\n\n请选择账户："


def dashboard_acc_kb():
    sorted_idx = sorted(range(len(ACCOUNTS)), key=lambda i: ACCOUNTS[i].get("alias", ""))
    rows = [[InlineKeyboardButton(ACCOUNTS[i]["alias"], callback_data=f"dash_{i}_0")] for i in sorted_idx]
    return InlineKeyboardMarkup(rows)


def build_dashboard_account_page(acc_idx: int, page: int = 0, page_size: int = 10):
    acc = ACCOUNTS[acc_idx]
    rs = get_account_status_live(acc_idx)
    total = len(rs)
    start = page * page_size
    end = min(start + page_size, total)
    acc_running = sum(1 for i in rs if i.get("state") == "running")
    acc_stopped = sum(1 for i in rs if i.get("state") == "stopped")
    pages = (total + page_size - 1) // page_size
    lines = [
        f"{acc['alias']}",
        f"R:{acc_running} S:{acc_stopped} T:{total}  |  {page+1}/{pages}",
    ]
    rows = []
    for i in rs[start:end]:
        badge = state_badge(i.get('state', 'unknown')) if i.get("ok") else "[ERR]"
        name = i.get('cfg_name', '?')
        ip = i.get('ip', 'N/A') if i.get("ok") else (i.get('error') or '?')[:20]
        lines.append(f"{badge} {name}  {ip}")
        if i.get("ok"):
            rows.append([InlineKeyboardButton(
                f"{badge} {name}",
                callback_data=f"detinst_{acc_idx}_{i['id']}"
            )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"dash_{acc_idx}_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"dash_{acc_idx}_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 返回总览", callback_data="dash_back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def cmd_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    await update.message.reply_text(dashboard_home_text(), reply_markup=dashboard_acc_kb())


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    await update.message.reply_text("请选择账户：", reply_markup=acc_kb("sts_"))



async def cmd_control(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    await update.message.reply_text("请选择账户：", reply_markup=acc_kb("ctl_"))


def _search_ip_parallel(needle: str):
    """并发搜索所有账户，找到即返回"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _search_one(acc_idx):
        rs = get_account_status_live(acc_idx)
        for i in rs:
            if needle in i.get('public_ips', []) or needle in i.get('private_ips', []) \
               or i.get('ip') == needle or i.get('private_ip') == needle:
                return (acc_idx, ACCOUNTS[acc_idx], i)
        return None

    with ThreadPoolExecutor(max_workers=len(ACCOUNTS)) as pool:
        futures = {pool.submit(_search_one, idx): idx for idx in range(len(ACCOUNTS))}
        for f in as_completed(futures):
            result = f.result()
            if result:
                return result
    return None


def _ip_cache_valid():
    """检查 IP 缓存是否在 TTL 内"""
    return FAST_INDEX['ip'] and (time.time() - FAST_INDEX['ts'] < FAST_INDEX_TTL)


def _fmt_ips(i):
    """格式化所有 IP，多个用逗号分隔"""
    pub = i.get('public_ips', [])
    priv = i.get('private_ips', [])
    pub_text = ", ".join(pub) if pub else i.get('ip', 'N/A')
    priv_text = ", ".join(priv) if priv else i.get('private_ip', 'N/A')
    return pub_text, priv_text


def _format_ip_result(acc_idx, acc, i):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("详情", callback_data=f"detinst_{acc_idx}_{i['id']}"),
         InlineKeyboardButton("控制", callback_data=f"ctlinst_{acc_idx}_{i['id']}")],
    ])
    pub_text, priv_text = _fmt_ips(i)
    text = (
        f"{acc['alias']} / {i['cfg_name']}\n"
        f"ID: {i['id']}\n"
        f"状态: {i.get('state','unknown')}\n"
        f"公网IP: {pub_text}\n"
        f"内网IP: {priv_text}"
    )
    return text, kb


def _ip_select_kb(needle: str):
    sorted_idx = sorted(range(len(ACCOUNTS)), key=lambda i: ACCOUNTS[i].get("alias", ""))
    rows = [[InlineKeyboardButton(ACCOUNTS[i]["alias"], callback_data=f"ipacc_{i}_{needle}")] for i in sorted_idx]
    rows.append([InlineKeyboardButton("不确定 (搜全部)", callback_data=f"ipall_{needle}")])
    return InlineKeyboardMarkup(rows)


async def cmd_searchip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    if not ctx.args:
        await update.message.reply_text("用法: /searchip <公网IP或内网IP>")
        return
    needle = ctx.args[0].strip()
    # 缓存有效且命中 → 秒回
    if _ip_cache_valid():
        cached = FAST_INDEX['ip'].get(needle)
        if cached:
            text, kb = _format_ip_result(*cached)
            await update.message.reply_text(text, reply_markup=kb)
            return
    # 缓存无效或未命中 → 选账户
    await update.message.reply_text(f"查找 {needle}\n请选择所在账户：", reply_markup=_ip_select_kb(needle))


async def cmd_searchhost(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    if not ctx.args:
        await update.message.reply_text("用法: /searchhost <关键词>")
        return
    wait_msg = await show_processing(update, "主机搜索处理中，请稍候...")
    keyword = " ".join(ctx.args).strip().lower()

    def _search():
        found_map = {}
        for acc_idx, acc in enumerate(ACCOUNTS):
            rs = get_account_status_live(acc_idx)
            for i in rs:
                if keyword in (i.get('cfg_name', '') or '').lower() or keyword in (i.get('aws_name', '') or '').lower():
                    found_map[i['id']] = (acc_idx, acc, i)
        return list(found_map.values())

    found = await asyncio.to_thread(_search)
    if not found:
        if wait_msg:
            try:
                await wait_msg.delete()
            except Exception:
                pass
        await update.message.reply_text(f"未找到主机: {keyword}")
        return

    if len(found) == 1:
        acc_idx, acc, i = found[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("详情", callback_data=f"detinst_{acc_idx}_{i['id']}"), InlineKeyboardButton("控制", callback_data=f"ctlinst_{acc_idx}_{i['id']}")],
        ])
        if wait_msg:
            try:
                await wait_msg.delete()
            except Exception:
                pass
        await update.message.reply_text(
            f"账户: {acc['alias']}\n实例: {i['cfg_name']}\nID: {i['id']}\n状态: {i.get('state','unknown')}\n公网IP: {_fmt_ips(i)[0]}\n内网IP: {_fmt_ips(i)[1]}",
            reply_markup=kb,
        )
        return

    lines = [f"找到 {len(found)} 台匹配主机："]
    for _, acc, i in found[:10]:
        lines.append(
            f"账户: {acc['alias']} | 实例: {i['cfg_name']} | ID: {i['id']} | 状态: {i.get('state','unknown')} | 公网: {_fmt_ips(i)[0]} | 内网: {_fmt_ips(i)[1]}"
        )
    if len(found) > 10:
        lines.append(f"... 其余 {len(found)-10} 台已省略")
    if wait_msg:
        try:
            await wait_msg.delete()
        except Exception:
            pass
    await update.message.reply_text("\n".join(lines))


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    loading = await show_processing(update, "正在巡检所有实例，请稍候...")
    all_results = await asyncio.to_thread(lambda: [aws.get_all_instances_status(acc, TZ) for acc in ACCOUNTS])
    issues = []
    for acc, rs in zip(ACCOUNTS, all_results):
        for i in rs:
            if not i.get("ok"):
                issues.append(f"ERR {acc['alias']} {i['cfg_name']} {i.get('error','?')}")
            elif i.get("state") not in ("running", "stopped"):
                issues.append(f"WARN {acc['alias']} {i['cfg_name']} {i['state']}")
    try:
        await loading.delete()
    except Exception:
        pass
    await update.message.reply_text("巡检完成\n" + ("\n".join(issues) if issues else "全部正常"))


async def cmd_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    rows = AUDIT.recent(20)
    if not rows:
        await update.message.reply_text("暂无审计记录")
        return
    text = ["最近审计记录:"]
    for ts, uid, acc, inst, action, result in rows:
        text.append(f"{ts} | {uid} | {acc} | {inst} | {action} | {result}")
    await update.message.reply_text("\n".join(text))


async def cmd_audit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    uid = update.effective_user.id
    rows = AUDIT.recent_by_user(uid, 20)
    if not rows:
        await update.message.reply_text("你暂无审计记录")
        return
    text = ["你的最近审计记录:"]
    for ts, _uid, acc, inst, action, result in rows:
        text.append(f"{ts} | {acc} | {inst} | {action} | {result}")
    await update.message.reply_text("\n".join(text))


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    uid = q.from_user.id
    data = q.data
    if uid not in ALLOWED:
        await q.edit_message_text("无权限")
        return

    # IP 搜索：选择单个账户
    if data.startswith("ipacc_"):
        parts = data.split("_", 2)
        acc_idx = int(parts[1])
        needle = parts[2]
        await q.edit_message_text(f"正在查找 {needle} ...")

        def _search_one(idx, ip):
            rs = get_account_status_live(idx)
            for i in rs:
                if ip in i.get('public_ips', []) or ip in i.get('private_ips', []) \
                   or i.get('ip') == ip or i.get('private_ip') == ip:
                    return (idx, ACCOUNTS[idx], i)
            return None

        found = await asyncio.to_thread(_search_one, acc_idx, needle)
        if found:
            text, kb = _format_ip_result(*found)
            await q.edit_message_text(text, reply_markup=kb)
        else:
            retry_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("搜索全部账户", callback_data=f"ipall_{needle}")],
                [InlineKeyboardButton("重新选择账户", callback_data=f"ipreselect_{needle}")],
            ])
            await q.edit_message_text(
                f"在 {ACCOUNTS[acc_idx]['alias']} 中未找到: {needle}",
                reply_markup=retry_kb
            )
        return

    # IP 搜索：不确定，搜全部
    if data.startswith("ipall_"):
        needle = data.split("_", 1)[1]
        await q.edit_message_text(f"正在搜索全部账户 {needle} ...")
        found = await asyncio.to_thread(_search_ip_parallel, needle)
        if found:
            text, kb = _format_ip_result(*found)
            await q.edit_message_text(text, reply_markup=kb)
        else:
            await q.edit_message_text(f"全部账户中未找到: {needle}")
        return

    # IP 搜索：重新选择账户
    if data.startswith("ipreselect_"):
        needle = data.split("_", 1)[1]
        await q.edit_message_text(f"查找 {needle}\n请选择所在账户：", reply_markup=_ip_select_kb(needle))
        return

    if data in ("cpualarm_on", "cpualarm_off"):
        if uid not in ADMINS:
            await q.edit_message_text("仅 admin 可执行")
            return
        enabled = data == "cpualarm_on"
        await asyncio.to_thread(set_cpu_alarm_enabled, enabled)
        await q.edit_message_text(f"CPU 告警已{'开启' if enabled else '关闭'}\n时间: {now_local()}")
        return

    if data == "dash_back":
        await q.edit_message_text(dashboard_home_text(), reply_markup=dashboard_acc_kb())
        return

    if data.startswith("dash_"):
        _, acc_idx, page = data.split("_", 2)
        await q.edit_message_text("正在加载实例列表...")
        text, kb = await asyncio.to_thread(build_dashboard_account_page, int(acc_idx), int(page))
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data == "sts_back":
        await q.edit_message_text("请选择账户：", reply_markup=acc_kb("sts_"))
        return

    if data.startswith("sts_") and data.count("_") == 1:
        acc_idx = int(data.split("_")[1])
        await q.edit_message_text("状态加载中，请稍候...")
        text, kb = await asyncio.to_thread(build_status_page, acc_idx, 0)
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("stspage_"):
        _, acc_idx, page = data.split("_", 2)
        await q.edit_message_text("状态翻页加载中，请稍候...")
        text, kb = await asyncio.to_thread(build_status_page, int(acc_idx), int(page))
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("detinst_"):
        _, acc_idx, inst_id = data.split("_", 2)
        acc_idx = int(acc_idx)
        acc, inst = find_inst(acc_idx, inst_id)
        await q.edit_message_text(f"正在查询 {inst['name']} 详情...")
        info = await asyncio.to_thread(aws.get_instance_status, acc, inst_id, TZ)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("控制", callback_data=f"ctlinst_{acc_idx}_{inst_id}")],
            [InlineKeyboardButton("🔙 返回列表", callback_data=f"dash_{acc_idx}_0")],
        ])
        await q.edit_message_text(
            f"{acc['alias']} / {inst['name']}\n"
            f"ID: {inst_id}\n"
            f"状态: {info.get('state','unknown')}\n"
            f"公网IP: {_fmt_ips(info)[0]}\n"
            f"内网IP: {_fmt_ips(info)[1]}\n"
            f"规格: {info.get('type','N/A')}\n"
            f"启动: {info.get('launch','N/A')}\n"
            f"运行: {info.get('uptime_h','N/A')}h\n"
            f"日费: ${info.get('cost_day', 0)}",
            reply_markup=kb,
        )
        return

    if data.startswith("ctl_") and data.count("_") == 1:
        acc_idx = int(data.split("_")[1])
        kb, total, start, end = paged_inst_kb(acc_idx, "ctl", 0)
        await q.edit_message_text(f"请选择实例\n第 1 页 | {start+1}-{end}/{total}", reply_markup=kb)
        return

    if data.startswith("ctlpage_"):
        _, acc_idx, page = data.split("_", 2)
        page = int(page)
        kb, total, start, end = paged_inst_kb(int(acc_idx), "ctl", page)
        await q.edit_message_text(f"请选择实例\n第 {page+1} 页 | {start+1}-{end}/{total}", reply_markup=kb)
        return

    if data.startswith("ctlinst_"):
        _, acc_idx, inst_id = data.split("_", 2)
        acc, inst = find_inst(int(acc_idx), inst_id)
        rows = [
            [InlineKeyboardButton("Reboot", callback_data=f"op_reboot_{acc_idx}_{inst_id}")],
            [InlineKeyboardButton("Start", callback_data=f"op_start_{acc_idx}_{inst_id}"), InlineKeyboardButton("Stop", callback_data=f"op_stop_{acc_idx}_{inst_id}")],
            [InlineKeyboardButton("返回详情", callback_data=f"detinst_{acc_idx}_{inst_id}")],
        ]
        await q.edit_message_text(f"实例: {inst['name']}\n请选择操作", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("op_"):
        _, action, acc_idx, inst_id = data.split("_", 3)
        acc, inst = find_inst(int(acc_idx), inst_id)
        if not can_operate(uid, action):
            await q.edit_message_text("权限不足")
            return
        reason = denied_policy(acc, inst, action)
        if reason:
            await q.edit_message_text(reason)
            return
        await q.edit_message_text(
            f"二次确认\n实例: {inst['name']}\n动作: {action}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("确认", callback_data=f"confirm_{action}_{acc_idx}_{inst_id}")]])
        )
        return

    if data.startswith("confirm_"):
        _, action, acc_idx, inst_id = data.split("_", 3)
        acc, inst = find_inst(int(acc_idx), inst_id)
        try:
            if action == "reboot":
                aws.reboot_instance(acc, inst_id)
            elif action == "start":
                aws.start_instance(acc, inst_id)
            elif action == "stop":
                aws.stop_instance(acc, inst_id)
            invalidate_account_cache(int(acc_idx))
            AUDIT.write(uid, acc['alias'], inst['name'], inst_id, action, "OK", "")
            await q.edit_message_text(f"操作成功: {inst['name']} -> {action}")
            await send_operation_notice(uid, acc, inst, inst_id, action, "成功")
        except RuntimeError as e:
            AUDIT.write(uid, acc['alias'], inst['name'], inst_id, action, "FAIL", str(e))
            await q.edit_message_text(f"操作失败: {e}")
            await send_operation_notice(uid, acc, inst, inst_id, action, "失败", str(e))


async def do_search_ip(update: Update, needle: str):
    if _ip_cache_valid():
        cached = FAST_INDEX['ip'].get(needle)
        if cached:
            text, kb = _format_ip_result(*cached)
            await update.message.reply_text(text, reply_markup=kb)
            return
    await update.message.reply_text(f"查找 {needle}\n请选择所在账户：", reply_markup=_ip_select_kb(needle))


async def handle_private_secret_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    # 0) 简写触发：ip / 查IP / host
    if auth(update):
        parts = text.split()
        if len(parts) >= 2 and (parts[0].lower() == "ip" or parts[0] in ("查IP", "查ip", "搜IP", "搜ip")):
            await do_search_ip(update, parts[1].strip())
            return
        if len(parts) >= 2 and (parts[0].lower() == "host" or parts[0] in ("查主机", "搜主机", "查机器", "搜机器")):
            ctx.args = parts[1:]
            await cmd_searchhost(update, ctx)
            return

    if update.effective_chat.type != "private":
        return

    # 1) 凭据录入会话
    session = SECRET_SESSIONS.get(uid)
    if session:
        prefix = session["prefix"]
        if session["step"] == "ak":
            session["ak"] = text
            session["step"] = "sk"
            await update.message.reply_text("已收到 Access Key，请发送 Secret Key。")
            return
        if session["step"] == "sk":
            session["sk"] = text
            session["step"] = "token"
            await update.message.reply_text("已收到 Secret Key，如有 Session Token 请发送；没有请发送空行或任意字符例如 none。")
            return
        if session["step"] == "token":
            token = "" if text.lower() in ("none", "null", "-") else text
            SECRET_MGR.upsert(f"{prefix}_KEY", session["ak"])
            SECRET_MGR.upsert(f"{prefix}_SECRET", session["sk"])
            SECRET_MGR.upsert(f"{prefix}_TOKEN", token)
            SECRET_SESSIONS.pop(uid, None)
            await update.message.reply_text(
                f"凭据已写入本地 .env：{prefix}_KEY / {prefix}_SECRET / {prefix}_TOKEN\n"
                f"建议尽快轮换凭据，并执行 /account_reload。"
            )
            return

    # 2) 动态配置会话
    cs = CONFIG_SESSIONS.get(uid)
    if not cs:
        return

    if cs["type"] == "account_add":
        data = cs["data"]
        if cs["step"] == "region":
            data["region"] = text
            cs["step"] = "environment"
            await update.message.reply_text("请输入 environment（prod/test/dev）")
            return
        if cs["step"] == "environment":
            data["environment"] = text
            cs["step"] = "access_key_env"
            await update.message.reply_text("请输入 access_key_env，例如 AWS_ACC_NEW_KEY")
            return
        if cs["step"] == "access_key_env":
            data["access_key_env"] = text
            cs["step"] = "secret_key_env"
            await update.message.reply_text("请输入 secret_key_env，例如 AWS_ACC_NEW_SECRET")
            return
        if cs["step"] == "secret_key_env":
            data["secret_key_env"] = text
            cs["step"] = "session_token_env"
            await update.message.reply_text("请输入 session_token_env，没有可输入 none")
            return
        if cs["step"] == "session_token_env":
            data["session_token_env"] = "" if text.lower() in ("none", "null", "-") else text
            account = {
                "alias": data["alias"],
                "region": data["region"],
                "auth": "access_key",
                "access_key_env": data["access_key_env"],
                "secret_key_env": data["secret_key_env"],
                "session_token_env": data["session_token_env"],
                "environment": data["environment"],
                "instances": [],
            }
            try:
                CFG_MGR.add_account(account)
                AUDIT.write(uid, data['alias'], '-', '-', 'account_add', 'OK', '')
                await update.message.reply_text(f"账户已写入 config.yaml：{data['alias']}\n请先用 /secret_add 写入凭据，再执行 /account_reload。")
            except Exception as e:
                AUDIT.write(uid, data['alias'], '-', '-', 'account_add', 'FAIL', str(e))
                await update.message.reply_text(f"账户写入失败: {e}")
            CONFIG_SESSIONS.pop(uid, None)
            return

    if cs["type"] == "instance_add":
        data = cs["data"]
        if cs["step"] == "id":
            data["id"] = text
            cs["step"] = "name"
            await update.message.reply_text("请输入实例名称")
            return
        if cs["step"] == "name":
            data["name"] = text
            cs["step"] = "role"
            await update.message.reply_text("请输入 role，例如 app/ops/k8s")
            return
        if cs["step"] == "role":
            data["role"] = text
            cs["step"] = "critical"
            await update.message.reply_text("请输入 critical（true/false）")
            return
        if cs["step"] == "critical":
            data["critical"] = text.lower() == 'true'
            cs["step"] = "allow_actions"
            await update.message.reply_text("请输入 allow_actions，逗号分隔，例如 status,detail,reboot")
            return
        if cs["step"] == "allow_actions":
            data["allow_actions"] = [i.strip() for i in text.split(',') if i.strip()]
            inst = {
                "id": data["id"],
                "name": data["name"],
                "role": data["role"],
                "critical": data["critical"],
                "allow_actions": data["allow_actions"],
            }
            try:
                CFG_MGR.add_instance(data['alias'], inst)
                AUDIT.write(uid, data['alias'], data['name'], data['id'], 'instance_add', 'OK', '')
                await update.message.reply_text(f"实例已写入 config.yaml：{data['alias']} / {data['name']}\n请执行 /account_reload 生效。")
            except Exception as e:
                AUDIT.write(uid, data['alias'], data.get('name','-'), data.get('id','-'), 'instance_add', 'FAIL', str(e))
                await update.message.reply_text(f"实例写入失败: {e}")
            CONFIG_SESSIONS.pop(uid, None)
            return


async def show_processing(update: Update, text: str = "处理中，请稍候..."):
    try:
        await update.effective_chat.send_action(ChatAction.TYPING)
    except Exception:
        pass
    try:
        return await update.message.reply_text(text)
    except Exception:
        return None


async def push_notify(chat_ids: list, text: str):
    app = push_notify._app
    for cid in chat_ids:
        try:
            await app.bot.send_message(chat_id=cid, text=text, parse_mode="Markdown")
        except Exception as e:
            log.warning("推送失败 %s: %s", cid, e)


async def send_operation_notice(uid: int, acc: dict, inst: dict, inst_id: str, action: str, result: str, detail: str = ""):
    app = push_notify._app
    user_label = str(uid)
    info = await asyncio.to_thread(aws.get_instance_status, acc, inst_id, TZ)
    text = (
        f"[实例操作通知]\n"
        f"操作人: {user_label}\n"
        f"时间: {now_local()}\n"
        f"来源: Telegram\n"
        f"账户: {acc['alias']}\n"
        f"实例: {inst['name']}\n"
        f"ID: {inst_id}\n"
        f"动作: {action}\n"
        f"结果: {result}\n"
        f"公网IP: {_fmt_ips(info)[0]}\n"
        f"内网IP: {_fmt_ips(info)[1]}"
    )
    if detail:
        text += f"\n说明: {detail}"
    for cid in CFG.get('telegram', {}).get('alert_chat_ids', []):
        try:
            await app.bot.send_message(chat_id=cid, text=text)
        except Exception as e:
            log.warning("操作通知发送失败 %s: %s", cid, e)


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("cpualarm", cmd_cpualarm))
    app.add_handler(CommandHandler("account_list", cmd_account_list))
    app.add_handler(CommandHandler("account_show", cmd_account_show))
    app.add_handler(CommandHandler("account_reload", cmd_account_reload))
    app.add_handler(CommandHandler("account_add", cmd_account_add))
    app.add_handler(CommandHandler("account_delete", cmd_account_delete))
    app.add_handler(CommandHandler("instance_add", cmd_instance_add))
    app.add_handler(CommandHandler("instance_delete", cmd_instance_delete))
    app.add_handler(CommandHandler("account_import", cmd_account_import))
    app.add_handler(CommandHandler("secret_add", cmd_secret_add))
    app.add_handler(CommandHandler("secret_cancel", cmd_secret_cancel))
    app.add_handler(CommandHandler("secret_status", cmd_secret_status))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(CommandHandler("control", cmd_control))
    app.add_handler(CommandHandler("searchip", cmd_searchip))
    app.add_handler(CommandHandler("searchhost", cmd_searchhost))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_private_secret_input))
    push_notify._app = app
    monitor = MonitorEngine(CFG, push_notify)
    runtime_refs = {"monitor_task": None}

    async def post_init(application):
        runtime_refs["monitor_task"] = asyncio.create_task(monitor.run())
        asyncio.create_task(_async_warmup_ip_index())
        log.info("后台巡检已启动，IP索引预热中")

    async def _async_warmup_ip_index():
        """异步预热IP索引，不阻塞事件循环"""
        try:
            await asyncio.to_thread(rebuild_fast_ip_index)
            log.info("IP索引预热完成")
        except Exception as e:
            log.error("IP索引预热失败: %s", e)

    async def post_shutdown(application):
        monitor.stop()
        task = runtime_refs.get("monitor_task")
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        log.info("后台巡检已停止")

    app.post_init = post_init
    app.post_shutdown = post_shutdown
    log.info("EC2 Bot Secure Edition 启动")
    app.run_polling(drop_pending_updates=False)
