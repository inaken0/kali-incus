"""kali forward / unforward: ホストのポートを Kali へ転送する（Incus の proxy デバイス）。"""

from dataclasses import dataclass

from . import incus
from .common import KaliError, format_table, info
from .config import Config
from .instance import Devices, require

FWD_PREFIX = "fwd-"
DEFAULT_BIND = "127.0.0.1"


@dataclass(frozen=True)
class Forward:
    name: str
    proto: str
    listen: str
    connect: str


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise KaliError(f"ポート番号が整数ではありません: {value}") from None
    if not 1 <= port <= 65535:
        raise KaliError(f"ポート番号は 1〜65535 で指定してください: {value}")
    return port


def forward_name(proto: str, host_port: int) -> str:
    return f"{FWD_PREFIX}{proto}-{host_port}"


def _endpoint(proto: str, addr: str, port: int) -> str:
    host = f"[{addr}]" if ":" in addr else addr  # IPv6
    return f"{proto}:{host}:{port}"


def list_forwards(devices: Devices) -> list[Forward]:
    out = []
    for name, d in devices.items():
        if d.get("type") == "proxy" and name.startswith(FWD_PREFIX):
            listen = d.get("listen", "")
            out.append(Forward(name, listen.split(":", 1)[0], listen, d.get("connect", "")))
    return sorted(out, key=lambda f: f.name)


def cmd_forward(cfg: Config, host_port: str, kali_port: str, proto: str, bind: str) -> int:
    hp, kp = parse_port(host_port), parse_port(kali_port)
    inst = require(cfg)
    name = forward_name(proto, hp)
    if name in inst.devices:
        raise KaliError(f"{proto}/{hp} は既に公開されています（kali forward ls で確認できます）")
    incus.run(
        "config", "device", "add", cfg.target, name, "proxy",
        f"listen={_endpoint(proto, bind, hp)}",
        f"connect={_endpoint(proto, '127.0.0.1', kp)}",
        "bind=host",
    )  # fmt: skip
    note = "" if inst.running else "（反映は次回の起動時です）"
    info(f"公開しました: {bind}:{hp}/{proto} -> {cfg.target}:{kp}{note}")
    if bind not in ("127.0.0.1", "::1"):
        info(f"注意: {bind} で待ち受けているため、ホスト外から到達できる可能性があります")
    return 0


def cmd_unforward(cfg: Config, host_port: str, proto: str | None) -> int:
    hp = parse_port(host_port)
    inst = require(cfg)
    names = [
        forward_name(p, hp) for p in ([proto] if proto else ["tcp", "udp"])
        if forward_name(p, hp) in inst.devices
    ]  # fmt: skip
    if not names:
        raise KaliError(f"ポート {hp} の公開はありません（kali forward ls で確認できます）")
    for name in names:
        incus.run("config", "device", "remove", cfg.target, name)
        info(f"公開を解除しました: {name}")
    return 0


def cmd_forward_ls(cfg: Config) -> int:
    inst = require(cfg)
    fwds = list_forwards(inst.devices)
    if not fwds:
        info("公開しているポートはありません")
        return 0
    rows = [["PROTO", "HOST_LISTEN", "KALI_CONNECT"]]
    rows += [[f.proto, f.listen.split(":", 1)[-1], f.connect.split(":", 1)[-1]] for f in fwds]
    print(format_table(rows))
    return 0
