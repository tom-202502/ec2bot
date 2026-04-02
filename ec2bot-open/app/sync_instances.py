#!/usr/bin/env python3
"""
EC2 实例自动同步脚本
- 扫描所有 AWS 账户，发现新增实例自动导入 config.yaml
- 清理已 terminated 的实例
- 通过 Telegram 发送变更通知
- 支持手动执行和 cron 定时运行

用法:
  python3 sync_instances.py                  # 扫描并同步
  python3 sync_instances.py --dry-run        # 仅预览，不修改
  python3 sync_instances.py --account SF-5生产环境  # 仅同步指定账户
"""
import os
import sys
import json
import logging
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import boto3
import yaml
import requests
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("sync-instances")

CFG_PATH = os.getenv("EC2BOT_CONFIG", "/opt/ec2bot/config/config.yaml")
ENV_PATH = os.getenv("EC2BOT_ENV", "/opt/ec2bot/config/.env")
TZ = "Asia/Shanghai"

# ---------- 凭证加载 ----------

def load_env(env_path: str) -> dict:
    """从 .env 文件加载环境变量"""
    envs = {}
    if not os.path.exists(env_path):
        return envs
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                envs[k.strip()] = v.strip().strip('"').strip("'")
    return envs


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(path: str, cfg: dict):
    # 备份原文件
    backup = path + f".bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        with open(backup, "w", encoding="utf-8") as f:
            f.write(content)
        log.info(f"配置已备份: {backup}")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


# ---------- AWS 操作 ----------

def get_session(account: dict, envs: dict) -> boto3.session.Session:
    """根据账户配置创建 boto3 session"""
    auth = account.get("auth", "instance_role")
    region = account["region"]

    if auth == "access_key":
        ak_env = account.get("access_key_env", "AWS_ACCESS_KEY_ID")
        sk_env = account.get("secret_key_env", "AWS_SECRET_ACCESS_KEY")
        st_env = account.get("session_token_env", "")

        ak = envs.get(ak_env, os.environ.get(ak_env, ""))
        sk = envs.get(sk_env, os.environ.get(sk_env, ""))
        st = envs.get(st_env, os.environ.get(st_env, "")) if st_env else None

        kwargs = {
            "aws_access_key_id": ak,
            "aws_secret_access_key": sk,
            "region_name": region,
        }
        if st:
            kwargs["aws_session_token"] = st
        return boto3.session.Session(**kwargs)
    else:
        return boto3.session.Session(region_name=region)


def discover_instances(session: boto3.session.Session) -> list:
    """扫描账户下所有非 terminated 的 EC2 实例"""
    ec2 = session.client("ec2")
    instances = []
    paginator = ec2.get_paginator("describe_instances")
    # 排除已终止的实例
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped", "stopping", "pending"]}]
    ):
        for rs in page.get("Reservations", []):
            for inst in rs.get("Instances", []):
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                instances.append({
                    "id": inst["InstanceId"],
                    "name": tags.get("Name", inst["InstanceId"]),
                    "type": inst["InstanceType"],
                    "state": inst["State"]["Name"],
                    "launch_time": inst.get("LaunchTime", "").isoformat() if inst.get("LaunchTime") else "",
                })
    return instances


def check_instance_exists(session: boto3.session.Session, instance_id: str) -> str:
    """检查实例是否存在，返回状态或 'not_found'"""
    ec2 = session.client("ec2")
    try:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        for rs in resp.get("Reservations", []):
            for inst in rs.get("Instances", []):
                return inst["State"]["Name"]
        return "not_found"
    except ClientError as e:
        if "InvalidInstanceID" in str(e):
            return "not_found"
        raise


# ---------- 同步逻辑 ----------

def sync_account(cfg: dict, account: dict, envs: dict, dry_run: bool = False) -> dict:
    """
    同步单个账户，返回变更摘要:
    {
        "alias": str,
        "added": [{"id": ..., "name": ...}, ...],
        "removed": [{"id": ..., "name": ..., "reason": ...}, ...],
        "errors": [str, ...],
    }
    """
    alias = account.get("alias", "unknown")
    result = {"alias": alias, "added": [], "removed": [], "errors": []}

    try:
        session = get_session(account, envs)
    except Exception as e:
        result["errors"].append(f"创建 AWS 会话失败: {e}")
        return result

    # 1. 扫描 AWS 实际实例
    try:
        aws_instances = discover_instances(session)
    except Exception as e:
        result["errors"].append(f"扫描实例失败: {e}")
        return result

    aws_ids = {inst["id"] for inst in aws_instances}
    cfg_instances = account.get("instances", [])
    cfg_ids = {inst["id"] for inst in cfg_instances}

    # 2. 发现新增实例（AWS 有但 config 没有）
    for inst in aws_instances:
        if inst["id"] not in cfg_ids:
            new_entry = {
                "id": inst["id"],
                "name": inst["name"],
                "role": "app",
                "critical": False,
                "allow_actions": ["status", "detail", "reboot", "start", "stop"],
            }
            result["added"].append({
                "id": inst["id"],
                "name": inst["name"],
                "type": inst["type"],
                "state": inst["state"],
            })
            if not dry_run:
                cfg_instances.append(new_entry)

    # 3. 发现已终止实例（config 有但 AWS 中已 terminated/不存在）
    for inst in list(cfg_instances):
        if inst["id"] not in aws_ids:
            # 二次确认：调用 API 检查是否真的已终止
            try:
                state = check_instance_exists(session, inst["id"])
            except Exception:
                state = "unknown"

            if state in ("terminated", "not_found"):
                result["removed"].append({
                    "id": inst["id"],
                    "name": inst.get("name", ""),
                    "reason": state,
                })
                if not dry_run:
                    cfg_instances.remove(inst)
            # 如果状态是 unknown 或其他，保留不动

    if not dry_run:
        account["instances"] = cfg_instances

    return result


# ---------- Telegram 通知 ----------

def send_telegram_notify(bot_token: str, chat_ids: list, message: str):
    """发送 Telegram 通知"""
    if not bot_token or not chat_ids:
        log.warning("Telegram 未配置，跳过通知")
        return
    for chat_id in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }, timeout=10)
            if resp.status_code == 200:
                log.info(f"Telegram 通知已发送: chat_id={chat_id}")
            else:
                log.warning(f"Telegram 发送失败: {resp.text}")
        except Exception as e:
            log.warning(f"Telegram 发送异常: {e}")


def format_report(results: list) -> str:
    """格式化同步报告"""
    now = datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"<b>🔄 EC2 实例同步报告</b>", f"<i>{now}</i>", ""]

    has_changes = False
    for r in results:
        if r["added"] or r["removed"] or r["errors"]:
            has_changes = True
            lines.append(f"<b>📋 {r['alias']}</b>")

            if r["added"]:
                lines.append(f"  ➕ 新增 {len(r['added'])} 台:")
                for inst in r["added"]:
                    lines.append(f"    • {inst['name']} ({inst['id']}) [{inst['type']}] {inst['state']}")

            if r["removed"]:
                lines.append(f"  ➖ 清理 {len(r['removed'])} 台:")
                for inst in r["removed"]:
                    lines.append(f"    • {inst['name']} ({inst['id']}) [{inst['reason']}]")

            if r["errors"]:
                lines.append(f"  ⚠️ 错误:")
                for err in r["errors"]:
                    lines.append(f"    • {err}")
            lines.append("")

    if not has_changes:
        lines.append("✅ 所有账户实例配置与 AWS 一致，无变更。")

    return "\n".join(lines)


# ---------- 主流程 ----------

def main():
    parser = argparse.ArgumentParser(description="EC2 实例自动同步")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更，不修改配置")
    parser.add_argument("--account", type=str, help="仅同步指定账户（alias）")
    parser.add_argument("--no-notify", action="store_true", help="不发送 Telegram 通知")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理已终止的实例")
    parser.add_argument("--config", type=str, default=CFG_PATH, help="配置文件路径")
    parser.add_argument("--env", type=str, default=ENV_PATH, help="环境变量文件路径")
    args = parser.parse_args()

    log.info(f"EC2 实例同步开始 {'(DRY RUN)' if args.dry_run else ''}")

    # 加载配置和环境变量
    envs = load_env(args.env)
    # 将 .env 变量注入 os.environ（供 boto3 使用）
    for k, v in envs.items():
        os.environ.setdefault(k, v)

    cfg = load_config(args.config)
    accounts = cfg.get("aws_accounts", [])

    if args.account:
        accounts = [a for a in accounts if a.get("alias") == args.account]
        if not accounts:
            log.error(f"账户不存在: {args.account}")
            sys.exit(1)

    # 逐个账户同步
    results = []
    for acc in accounts:
        alias = acc.get("alias", "unknown")
        log.info(f"正在扫描: {alias} ({acc.get('region', 'N/A')})")
        r = sync_account(cfg, acc, envs, dry_run=args.dry_run)

        if args.no_cleanup:
            r["removed"] = []

        results.append(r)
        if r["added"]:
            log.info(f"  新增: {len(r['added'])} 台")
        if r["removed"]:
            log.info(f"  清理: {len(r['removed'])} 台")
        if r["errors"]:
            log.warning(f"  错误: {r['errors']}")

    # 保存配置
    has_changes = any(r["added"] or r["removed"] for r in results)
    if has_changes and not args.dry_run:
        save_config(args.config, cfg)
        log.info("配置已更新")

    # 生成报告
    report = format_report(results)
    plain = report.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    try:
        print("\n" + plain)
    except UnicodeEncodeError:
        print("\n" + plain.encode("utf-8", errors="replace").decode("utf-8"))

    # 发送 Telegram 通知（仅有变更时）
    if has_changes and not args.dry_run and not args.no_notify:
        bot_token = envs.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        alert_ids = cfg.get("telegram", {}).get("alert_chat_ids", [])
        send_telegram_notify(bot_token, alert_ids, report)

    # 提示 reload
    if has_changes and not args.dry_run:
        log.info("⚠️  配置已更新，请在 Telegram 执行 /account_reload 或重启 Bot 生效")

    log.info("同步完成")


if __name__ == "__main__":
    main()
