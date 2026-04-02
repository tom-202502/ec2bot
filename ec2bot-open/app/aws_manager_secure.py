#!/usr/bin/env python3
import os
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

import boto3
import yaml
from botocore.exceptions import ClientError, NoCredentialsError

log = logging.getLogger(__name__)

_PRICE_MAP = {
    "t3.micro": 0.0116, "t3.small": 0.0232, "t3.medium": 0.0464,
    "c5.large": 0.096, "c5.xlarge": 0.192, "c5.2xlarge": 0.384,
    "m5.large": 0.107, "m5.xlarge": 0.214, "m5.2xlarge": 0.428,
}


def load_config(path: str = "/opt/ec2bot/config/config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def local_now_str(tz_name: str = "Asia/Shanghai") -> str:
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S")


_SESSION_CACHE = {}


def _session(account: dict):
    cache_key = account.get("alias", "") + "|" + account["region"]
    cached = _SESSION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    auth = account.get("auth", "instance_role")
    region = account["region"]
    if auth == "instance_role" or os.getenv("AWS_USE_INSTANCE_ROLE", "true").lower() == "true":
        sess = boto3.session.Session(region_name=region)
        _SESSION_CACHE[cache_key] = sess
        return sess

    # 多账户独立凭据模式：每个账户指定各自的环境变量名
    ak_env = account.get("access_key_env", "AWS_ACCESS_KEY_ID")
    sk_env = account.get("secret_key_env", "AWS_SECRET_ACCESS_KEY")
    st_env = account.get("session_token_env", "AWS_SESSION_TOKEN")

    access_key = os.getenv(ak_env, "")
    secret_key = os.getenv(sk_env, "")
    session_token = os.getenv(st_env, "")

    if not access_key or not secret_key:
        raise RuntimeError(f"账户 {account.get('alias','?')} 未配置环境变量凭据: {ak_env}/{sk_env}")

    sess = boto3.session.Session(
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token,
    )
    _SESSION_CACHE[cache_key] = sess
    return sess


def _ec2(account: dict):
    return _session(account).client("ec2")


def _cw(account: dict):
    return _session(account).client("cloudwatch")


def _wrap(func):
    def inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except NoCredentialsError:
            raise RuntimeError("AWS 凭据无效或未配置")
        except ClientError as e:
            code = e.response["Error"].get("Code", "Unknown")
            msg = e.response["Error"].get("Message", "")
            raise RuntimeError(f"[{code}] {msg}")
        except Exception as e:
            raise RuntimeError(str(e))
    return inner


def _collect_all_ips(inst: dict):
    """从实例的所有网络接口中提取全部公网/内网 IP"""
    public_ips, private_ips = [], []
    for eni in inst.get("NetworkInterfaces", []):
        for addr in eni.get("PrivateIpAddresses", []):
            pip = addr.get("PrivateIpAddress")
            if pip and pip not in private_ips:
                private_ips.append(pip)
            assoc = addr.get("Association", {})
            pub = assoc.get("PublicIp")
            if pub and pub not in public_ips:
                public_ips.append(pub)
    # 兜底：如果 NetworkInterfaces 为空，用顶层字段
    if not public_ips and inst.get("PublicIpAddress"):
        public_ips.append(inst["PublicIpAddress"])
    if not private_ips and inst.get("PrivateIpAddress"):
        private_ips.append(inst["PrivateIpAddress"])
    return public_ips, private_ips


@_wrap
def get_instance_status(account: dict, instance_id: str, tz_name: str = "Asia/Shanghai") -> dict:
    ec2 = _ec2(account)
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    rs = resp.get("Reservations", [])
    if not rs:
        raise RuntimeError("实例不存在")
    inst = rs[0]["Instances"][0]
    tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
    itype = inst["InstanceType"]
    launch_dt = inst["LaunchTime"]
    now_utc = datetime.now(timezone.utc)
    uptime_h = (now_utc - launch_dt).total_seconds() / 3600
    local_launch = launch_dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S")
    price_h = _PRICE_MAP.get(itype, 0)
    public_ips, private_ips = _collect_all_ips(inst)
    return {
        "state": inst["State"]["Name"],
        "ip": inst.get("PublicIpAddress", "N/A"),
        "private_ip": inst.get("PrivateIpAddress", "N/A"),
        "public_ips": public_ips,
        "private_ips": private_ips,
        "type": itype,
        "launch": local_launch,
        "uptime_h": round(uptime_h, 1),
        "az": inst["Placement"]["AvailabilityZone"],
        "aws_name": tags.get("Name", ""),
        "cost_day": round(price_h * 24, 3) if price_h else 0,
    }


def get_all_instances_status(account: dict, tz_name: str = "Asia/Shanghai") -> list:
    cfg_instances = account.get("instances", [])
    if not cfg_instances:
        return []
    try:
        ec2 = _ec2(account)
        ids = [i["id"] for i in cfg_instances]
        resp = ec2.describe_instances(InstanceIds=ids)
        mapping = {}
        for rs in resp.get("Reservations", []):
            for inst in rs.get("Instances", []):
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                itype = inst["InstanceType"]
                launch_dt = inst["LaunchTime"]
                now_utc = datetime.now(timezone.utc)
                uptime_h = (now_utc - launch_dt).total_seconds() / 3600
                local_launch = launch_dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S")
                price_h = _PRICE_MAP.get(itype, 0)
                public_ips, private_ips = _collect_all_ips(inst)
                mapping[inst["InstanceId"]] = {
                    "state": inst["State"]["Name"],
                    "ip": inst.get("PublicIpAddress", "N/A"),
                    "private_ip": inst.get("PrivateIpAddress", "N/A"),
                    "public_ips": public_ips,
                    "private_ips": private_ips,
                    "type": itype,
                    "launch": local_launch,
                    "uptime_h": round(uptime_h, 1),
                    "az": inst["Placement"]["AvailabilityZone"],
                    "aws_name": tags.get("Name", ""),
                    "cost_day": round(price_h * 24, 3) if price_h else 0,
                }
        out = []
        for inst in cfg_instances:
            iid = inst["id"]
            item = {"cfg_name": inst["name"], "id": iid, "ok": False}
            if iid in mapping:
                item.update(mapping[iid])
                item["ok"] = True
            else:
                item["error"] = "实例不存在或无权限"
            out.append(item)
        return out
    except Exception as e:
        err = str(e)
        return [{"cfg_name": inst["name"], "id": inst["id"], "ok": False, "error": err} for inst in cfg_instances]


def get_cpu_utilization(account: dict, instance_id: str, period: int = 300, points: int = 12) -> Optional[list]:
    try:
        cw = _cw(account)
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=period * points)
        resp = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=end,
            Period=period,
            Statistics=["Average"],
        )
        pts = sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
        return [round(p["Average"], 1) for p in pts] if pts else None
    except Exception as e:
        log.warning("CloudWatch 查询失败 %s: %s", instance_id, e)
        return None


def get_cpu_utilization_detail(account: dict, instance_id: str, period: int = 300, points: int = 12) -> dict:
    try:
        cw = _cw(account)
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=period * points)
        resp = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=end,
            Period=period,
            Statistics=["Average"],
        )
        pts = sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
        values = [round(p["Average"], 1) for p in pts] if pts else []
        return {"ok": True, "values": values, "error": ""}
    except Exception as e:
        msg = str(e)
        log.warning("CloudWatch 查询失败 %s: %s", instance_id, msg)
        return {"ok": False, "values": [], "error": msg}


def _allowed(inst_cfg: dict, action: str):
    return action in inst_cfg.get("allow_actions", ["status", "detail", "reboot", "start", "stop"])


@_wrap
def discover_all_instances(account: dict) -> list:
    """扫描账户下所有 EC2 实例，返回实例列表（不需要预先知道 instance id）"""
    ec2 = _ec2(account)
    instances = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for rs in page.get("Reservations", []):
            for inst in rs.get("Instances", []):
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                public_ips, private_ips = _collect_all_ips(inst)
                instances.append({
                    "id": inst["InstanceId"],
                    "name": tags.get("Name", inst["InstanceId"]),
                    "type": inst["InstanceType"],
                    "state": inst["State"]["Name"],
                    "ip": inst.get("PublicIpAddress", "N/A"),
                    "private_ip": inst.get("PrivateIpAddress", "N/A"),
                    "public_ips": public_ips,
                    "private_ips": private_ips,
                    "az": inst["Placement"]["AvailabilityZone"],
                })
    return instances


@_wrap
def reboot_instance(account: dict, instance_id: str):
    _ec2(account).reboot_instances(InstanceIds=[instance_id])


@_wrap
def start_instance(account: dict, instance_id: str):
    _ec2(account).start_instances(InstanceIds=[instance_id])


@_wrap
def stop_instance(account: dict, instance_id: str):
    _ec2(account).stop_instances(InstanceIds=[instance_id])
