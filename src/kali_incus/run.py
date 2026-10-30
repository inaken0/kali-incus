"""kali run / shell: コンテナ内ユーザーとしてコマンドを実行する。"""

import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from . import gui, incus, lifecycle, ssh_agent
from .common import KaliError, warn
from .config import SOCK_DIR, Config
from .mounts import list_mounts, map_cwd


@dataclass
class Prep:
    user: str = ""
    gid: str = ""
    home: str = ""
    shell: str = ""
    ino: str = ""
    ssh_ino: str = ""
    has_bus: bool = False


def parse_prep(out: str, uid: int) -> Prep:
    prep = Prep()
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if key == "nouser":
            raise KaliError(f"コンテナ内に UID {uid} のユーザーがいません")
        if key == "bus":
            prep.has_bus = True
        elif key in ("user", "gid", "home", "shell", "ino", "ssh_ino"):
            setattr(prep, key, value)
    if not prep.user:
        raise KaliError("コンテナ内の準備結果を読み取れませんでした")
    return prep


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_spec(spec: str) -> tuple[str, str]:
    """`NAME=値` を (NAME, 値) にする。値には = や空白を含んでよい。"""
    name, sep, value = spec.partition("=")
    if not sep or not _ENV_NAME_RE.match(name):
        raise KaliError(f"環境変数は NAME=値 の形で指定してください: {spec!r}")
    return name, value


@dataclass
class RunOptions:
    env: dict[str, str] = field(default_factory=dict)
    root: bool = False
    rest: list[str] = field(default_factory=list)


def split_run_options(args: Sequence[str]) -> RunOptions:
    """先頭にあるオプション（`-e NAME=値` / `--env NAME=値` / `--env=NAME=値` / `--root`）を取り出し、残りを返す。

    最初にオプション以外が現れた所からがコンテナ内のコマンド。`--` を挟めば -e などで始まるコマンドも実行できる。
    """
    opts = RunOptions()
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-e", "--env"):
            if i + 1 >= len(args):
                raise KaliError(f"{a} に値がありません（例: {a} NAME=値）")
            name, value = parse_env_spec(args[i + 1])
            opts.env[name] = value
            i += 2
        elif a.startswith("--env="):
            name, value = parse_env_spec(a.removeprefix("--env="))
            opts.env[name] = value
            i += 1
        elif a == "--root":
            opts.root = True
            i += 1
        else:
            break
    if args[i : i + 1] == ["--"]:
        i += 1
    opts.rest = list(args[i:])
    return opts


def _apply(plan: list[list[str]], failure: str) -> bool:
    """デバイス付け直しの incus 引数を順に実行する。失敗したら警告して False を返す。"""
    for args in plan:
        try:
            incus.run(*args)
        except incus.IncusError as e:
            warn(f"{failure}: {e.stderr}")
            return False
    return True


def _exec(cfg: Config, build_command: Callable[[Prep], list[str]], extra_env: Mapping[str, str], root: bool) -> int:
    # incus は呼び出し 3 回程度: 状態取得 → 準備(1 exec) → 本体の exec
    inst = lifecycle.ensure_running(cfg)
    env = os.environ
    use_gui = gui.has_gui_session(env)
    cookie = gui.xauth_cookie(env["DISPLAY"]) if env.get("DISPLAY") else ""
    out = incus.run(
        "exec", cfg.target, "-T", "--", "bash", "-c", lifecycle.script("prep.sh"),
        "_", str(cfg.uid), SOCK_DIR, input=cookie,
    )  # fmt: skip
    prep = parse_prep(out, cfg.uid)
    if use_gui:
        _apply(
            gui.plan_devices(cfg, inst.devices, env, prep.ino),
            "GUI 用デバイスの設定に失敗しました（GUI アプリが表示できない可能性があります）",
        )

    extra = dict(extra_env)
    if ssh_agent.should_forward(inst, env):
        plan = ssh_agent.plan_devices(cfg, inst.devices, env, prep.ssh_ino)
        if _apply(plan, "ssh-agent のデバイスの設定に失敗しました"):
            extra = {"SSH_AUTH_SOCK": ssh_agent.CONTAINER_SOCK, **extra}

    try:
        here = os.getcwd()
    except OSError:
        here = ""
    cwd = map_cwd(here, list_mounts(inst.devices)) if here else None
    envs = gui.runtime_env(cfg, prep.user, prep.home, prep.shell, prep.has_bus, env, extra, root=root)
    argv = ["exec", cfg.target, "--cwd", cwd or ("/root" if root else prep.home)]
    for item in envs:
        argv += ["--env", item]
    if root:
        argv += ["--"]  # incus exec はもともと root で実行する
    else:
        # incus exec --user は補助グループを設定しないため、root で exec して setpriv で切り替える
        argv += ["--", "setpriv", f"--reuid={cfg.uid}", f"--regid={prep.gid}", "--init-groups", "--"]
    incus.exec_replace(argv + build_command(prep))
    return 0  # exec_replace は戻らない


def cmd_run(cfg: Config, command: list[str], extra_env: Mapping[str, str] | None = None, root: bool = False) -> int:
    if not command:
        raise KaliError("実行するコマンドを指定してください（例: kali run ls -la /usr/bin/）")
    return _exec(cfg, lambda _: command, extra_env or {}, root)


# root のログインシェル（Kali の root は zsh）。パスは getent で引く
_ROOT_SHELL = ["sh", "-c", 'exec "$(getent passwd 0 | cut -d: -f7)" -l']


def cmd_shell(cfg: Config, extra_env: Mapping[str, str] | None = None, root: bool = False) -> int:
    if root:
        return _exec(cfg, lambda _: _ROOT_SHELL, extra_env or {}, True)
    return _exec(cfg, lambda prep: [prep.shell or "/bin/bash", "-l"], extra_env or {}, False)
