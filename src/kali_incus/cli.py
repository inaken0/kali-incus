"""コマンドライン引数の解析と各サブコマンドへの振り分け。"""

import argparse
import sys
from collections.abc import Callable, Sequence

from . import __version__, forward, lifecycle, mounts, prereq, snapshot, ssh_agent, tools
from . import config as config_mod
from . import run as run_mod
from .common import KaliError
from .config import Config
from .incus import IncusError

USAGE = """\
使い方: kali [-t TARGET] <コマンド> [引数...]

  target は -t > 環境変数 KALI_TARGET > 既定値 kali の順で決まります（-t はコマンドの前に置く）。

ライフサイクル:
  up                 コンテナを作成して起動（既にあれば起動のみ、起動済みなら何もしない）
  down [-f]          停止（-f: 強制停止）
  reload [-f]        停止して起動し直す
  destroy [-y] [--purge-image]
                     削除（-y: 確認を省略 / --purge-image: 使われていないイメージも削除）
  list               管理しているコンテナの一覧

ツールの導入:
  provision [パッケージ...]
                     Kali のツールとシェル環境を導入（省略時は kali-linux-default。何度でも実行可）

実行:
  run [--root] [-e NAME=値]... <cmd> [args...]
                     コンテナ内ユーザーとしてコマンドを実行（停止中なら起動、未作成なら作成）。
                     -e で環境変数を渡せる（何度でも指定可。既定値より優先。`--` でコマンドと区切れる）。
                     --root で root として実行（GUI アプリも使える。例: kali run --root zenmap）
  shell [--root] [-e NAME=値]...
                     コンテナ内ユーザー（--root なら root）のログインシェルに接続

ホストとの共有:
  mount -s <ホスト側> -d <Kali側> [-r]
                     ホストのパスを永続的にマウント（-r: 読み取り専用）
  umount <Kali側>    マウントを解除
  mount ls           マウントの一覧
  forward <ホスト側ポート> <Kali側ポート> [--proto tcp|udp] [--bind ADDR]
                     ホストのポートを Kali へ転送（既定の待ち受けは 127.0.0.1）
  unforward <ホスト側ポート> [--proto tcp|udp]
  forward ls         転送の一覧

  ssh-agent [on|off] ホストの ssh-agent (SSH_AUTH_SOCK) をコンテナへ渡す設定（引数なしで現在の状態を表示）

スナップショット:
  snapshot [名前]    作成（省略時は snap-日時）
  snapshot ls | snapshot rm <名前>
  restore <名前> [-y]  スナップショットの状態へ戻す（マウント設定も戻る）

  help, -h, --help   この表示
  --version          バージョン

環境変数: KALI_TARGET, KALI_IMAGE, KALI_UID, KALI_USER, KALI_LANG
"""


def _parser(prog: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"kali {prog}", add_help=True)


def _no_args(sub: str, args: Sequence[str]) -> None:
    _parser(sub).parse_args(list(args))


def _up(cfg: Config, args: Sequence[str]) -> int:
    _no_args("up", args)
    return lifecycle.cmd_up(cfg)


def _down(cfg: Config, args: Sequence[str]) -> int:
    p = _parser("down")
    p.add_argument("-f", "--force", action="store_true", help="強制停止")
    return lifecycle.cmd_down(cfg, p.parse_args(list(args)).force)


def _reload(cfg: Config, args: Sequence[str]) -> int:
    p = _parser("reload")
    p.add_argument("-f", "--force", action="store_true", help="強制停止")
    return lifecycle.cmd_reload(cfg, p.parse_args(list(args)).force)


def _destroy(cfg: Config, args: Sequence[str]) -> int:
    p = _parser("destroy")
    p.add_argument("-y", "--yes", action="store_true", help="確認を省略")
    p.add_argument("--purge-image", action="store_true", help="使われていないイメージも削除")
    a = p.parse_args(list(args))
    return lifecycle.cmd_destroy(cfg, a.yes, a.purge_image)


def _list(cfg: Config, args: Sequence[str]) -> int:
    _no_args("list", args)
    return lifecycle.cmd_list(cfg)


def _provision(cfg: Config, args: Sequence[str]) -> int:
    p = _parser("provision")
    p.add_argument("packages", nargs="*", help="メタパッケージ名（省略時は kali-linux-default）")
    return tools.cmd_provision(cfg, p.parse_args(list(args)).packages)


def _run(cfg: Config, args: Sequence[str]) -> int:
    opts = run_mod.split_run_options(args)
    return run_mod.cmd_run(cfg, opts.rest, opts.env, opts.root)


def _shell(cfg: Config, args: Sequence[str]) -> int:
    opts = run_mod.split_run_options(args)
    if opts.rest:
        raise KaliError(f"shell に余分な引数があります: {' '.join(opts.rest)}（環境変数は -e NAME=値）")
    return run_mod.cmd_shell(cfg, opts.env, opts.root)


def _mount(cfg: Config, args: Sequence[str]) -> int:
    if list(args) == ["ls"]:
        return mounts.cmd_mount_ls(cfg)
    p = _parser("mount")
    p.add_argument("-s", "--source", required=True, help="ホスト側のパス")
    p.add_argument("-d", "--dest", required=True, help="Kali 側の絶対パス")
    p.add_argument("-r", "--readonly", action="store_true", help="読み取り専用")
    a = p.parse_args(list(args))
    return mounts.cmd_mount(cfg, a.source, a.dest, a.readonly)


def _umount(cfg: Config, args: Sequence[str]) -> int:
    p = _parser("umount")
    p.add_argument("dest", help="Kali 側のパス")
    return mounts.cmd_umount(cfg, p.parse_args(list(args)).dest)


def _ssh_agent(cfg: Config, args: Sequence[str]) -> int:
    p = _parser("ssh-agent")
    p.add_argument("mode", nargs="?", choices=["on", "off"], help="省略すると現在の状態を表示")
    return ssh_agent.cmd_ssh_agent(cfg, p.parse_args(list(args)).mode)


def _forward(cfg: Config, args: Sequence[str]) -> int:
    if list(args) == ["ls"]:
        return forward.cmd_forward_ls(cfg)
    p = _parser("forward")
    p.add_argument("host_port", help="ホスト側のポート")
    p.add_argument("kali_port", help="Kali 側のポート")
    p.add_argument("--proto", choices=["tcp", "udp"], default="tcp")
    p.add_argument("--bind", default=forward.DEFAULT_BIND, help="ホスト側の待ち受けアドレス")
    a = p.parse_args(list(args))
    return forward.cmd_forward(cfg, a.host_port, a.kali_port, a.proto, a.bind)


def _unforward(cfg: Config, args: Sequence[str]) -> int:
    p = _parser("unforward")
    p.add_argument("host_port", help="ホスト側のポート")
    p.add_argument("--proto", choices=["tcp", "udp"], default=None)
    a = p.parse_args(list(args))
    return forward.cmd_unforward(cfg, a.host_port, a.proto)


def _snapshot(cfg: Config, args: Sequence[str]) -> int:
    rest = list(args)
    if rest == ["ls"]:
        return snapshot.cmd_snapshot_ls(cfg)
    if rest[:1] == ["rm"]:
        p = _parser("snapshot rm")
        p.add_argument("name")
        return snapshot.cmd_snapshot_rm(cfg, p.parse_args(rest[1:]).name)
    p = _parser("snapshot")
    p.add_argument("name", nargs="?")
    return snapshot.cmd_snapshot(cfg, p.parse_args(rest).name)


def _restore(cfg: Config, args: Sequence[str]) -> int:
    p = _parser("restore")
    p.add_argument("name")
    p.add_argument("-y", "--yes", action="store_true", help="確認を省略")
    a = p.parse_args(list(args))
    return snapshot.cmd_restore(cfg, a.name, a.yes)


COMMANDS: dict[str, Callable[[Config, Sequence[str]], int]] = {
    "up": _up, "down": _down, "reload": _reload, "destroy": _destroy, "list": _list,
    "provision": _provision, "run": _run, "shell": _shell, "mount": _mount, "umount": _umount,
    "ssh-agent": _ssh_agent, "forward": _forward, "unforward": _unforward, "snapshot": _snapshot, "restore": _restore,
}  # fmt: skip


def split_global(argv: Sequence[str]) -> tuple[str | None, list[str]]:
    """サブコマンドより前のグローバルオプション（-t）を取り出す。残りを返す。"""
    target: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-t", "--target"):
            if i + 1 >= len(argv):
                raise KaliError(f"{a} に値がありません")
            target = argv[i + 1]
            i += 2
        elif a.startswith("--target="):
            target = a.split("=", 1)[1]
            i += 1
        else:
            break
    return target, list(argv[i:])


def main(argv: Sequence[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        target, rest = split_global(argv)
        if not rest or rest[0] in ("help", "-h", "--help"):
            print(USAGE, end="")
            return 0
        if rest[0] == "--version":
            print(f"kali-incus {__version__}")
            return 0
        handler = COMMANDS.get(rest[0])
        if handler is None:
            print(USAGE, end="", file=sys.stderr)
            raise KaliError(f"不明なコマンド: {rest[0]}")
        cfg = config_mod.load(target)
        prereq.require_incus()
        return handler(cfg, rest[1:])
    except IncusError as e:
        hint = prereq.diagnose(e.stderr)
        print(f"kali: {e}", file=sys.stderr)
        if hint:
            print(f"kali: {hint}", file=sys.stderr)
        return 1
    except KaliError as e:
        print(f"kali: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
