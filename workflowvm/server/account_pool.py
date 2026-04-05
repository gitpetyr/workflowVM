import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


class NoAccountAvailable(Exception):
    pass


class AccountPool:
    def __init__(self, config_path: str):
        self._config_path = config_path
        self._mtime: float = 0.0
        self._accounts: list[dict] = []
        self._active: dict[str, int] = {}  # username → count
        self._server_config: dict = {}
        self._load()

    def _load(self):
        with open(self._config_path) as f:
            cfg = yaml.safe_load(f)
        self._mtime = os.path.getmtime(self._config_path)
        self._server_config = cfg.get("server", {})
        new_accounts = cfg.get("accounts", [])
        # 保留已有 active 计数，新账号从0开始
        existing = {a["username"] for a in self._accounts}
        for acc in new_accounts:
            if acc["username"] not in existing:
                self._active.setdefault(acc["username"], 0)
        self._accounts = new_accounts

    def reload_if_changed(self):
        try:
            mtime = os.path.getmtime(self._config_path)
        except OSError:
            return
        if mtime > self._mtime:
            self._load()

    @property
    def server_config(self) -> dict:
        return self._server_config

    def pick(self) -> dict:
        """选取 active_count 最小且未满的账号。"""
        self.reload_if_changed()
        candidates = [
            acc for acc in self._accounts
            if self._active.get(acc["username"], 0) < acc["max_concurrent"]
        ]
        if not candidates:
            raise NoAccountAvailable("所有账号已达并发上限")
        # 最少使用策略
        chosen = min(candidates, key=lambda a: self._active.get(a["username"], 0))
        self._active[chosen["username"]] = self._active.get(chosen["username"], 0) + 1
        return chosen

    def release(self, username: str):
        if self._active.get(username, 0) > 0:
            self._active[username] -= 1
