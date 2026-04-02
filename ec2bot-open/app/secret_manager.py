#!/usr/bin/env python3
from pathlib import Path


class SecretEnvManager:
    def __init__(self, env_path: str):
        self.env_path = Path(env_path)

    def _read_lines(self):
        if not self.env_path.exists():
            return []
        return self.env_path.read_text(encoding="utf-8").splitlines()

    def _write_lines(self, lines):
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def upsert(self, key: str, value: str):
        lines = self._read_lines()
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"{key}={value}")
        self._write_lines(new_lines)

    def exists_prefix(self, prefix: str) -> bool:
        lines = self._read_lines()
        return any(line.startswith(prefix + "_") for line in lines)
