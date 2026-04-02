#!/usr/bin/env python3
import os
from pathlib import Path
import yaml


class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)

    def load(self):
        return yaml.safe_load(self.config_path.read_text(encoding="utf-8"))

    def save(self, cfg: dict):
        self.config_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def list_accounts(self):
        cfg = self.load()
        return cfg.get("aws_accounts", [])

    def add_account(self, account: dict):
        cfg = self.load()
        cfg.setdefault("aws_accounts", [])
        exists = any(a.get("alias") == account.get("alias") for a in cfg["aws_accounts"])
        if exists:
            raise ValueError(f"账户已存在: {account.get('alias')}")
        cfg["aws_accounts"].append(account)
        self.save(cfg)

    def delete_account(self, alias: str):
        cfg = self.load()
        old = len(cfg.get("aws_accounts", []))
        cfg["aws_accounts"] = [a for a in cfg.get("aws_accounts", []) if a.get("alias") != alias]
        if len(cfg["aws_accounts"]) == old:
            raise ValueError(f"账户不存在: {alias}")
        self.save(cfg)

    def add_instance(self, alias: str, inst: dict):
        cfg = self.load()
        for acc in cfg.get("aws_accounts", []):
            if acc.get("alias") == alias:
                acc.setdefault("instances", [])
                if any(i.get("id") == inst.get("id") for i in acc["instances"]):
                    raise ValueError(f"实例已存在: {inst.get('id')}")
                acc["instances"].append(inst)
                self.save(cfg)
                return
        raise ValueError(f"账户不存在: {alias}")

    def delete_instance(self, alias: str, instance_id: str):
        cfg = self.load()
        for acc in cfg.get("aws_accounts", []):
            if acc.get("alias") == alias:
                old = len(acc.get("instances", []))
                acc["instances"] = [i for i in acc.get("instances", []) if i.get("id") != instance_id]
                if len(acc["instances"]) == old:
                    raise ValueError(f"实例不存在: {instance_id}")
                self.save(cfg)
                return
        raise ValueError(f"账户不存在: {alias}")
