import json
import os
import re
from pathlib import Path
import secrets
import stat
import tomllib
from dataclasses import dataclass


class ConfigError(Exception):
    def __init__(self):
        super().__init__("Invalid local configuration.")


def private_file(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ConfigError()
            data = stream.read(16385)
            if len(data) > 16384:
                raise ConfigError()
            return data
    except (OSError, ValueError):
        raise ConfigError() from None


def root_path(root=None):
    root = Path(root or Path.cwd()).resolve()
    try:
        if tomllib.loads((root / "pyproject.toml").read_text())["project"]["name"] != "langdock-support-lab":
            raise ConfigError()
    except (OSError, ValueError, KeyError):
        raise ConfigError() from None
    return root


def local_dir(root):
    local = root / ".local"
    try:
        info = local.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ConfigError()
    except OSError:
        raise ConfigError() from None
    return local


def initialize(root):
    root = root_path(root)
    local = root / ".local"
    local.mkdir(mode=0o700, exist_ok=True)
    local_dir(root)
    target = local / "credentials.json"
    with open(target, "x", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)) as stream:
        json.dump({"schema_version": 1, **{f"{role}_token": secrets.token_urlsafe(32) for role in ("reader", "operator", "admin")}}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    from .storage import Storage
    Storage(local / "state.sqlite3").initialize()
    return {"created": [".local/credentials.json", ".local/state.sqlite3"], "roles": ["reader", "operator", "admin"]}


@dataclass
class Config:
    root: Path
    tokens: dict
    mode: str = "offline"
    port: int = 8765
    provider_key: str | None = None
    agent_id: str | None = None
    deadline: float = 25

    @property
    def secrets(self):
        return [*self.tokens.values(), self.provider_key]

    @classmethod
    def load(cls, root=None, credentials_file=None):
        root = root_path(root)
        local = local_dir(root)
        try:
            data = json.loads(private_file(Path(credentials_file) if credentials_file else local / "credentials.json"))
            tokens = {role: data[f"{role}_token"] for role in ("reader", "operator", "admin")}
            if data["schema_version"] != 1 or any(not isinstance(v, str) or re.fullmatch(r"[A-Za-z0-9_-]{43,}", v) is None for v in tokens.values()) or len(set(tokens.values())) != 3:
                raise ConfigError()
            mode = os.environ.get("LAB_MODE", "offline")
            port = int(os.environ.get("LAB_PORT", "8765"))
            if mode not in ("offline", "live") or not 1024 <= port <= 65535 or os.environ.get("LAB_HOST", "127.0.0.1") != "127.0.0.1":
                raise ConfigError()
            key, agent = None, None
            if mode == "live":
                if os.environ.get("LAB_LIVE_SCOPE_CONFIRMED") != "synthetic-only":
                    raise ConfigError()
                key = private_file(Path(os.environ["LANGDOCK_API_KEY_FILE"])).decode("utf-8").removesuffix("\n")
                agent = os.environ["LANGDOCK_AGENT_ID"]
                if not 16 <= len(key) <= 4096 or any(c in key for c in "\r\n\0") or not agent.strip():
                    raise ConfigError()
            return cls(root, tokens, mode, port, key, agent)
        except (KeyError, TypeError, ValueError, OSError, UnicodeError):
            raise ConfigError() from None
