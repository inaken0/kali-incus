"""インスタンス情報の取得と管理判定。"""

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from . import incus
from .common import KaliError
from .config import MANAGED_KEY, PROVISIONED_KEY, SSH_AGENT_KEY, Config

Devices = dict[str, dict[str, str]]


@dataclass
class Instance:
    name: str
    status: str
    config: dict[str, str] = field(default_factory=dict)
    devices: Devices = field(default_factory=dict)

    @property
    def managed(self) -> bool:
        return self.config.get(MANAGED_KEY) == "true"

    @property
    def provisioned(self) -> bool:
        return self.config.get(PROVISIONED_KEY) == "true"

    @property
    def ssh_agent(self) -> bool:
        return self.config.get(SSH_AGENT_KEY) == "true"

    @property
    def running(self) -> bool:
        return self.status == "Running"


def from_api(obj: dict[str, Any]) -> Instance:
    return Instance(
        name=obj.get("name", ""),
        status=obj.get("status", ""),
        config=dict(obj.get("config") or {}),
        devices={k: dict(v) for k, v in (obj.get("devices") or {}).items()},
    )


def load(target: str) -> Instance | None:
    """状態とデバイスを query 1 回で取得する。存在しなければ None。"""
    try:
        return from_api(incus.query(f"/1.0/instances/{quote(target)}"))
    except incus.IncusError as e:
        if "not found" in e.stderr.lower():
            return None
        raise


def list_all() -> list[Instance]:
    return [from_api(o) for o in incus.query("/1.0/instances?recursion=1")]


def list_managed() -> list[Instance]:
    return sorted((i for i in list_all() if i.managed), key=lambda i: i.name)


def require(cfg: Config) -> Instance:
    """作成済みで管理対象のインスタンスを返す。なければエラー。"""
    inst = load(cfg.target)
    if inst is None:
        raise KaliError(f"コンテナ '{cfg.target}' がまだありません。`{cfg.up_hint()}` で作成してください")
    check_managed(inst)
    return inst


def check_managed(inst: Instance) -> None:
    if not inst.managed:
        raise KaliError(
            f"'{inst.name}' は kali-incus が作成したコンテナではないため操作しません（{MANAGED_KEY}=true がありません）"
        )
