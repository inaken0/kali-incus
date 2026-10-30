"""bin/kali を偽 incus に向けて実行する統合テスト。"""

import os
import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _subid(kenv):
    uid, gid = os.getuid(), os.getgid()
    (kenv.tmp / "subuid").write_text(f"root:{uid}:1\n")
    (kenv.tmp / "subgid").write_text(f"root:{gid}:1\n")
    kenv.env["KALI_SUBUID_FILE"] = str(kenv.tmp / "subuid")
    kenv.env["KALI_SUBGID_FILE"] = str(kenv.tmp / "subgid")


def verbs(kenv):
    """incus 呼び出しの先頭 2 語（query や exec など）の列。"""
    return [" ".join(c[:2]) for c in kenv.calls()]


# ---- 引数解析・target の解決 ----------------------------------------------------------


def test_help_and_unknown(kenv):
    assert "使い方" in kenv.kali("help").out
    assert "使い方" in kenv.kali().out
    r = kenv.kali("frobnicate")
    assert r.rc == 1 and "不明なコマンド" in r.err


def test_target_priority_cli_over_env(kenv):
    kenv.add_instance("from-env")
    kenv.add_instance("from-cli")
    r = kenv.kali("-t", "from-cli", "down", KALI_TARGET="from-env")
    assert r.rc == 0
    assert kenv.state["instances"]["from-cli"]["status"] == "Stopped"
    assert kenv.state["instances"]["from-env"]["status"] == "Running"
    kenv.kali("down", KALI_TARGET="from-env")
    assert kenv.state["instances"]["from-env"]["status"] == "Stopped"


def test_default_target_is_kali(kenv):
    kenv.add_instance("kali")
    assert kenv.kali("down").rc == 0
    assert kenv.state["instances"]["kali"]["status"] == "Stopped"


def test_target_after_subcommand_is_not_global_option(kenv):
    kenv.add_instance("kali")
    assert kenv.kali("down", "-t", "x").rc == 2  # サブコマンドの後ろの -t は受け付けない


def test_missing_target_value_and_invalid_name(kenv):
    assert "値がありません" in kenv.kali("-t").err
    assert "不正" in kenv.kali("-t", "a_b", "up").err


# ---- up -------------------------------------------------------------------------------


def test_up_creates_and_provisions(kenv):
    r = kenv.kali("up")
    assert r.rc == 0, r.err
    inst = kenv.state["instances"]["kali"]
    assert inst["status"] == "Running"
    assert inst["config"]["user.kali-incus.managed"] == "true"
    assert inst["config"]["user.kali-incus.provisioned"] == "true"
    assert inst["config"]["raw.idmap"] == f"uid {os.getuid()} 1000\ngid {os.getgid()} 1000"
    ruleset = inst["config"]["raw.apparmor"]
    assert "signal peer=incus-**//&unconfined," in ruleset and "ptrace peer=incus-**//&unconfined," in ruleset
    # ホストのプロファイルが積み重なった相手 (firefox//&incus-…) にも signal / ptrace できる
    assert "signal peer=**//&incus-**," in ruleset and "ptrace peer=**//&incus-**," in ruleset
    assert ruleset.count("\n") == 3  # 1 行 1 ルール、4 行
    init = next(c for c in kenv.calls() if c[0] == "init")
    assert init[1:3] == ["images:kali/current/amd64", "kali"]
    if Path("/dev/dri").is_dir():
        assert inst["devices"]["gpu"]["gid"] == "44"
    # 初期設定スクリプトが標準入力で渡る
    setup = next(c for c in kenv.calls_full() if c["argv"][:2] == ["exec", "kali"] and "-s" in c["argv"])
    assert "apt-get install" in setup["stdin"] and setup["argv"][-2:] == ["1000", "kali"]


def test_up_is_idempotent(kenv):
    kenv.add_instance()
    r = kenv.kali("up")
    assert r.rc == 0 and "既に起動" in r.err
    assert verbs(kenv) == ["query /1.0/instances/kali"]


def test_up_starts_stopped_instance(kenv):
    kenv.add_instance(status="Stopped")
    assert kenv.kali("up").rc == 0
    assert kenv.state["instances"]["kali"]["status"] == "Running"
    assert not any(c[0] == "init" for c in kenv.calls())


def test_up_refuses_when_mount_source_is_gone(kenv):
    kenv.add_instance(
        status="Stopped",
        devices={"share-x": {"type": "disk", "source": str(kenv.tmp / "gone"), "path": "/w"}},
    )
    r = kenv.kali("up")
    assert r.rc == 1 and "存在しない" in r.err and str(kenv.tmp / "gone") in r.err
    assert kenv.state["instances"]["kali"]["status"] == "Stopped"
    assert not any(c[0] == "start" for c in kenv.calls())


def test_up_refuses_unmanaged(kenv):
    kenv.add_instance(config={}, status="Stopped")
    r = kenv.kali("up")
    assert r.rc == 1 and "作成したコンテナではない" in r.err


def test_up_idmap_prereq_prints_commands(kenv):
    (kenv.tmp / "subuid").write_text("")
    r = kenv.kali("up")
    assert r.rc == 1 and "/etc/subuid" in r.err and "sudo" in r.err
    assert not any(c[0] == "init" for c in kenv.calls())


def test_up_idmap_accepts_wider_range(kenv):
    (kenv.tmp / "subuid").write_text("root:0:65536\n")
    assert kenv.kali("up").rc == 0


# ---- down / reload / destroy / list ---------------------------------------------------


def test_down_and_force(kenv):
    kenv.add_instance()
    assert kenv.kali("down", "-f").rc == 0
    assert ["stop", "kali", "--force"] in kenv.calls()
    assert "既に停止" in kenv.kali("down").err


def test_reload_states(kenv):
    kenv.add_instance()
    assert kenv.kali("reload").rc == 0
    assert [v for v in verbs(kenv) if v.startswith(("stop", "start"))] == ["stop kali", "start kali"]
    kenv.add_instance(status="Stopped")
    assert kenv.kali("reload").rc == 0
    assert kenv.state["instances"]["kali"]["status"] == "Running"


def test_reload_missing_is_error(kenv):
    r = kenv.kali("reload")
    assert r.rc == 1 and "kali up" in r.err
    assert not any(c[0] == "init" for c in kenv.calls())


@pytest.mark.parametrize(("answer", "deleted"), [("n\n", False), ("\n", False), ("", False), ("y\n", True)])
def test_destroy_prompt(kenv, answer, deleted):
    kenv.add_instance()
    r = kenv.kali("destroy", input=answer)
    assert ("kali" not in kenv.state["instances"]) is deleted
    assert "[y/N]" in r.err and "'kali'" in r.err
    assert r.rc == (0 if deleted else 1)


def test_destroy_yes_stops_then_deletes(kenv):
    kenv.add_instance()
    assert kenv.kali("destroy", "-y").rc == 0
    assert [v for v in verbs(kenv) if v.split()[0] in ("stop", "delete")] == ["stop kali", "delete kali"]


def test_destroy_unmanaged_and_missing(kenv):
    kenv.add_instance(config={})
    assert kenv.kali("destroy", "-y").rc == 1
    assert "kali" in kenv.state["instances"]
    assert kenv.kali("-t", "none", "destroy", "-y").rc == 1


def test_destroy_purge_image(kenv):
    kenv.add_instance("a", config={"user.kali-incus.managed": "true", "volatile.base_image": "fp-img"})
    kenv.add_instance("b", config={"user.kali-incus.managed": "true", "volatile.base_image": "fp-img"})
    kenv.set_state(kenv.state["instances"], ["img"])
    kenv.kali("-t", "a", "destroy", "-y", "--purge-image")
    assert kenv.state["images"] == ["img"]  # b が使っているので残る
    kenv.kali("-t", "b", "destroy", "-y", "--purge-image")
    assert kenv.state["images"] == []


def test_list_only_managed_and_marks_current(kenv):
    kenv.add_instance(
        "kali", config={"user.kali-incus.managed": "true", "user.kali-incus.image": "images:kali/current/amd64"}
    )
    kenv.add_instance("other", config={})
    kenv.add_instance("pentest", status="Stopped", devices={"s": {"type": "disk", "source": "/a", "path": "/a"}})
    r = kenv.kali("list")
    assert "other" not in r.out
    kali_line = next(ln for ln in r.out.splitlines() if " kali " in ln)
    pentest = next(ln for ln in r.out.splitlines() if "pentest" in ln).split()
    assert kali_line.startswith("*") and "kali/current/amd64" in kali_line
    assert pentest[:2] == ["pentest", "Stopped"] and pentest[-1] == "1"
    assert verbs(kenv) == ["query /1.0/instances?recursion=1"]


def test_list_empty(kenv):
    assert "管理しているコンテナはありません" in kenv.kali("list").err


# ---- mount / umount -------------------------------------------------------------------


def test_mount_lifecycle(kenv):
    kenv.add_instance()
    host = kenv.tmp / "work"
    host.mkdir()
    assert kenv.kali("mount", "-s", str(host), "-d", "/work/../srv//proj").rc == 0
    devs = kenv.state["instances"]["kali"]["devices"]
    ((name, dev),) = devs.items()
    assert name.startswith("share-") and dev["path"] == "/srv/proj" and dev["readonly"] == "false"
    assert dev["source"] == str(host.resolve())
    # 二重マウントはエラー
    r = kenv.kali("mount", "-s", str(host), "-d", "/srv/proj")
    assert r.rc == 1 and "既にマウント" in r.err
    # 一覧
    ls = kenv.kali("mount", "ls").out
    assert "/srv/proj" in ls and "rw" in ls
    # 解除
    assert kenv.kali("umount", "/srv/proj").rc == 0
    assert kenv.state["instances"]["kali"]["devices"] == {}


def test_mount_readonly_and_stopped_does_not_start(kenv):
    kenv.add_instance(status="Stopped")
    host = kenv.tmp / "w"
    host.mkdir()
    r = kenv.kali("mount", "-s", str(host), "-d", "/w", "-r")
    assert r.rc == 0 and "次回の起動時" in r.err
    assert kenv.state["instances"]["kali"]["status"] == "Stopped"
    assert next(iter(kenv.state["instances"]["kali"]["devices"].values()))["readonly"] == "true"
    assert "ro" in kenv.kali("mount", "ls").out


def test_mount_errors(kenv):
    host = kenv.tmp / "w"
    host.mkdir()
    assert "kali up" in kenv.kali("mount", "-s", str(host), "-d", "/w").err  # 未作成
    kenv.add_instance()
    assert "存在しません" in kenv.kali("mount", "-s", str(kenv.tmp / "no"), "-d", "/w").err
    assert "絶対パス" in kenv.kali("mount", "-s", str(host), "-d", "rel").err
    assert "/ には" in kenv.kali("mount", "-s", str(host), "-d", "/").err
    assert kenv.kali("mount", "-s", str(host)).rc == 2


def test_umount_only_touches_kali_mounts(kenv):
    kenv.add_instance(devices={"mine": {"type": "disk", "source": "/x", "path": "/x"}})
    r = kenv.kali("umount", "/x")
    assert r.rc == 1 and "mount でマウントされた" in r.err
    assert "mine" in kenv.state["instances"]["kali"]["devices"]


# ---- run / shell ----------------------------------------------------------------------


def last_exec(kenv):
    return kenv.calls()[-1]


def test_run_call_count_and_exit_code(kenv):
    kenv.add_instance()
    r = kenv.kali("run", "ls", "-la", "/usr/bin/", FAKE_INCUS_EXIT="3")
    assert r.rc == 3
    assert verbs(kenv) == ["query /1.0/instances/kali", "exec kali", "exec kali"]
    argv = last_exec(kenv)
    tail = argv[argv.index("--") + 1 :]
    assert tail == ["setpriv", "--reuid=1000", "--regid=1000", "--init-groups", "--", "ls", "-la", "/usr/bin/"]
    assert argv[argv.index("--cwd") + 1] == "/home/kali"  # マウント外は Kali のホーム


def test_run_requires_command(kenv):
    kenv.add_instance()
    assert "コマンドを指定" in kenv.kali("run").err


def test_run_double_dash(kenv):
    kenv.add_instance()
    assert kenv.kali("run", "--", "-weird").rc == 0
    assert last_exec(kenv)[-1] == "-weird"


def test_run_cwd_maps_into_mount(kenv):
    host = kenv.tmp / "proj"
    (host / "sub").mkdir(parents=True)
    kenv.add_instance(devices={"s": {"type": "disk", "source": str(host.resolve()), "path": "/work"}})
    import subprocess
    import sys

    from conftest import KALI

    subprocess.run([sys.executable, str(KALI), "run", "pwd"], cwd=host / "sub", env=kenv.env, input="", text=True)
    argv = last_exec(kenv)
    assert argv[argv.index("--cwd") + 1] == "/work/sub"


def test_run_starts_stopped_and_creates_missing(kenv):
    kenv.add_instance(status="Stopped")
    assert kenv.kali("run", "true").rc == 0
    assert kenv.state["instances"]["kali"]["status"] == "Running"
    assert kenv.kali("-t", "fresh", "run", "true").rc == 0
    assert kenv.state["instances"]["fresh"]["config"]["user.kali-incus.provisioned"] == "true"


def test_run_without_gui_skips_gui_setup(kenv):
    kenv.add_instance()
    kenv.kali("run", "true")
    argv = last_exec(kenv)
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
    assert not any(e.startswith(("WAYLAND_DISPLAY", "DISPLAY", "MOZ_", "QT_")) for e in envs)
    assert "XDG_RUNTIME_DIR=/run/user/1000" in envs
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus" in envs
    assert not any(c[:3] == ["config", "device", "add"] for c in kenv.calls())


@pytest.fixture
def wayland(kenv):
    path = kenv.tmp / "wayland-test"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    kenv.env["WAYLAND_DISPLAY"] = str(path)
    kenv.env.pop("DISPLAY", None)
    yield path, str(os.stat(path).st_ino)
    s.close()


def test_run_attaches_wayland_when_inode_differs(kenv, wayland):
    path, ino = wayland
    kenv.add_instance()
    assert kenv.kali("run", "true", FAKE_INCUS_CT_INO="").rc == 0
    dev = kenv.state["instances"]["kali"]["devices"]["wayland"]
    assert dev["source"] == str(path) and dev["path"] == "/mnt/.kali-host/wayland"
    assert dev["optional"] == "true"
    envs = [last_exec(kenv)[i + 1] for i, a in enumerate(last_exec(kenv)) if a == "--env"]
    assert "WAYLAND_DISPLAY=wayland-0" in envs and "MOZ_ENABLE_WAYLAND=1" in envs
    assert "QT_QPA_PLATFORM=wayland;xcb" in envs and "GDK_BACKEND=wayland,x11" in envs
    assert "QT_QPA_PLATFORMTHEME=gtk3" in envs  # Qt アプリは GTK のテーマを使う


def test_run_reattaches_stale_wayland(kenv, wayland):
    path, ino = wayland
    kenv.add_instance(devices={"wayland": {"type": "disk", "source": "/old", "path": "/mnt/.kali-host/wayland"}})
    kenv.kali("run", "true", FAKE_INCUS_CT_INO="1")
    assert ["config", "device", "remove", "kali", "wayland"] in kenv.calls()
    assert kenv.state["instances"]["kali"]["devices"]["wayland"]["source"] == str(path)


def test_run_keeps_wayland_when_inode_matches(kenv, wayland):
    path, ino = wayland
    kenv.add_instance(devices={"wayland": {"type": "disk", "source": str(path), "path": "/mnt/.kali-host/wayland"}})
    kenv.kali("run", "true", FAKE_INCUS_CT_INO=ino)
    assert len(kenv.calls()) == 3
    assert not any(c[:2] == ["config", "device"] for c in kenv.calls())


# ---- ssh-agent ------------------------------------------------------------------------


@pytest.fixture
def agent(kenv):
    path = kenv.tmp / "agent.sock"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    kenv.env["SSH_AUTH_SOCK"] = str(path)
    yield path, str(os.stat(path).st_ino)
    s.close()


def _envs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]


def test_ssh_agent_default_is_off_and_not_attached(kenv, agent):
    kenv.add_instance()
    assert "無効" in kenv.kali("ssh-agent").out
    kenv.kali("run", "true")
    assert "ssh-agent" not in kenv.state["instances"]["kali"]["devices"]
    assert not any(e.startswith("SSH_AUTH_SOCK=") for e in _envs(last_exec(kenv)))


def test_ssh_agent_on_attaches_on_run(kenv, agent):
    path, _ = agent
    kenv.add_instance()
    assert kenv.kali("ssh-agent", "on").rc == 0
    assert kenv.state["instances"]["kali"]["config"]["user.kali-incus.ssh-agent"] == "true"
    assert "有効" in kenv.kali("ssh-agent").out
    kenv.kali("run", "true")
    dev = kenv.state["instances"]["kali"]["devices"]["ssh-agent"]
    assert dev["source"] == str(path) and dev["path"] == "/mnt/.kali-host/ssh-agent" and dev["optional"] == "true"
    assert "SSH_AUTH_SOCK=/mnt/.kali-host/ssh-agent" in _envs(last_exec(kenv))


def test_ssh_agent_reattaches_when_inode_differs_and_keeps_when_same(kenv, agent):
    path, ino = agent
    kenv.add_instance(
        config={
            "user.kali-incus.managed": "true",
            "user.kali-incus.provisioned": "true",
            "user.kali-incus.ssh-agent": "true",
        },
        devices={"ssh-agent": {"type": "disk", "source": "/old", "path": "/mnt/.kali-host/ssh-agent"}},
    )
    kenv.kali("run", "true", FAKE_INCUS_SSH_INO="1")
    assert ["config", "device", "remove", "kali", "ssh-agent"] in kenv.calls()
    assert kenv.state["instances"]["kali"]["devices"]["ssh-agent"]["source"] == str(path)
    kenv.kali("run", "true", FAKE_INCUS_SSH_INO=ino)
    assert sum(c[:3] == ["config", "device", "add"] for c in kenv.calls()) == 1  # 2 回目は付け直さない


def test_ssh_agent_on_without_host_socket_skips_silently(kenv):
    kenv.add_instance()
    kenv.env.pop("SSH_AUTH_SOCK", None)
    r = kenv.kali("ssh-agent", "on")
    assert r.rc == 0 and "SSH_AUTH_SOCK" in r.err  # 設定は有効になるが、ホスト側が使えない旨を警告する
    kenv.kali("run", "true")
    assert "ssh-agent" not in kenv.state["instances"]["kali"]["devices"]
    assert not any(e.startswith("SSH_AUTH_SOCK=") for e in _envs(last_exec(kenv)))


def test_ssh_agent_off_removes_device_and_stops_passing(kenv, agent):
    kenv.add_instance()
    kenv.kali("ssh-agent", "on")
    kenv.kali("run", "true")
    assert kenv.kali("ssh-agent", "off").rc == 0
    assert "ssh-agent" not in kenv.state["instances"]["kali"]["devices"]
    kenv.kali("run", "true")
    assert not any(e.startswith("SSH_AUTH_SOCK=") for e in _envs(last_exec(kenv)))


def test_ssh_agent_env_can_be_overridden_by_e(kenv, agent):
    kenv.add_instance()
    kenv.kali("ssh-agent", "on")
    kenv.kali("run", "-e", "SSH_AUTH_SOCK=/x", "true")
    assert "SSH_AUTH_SOCK=/x" in _envs(last_exec(kenv))


def test_ssh_agent_requires_existing_container(kenv):
    r = kenv.kali("ssh-agent", "on")
    assert r.rc != 0 and "kali up" in r.err


def test_ssh_agent_device_is_hidden_from_mount_ls(kenv):
    kenv.add_instance(devices={"ssh-agent": {"type": "disk", "source": "/s", "path": "/mnt/.kali-host/ssh-agent"}})
    assert "ssh-agent" not in kenv.kali("mount", "ls").out


def test_shell_uses_login_shell(kenv):
    kenv.add_instance()
    assert kenv.kali("shell").rc == 0
    assert last_exec(kenv)[-2:] == ["/usr/bin/zsh", "-l"]


# ---- forward --------------------------------------------------------------------------


def test_forward_lifecycle(kenv):
    kenv.add_instance()
    assert kenv.kali("forward", "8080", "80").rc == 0
    dev = kenv.state["instances"]["kali"]["devices"]["fwd-tcp-8080"]
    assert dev["listen"] == "tcp:127.0.0.1:8080" and dev["connect"] == "tcp:127.0.0.1:80"
    assert "公開済み" not in kenv.kali("forward", "ls").err
    assert "8080" in kenv.kali("forward", "ls").out
    assert "既に公開" in kenv.kali("forward", "8080", "81").err
    r = kenv.kali("forward", "4444", "4444", "--proto", "udp", "--bind", "0.0.0.0")
    assert "注意" in r.err
    assert kenv.state["instances"]["kali"]["devices"]["fwd-udp-4444"]["listen"] == "udp:0.0.0.0:4444"
    # forward 経由のデバイスはマウント一覧に出ない
    assert "公開" not in kenv.kali("mount", "ls").out
    assert kenv.kali("unforward", "8080").rc == 0
    assert kenv.kali("unforward", "8080").rc == 1
    assert kenv.kali("unforward", "4444", "--proto", "udp").rc == 0
    assert kenv.state["instances"]["kali"]["devices"] == {}


def test_forward_ipv6_and_bad_port(kenv):
    kenv.add_instance()
    kenv.kali("forward", "9000", "9000", "--bind", "::1")
    assert kenv.state["instances"]["kali"]["devices"]["fwd-tcp-9000"]["listen"] == "tcp:[::1]:9000"
    assert kenv.kali("forward", "99999", "1").rc == 1


# ---- snapshot / restore ---------------------------------------------------------------


def test_snapshot_lifecycle(kenv):
    kenv.add_instance()
    assert kenv.kali("snapshot", "base").rc == 0
    assert kenv.kali("snapshot").rc == 0  # 名前省略
    out = kenv.kali("snapshot", "ls").out
    assert "base" in out and "snap-" in out
    assert kenv.kali("snapshot", "rm", "nope").rc == 1
    assert kenv.kali("snapshot", "rm", "base").rc == 0
    assert "base" not in kenv.kali("snapshot", "ls").out
    assert kenv.kali("snapshot", "ls").rc == 0


def test_restore_prompt_and_restores_devices(kenv):
    kenv.add_instance()
    kenv.kali("snapshot", "base")
    host = kenv.tmp / "w"
    host.mkdir()
    kenv.kali("mount", "-s", str(host), "-d", "/w")
    assert kenv.kali("restore", "base", input="n\n").rc == 1
    assert kenv.state["instances"]["kali"]["devices"]  # まだ戻っていない
    assert kenv.kali("restore", "base", "-y").rc == 0
    assert kenv.state["instances"]["kali"]["devices"] == {}  # マウント設定も戻る
    assert kenv.kali("restore", "ghost", "-y").rc == 1


def test_snapshot_needs_existing_managed_instance(kenv):
    assert "kali up" in kenv.kali("snapshot", "x").err
    kenv.add_instance(config={})
    assert kenv.kali("snapshot", "x").rc == 1


# ---- 初期設定中のネットワーク不通 -------------------------------------------------------


@pytest.mark.parametrize(
    ("setup_exit", "setup_err"),
    [
        ("42", "http.kali.org:80 に接続できません"),  # setup.sh が自分で検出
        ("100", "E: Failed to fetch http://kali.download/x  Unable to connect to kali.download:http:"),
    ],
)
def test_up_network_failure_gives_guidance_and_can_resume(kenv, setup_exit, setup_err):
    r = kenv.kali("up", FAKE_INCUS_SETUP_EXIT=setup_exit, FAKE_INCUS_SETUP_ERR=setup_err)
    assert r.rc == 1
    assert "sudo ufw allow in on incusbr0" in r.err and "DOCKER-USER" in r.err
    assert "`kali up`" in r.err
    inst = kenv.state["instances"]["kali"]
    assert inst["status"] == "Running"  # コンテナは残す
    assert "user.kali-incus.provisioned" not in inst["config"]
    # 原因を直したあとの再実行は、作り直さず初期設定だけをやり直す
    assert kenv.kali("up").rc == 0
    assert kenv.state["instances"]["kali"]["config"]["user.kali-incus.provisioned"] == "true"
    assert sum(c[0] == "init" for c in kenv.calls()) == 1


def test_up_other_setup_failure_is_not_blamed_on_network(kenv):
    r = kenv.kali("up", FAKE_INCUS_SETUP_EXIT="1", FAKE_INCUS_SETUP_ERR="E: dpkg was interrupted")
    assert r.rc == 1 and "ufw" not in r.err and "dpkg was interrupted" in r.err


def test_up_network_guidance_names_target(kenv):
    r = kenv.kali("-t", "pentest", "up", FAKE_INCUS_SETUP_EXIT="42")
    assert "`kali -t pentest up`" in r.err


# ---- provision ------------------------------------------------------------------------


def _setup_calls(kenv):
    return [c for c in kenv.calls_full() if c["argv"][:2] == ["exec", "kali"] and "-s" in c["argv"]]


def test_provision_default_package(kenv):
    kenv.add_instance()
    r = kenv.kali("provision")
    assert r.rc == 0, r.err
    (call,) = _setup_calls(kenv)
    assert call["argv"][-3:] == ["1000", "kali", "kali-linux-default"]
    assert "kali-defaults" in call["stdin"] and "cp -rn /etc/skel/." in call["stdin"]
    assert "kali-themes" in call["stdin"]  # Kali の見た目（GTK テーマ・アイコン）
    assert (
        "qt5-gtk-platformtheme" in call["stdin"] and "qt6-gtk-platformtheme" in call["stdin"]
    )  # Qt が GTK テーマを使う
    # GTK3/4 のテーマは kali-themes が設定しないので、settings.ini を（無いときだけ）置く
    assert "/etc/xdg/gtk-$v/settings.ini" in call["stdin"] and "gtk-theme-name=Kali-Dark" in call["stdin"]
    assert '[ ! -e "$f" ]' in call["stdin"]
    # kali-themes の GSettings 既定 (adw-gtk3-dark) は入らないテーマなので、dconf のシステム設定で Kali-Dark を指定する
    assert "/etc/dconf/db/local.d/20-kali-incus-theme" in call["stdin"]
    assert "gtk-theme='Kali-Dark'" in call["stdin"] and "dconf update" in call["stdin"]
    assert "adw-gtk3-dark" in call["stdin"]  # 実在するなら上書きしない


def test_provision_custom_packages(kenv):
    kenv.add_instance()
    assert kenv.kali("provision", "kali-tools-top10", "kali-tools-web").rc == 0
    assert _setup_calls(kenv)[0]["argv"][-2:] == ["kali-tools-top10", "kali-tools-web"]


def test_provision_rejects_bad_package_name(kenv):
    kenv.add_instance()
    r = kenv.kali("provision", "foo;rm")
    assert r.rc == 1 and "不正" in r.err
    assert not _setup_calls(kenv)


def test_provision_creates_missing_target(kenv):
    assert kenv.kali("-t", "fresh", "provision").rc == 0
    assert kenv.state["instances"]["fresh"]["config"]["user.kali-incus.provisioned"] == "true"


def test_provision_refuses_unmanaged(kenv):
    kenv.add_instance(config={})
    assert kenv.kali("provision").rc == 1


def test_setup_installs_kali_defaults_before_creating_the_user():
    """kali-defaults が useradd より後だと /etc/skel が配られず、zsh がゼロ設定で起動する。"""
    from kali_incus.lifecycle import script

    text = script("setup.sh")
    assert text.index("kali-defaults") < text.index("useradd")
    assert "zsh-autosuggestions" in text and "zsh-syntax-highlighting" in text


# ---- systemd の起動が完了しない環境 ------------------------------------------------------


def test_up_warns_when_systemd_never_finishes_booting(kenv):
    r = kenv.kali("up", FAKE_INCUS_SYSTEMD="initializing", KALI_BOOT_TIMEOUT="0")
    assert r.rc == 0  # 警告して続行する
    assert "systemd がまだ起動を完了していません" in r.err and "initializing" in r.err
    assert "incus config set kali raw.apparmor='signal peer=incus-**//&unconfined," in r.err
    assert "kali reload" in r.err


def test_up_does_not_warn_when_degraded(kenv):
    r = kenv.kali("up", FAKE_INCUS_SYSTEMD="degraded")
    assert r.rc == 0 and "systemd がまだ" not in r.err


def test_systemd_warning_names_the_target(kenv):
    r = kenv.kali("-t", "pentest", "up", FAKE_INCUS_SYSTEMD="initializing", KALI_BOOT_TIMEOUT="0")
    assert "incus config set pentest raw.apparmor=" in r.err and "kali -t pentest reload" in r.err


def test_existing_container_config_is_not_modified(kenv):
    """既存のコンテナには raw.apparmor を黙って足さない（警告で手順を示すだけ）。"""
    kenv.add_instance(status="Stopped")
    assert kenv.kali("up", FAKE_INCUS_SYSTEMD="initializing", KALI_BOOT_TIMEOUT="0").rc == 0
    assert "raw.apparmor" not in kenv.state["instances"]["kali"]["config"]
    assert not any(c[:2] == ["config", "set"] for c in kenv.calls())


def test_wait_boot_keeps_polling_until_systemd_is_ready(kenv):
    """起動直後は接続できず空や initializing が返る。running になるまで待ち、警告は出さない。"""
    r = kenv.kali("up", FAKE_INCUS_SYSTEMD_SEQ=",initializing,starting,running", KALI_BOOT_TIMEOUT="30")
    assert r.rc == 0 and "systemd がまだ" not in r.err
    polls = [c for c in kenv.calls() if c[-2:] == ["systemctl", "is-system-running"]]
    assert len(polls) == 4


def test_wait_boot_gives_up_after_timeout(kenv):
    r = kenv.kali("up", FAKE_INCUS_SYSTEMD="starting", KALI_BOOT_TIMEOUT="1")
    assert r.rc == 0 and "starting" in r.err


# ---- kali run -e / kali shell -e -----------------------------------------------------


def _envs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]


def _command_tail(argv):
    """`setpriv ... --` の後ろ（コンテナ内で実行されるコマンド）。"""
    return argv[len(argv) - argv[::-1].index("--") :]


def test_run_passes_extra_env(kenv):
    kenv.add_instance()
    r = kenv.kali("run", "-e", "QT_QPA_PLATFORMTHEME=gtk3", "--env=FOO=a=b c", "wireshark", "-e", "x")
    assert r.rc == 0, r.err
    argv = last_exec(kenv)
    envs = _envs(argv)
    assert "QT_QPA_PLATFORMTHEME=gtk3" in envs and "FOO=a=b c" in envs
    assert _command_tail(argv) == ["wireshark", "-e", "x"]  # コマンド以降の -e は引数のまま


def test_run_extra_env_overrides_defaults(kenv):
    kenv.add_instance()
    kenv.kali("run", "-e", "LANG=ja_JP.UTF-8", "-e", "QT_QPA_PLATFORM=xcb", "true")
    envs = _envs(last_exec(kenv))
    assert [e for e in envs if e.startswith("LANG=")] == ["LANG=ja_JP.UTF-8"]
    assert "LANG=C.UTF-8" not in envs


def test_run_env_then_double_dash_runs_command_starting_with_dash(kenv):
    kenv.add_instance()
    assert kenv.kali("run", "-e", "A=1", "--", "-e").rc == 0
    assert _command_tail(last_exec(kenv)) == ["-e"]


@pytest.mark.parametrize("bad", [["-e"], ["-e", "FOO"], ["-e", "1X=2"]])
def test_run_env_errors(kenv, bad):
    kenv.add_instance()
    r = kenv.kali("run", *bad, "true")
    assert r.rc == 1 and ("NAME=値" in r.err or "値がありません" in r.err)
    assert not any(c[0] == "exec" for c in kenv.calls())  # 何も実行しない


def test_run_env_without_command_is_error(kenv):
    kenv.add_instance()
    assert "コマンドを指定" in kenv.kali("run", "-e", "A=1").err


def test_shell_extra_env_and_stray_args(kenv):
    kenv.add_instance()
    assert kenv.kali("shell", "-e", "FOO=bar").rc == 0
    assert "FOO=bar" in _envs(last_exec(kenv)) and last_exec(kenv)[-2:] == ["/usr/bin/zsh", "-l"]
    r = kenv.kali("shell", "ls")
    assert r.rc == 1 and "余分な引数" in r.err


def test_qt_platformtheme_default_can_be_overridden(kenv, wayland):
    kenv.add_instance()
    kenv.kali("run", "-e", "QT_QPA_PLATFORMTHEME=qt6ct", "true", FAKE_INCUS_CT_INO=wayland[1])
    envs = _envs(last_exec(kenv))
    assert [e for e in envs if e.startswith("QT_QPA_PLATFORMTHEME=")] == ["QT_QPA_PLATFORMTHEME=qt6ct"]


# ---- kali run --root / kali shell --root ---------------------------------------------


def test_run_root_skips_user_switch_and_sets_root_env(kenv):
    kenv.add_instance()
    assert kenv.kali("run", "--root", "-e", "FOO=bar", "zenmap", "-v").rc == 0
    argv = last_exec(kenv)
    assert "setpriv" not in argv  # ユーザーへ切り替えない（incus exec はもともと root）
    assert _command_tail(argv) == ["zenmap", "-v"]
    envs = _envs(argv)
    assert {"HOME=/root", "USER=root", "LOGNAME=root", "FOO=bar"} <= set(envs)
    assert "XDG_RUNTIME_DIR=/run/user/1000" in envs  # Wayland のソケットはユーザーの runtime dir にある
    assert not any(e.startswith("DBUS_SESSION_BUS_ADDRESS=") for e in envs)  # ユーザーのバスに root は接続できない
    assert argv[argv.index("--cwd") + 1] == "/root"


def test_run_root_gui_env_and_xauthority(kenv, wayland):
    kenv.add_instance()
    assert kenv.kali("run", "--root", "true", FAKE_INCUS_CT_INO=wayland[1], DISPLAY=":0").rc == 0
    envs = _envs(last_exec(kenv))
    assert "WAYLAND_DISPLAY=wayland-0" in envs and "QT_QPA_PLATFORMTHEME=gtk3" in envs
    assert "DISPLAY=:0" in envs and "XAUTHORITY=/home/kali/.Xauthority" in envs  # X11 はユーザーの cookie を使う


def test_run_without_root_is_unchanged(kenv):
    kenv.add_instance()
    kenv.kali("run", "true")
    argv = last_exec(kenv)
    assert "setpriv" in argv and "HOME=/home/kali" in _envs(argv)
    assert not any(e.startswith("XAUTHORITY=") for e in _envs(argv))


def test_run_root_after_command_is_an_argument(kenv):
    kenv.add_instance()
    kenv.kali("run", "true", "--root")
    argv = last_exec(kenv)
    assert "setpriv" in argv and _command_tail(argv) == ["true", "--root"]


def test_run_root_cwd_maps_into_mount(kenv):
    import subprocess
    import sys

    from conftest import KALI

    host = kenv.tmp / "proj"
    host.mkdir()
    kenv.add_instance(devices={"s": {"type": "disk", "source": str(host.resolve()), "path": "/work"}})
    subprocess.run([sys.executable, str(KALI), "run", "--root", "pwd"], cwd=host, env=kenv.env, input="", text=True)
    argv = last_exec(kenv)
    assert argv[argv.index("--cwd") + 1] == "/work"


def test_shell_root(kenv):
    kenv.add_instance()
    assert kenv.kali("shell", "--root").rc == 0
    argv = last_exec(kenv)
    assert "setpriv" not in argv and "HOME=/root" in _envs(argv)
    assert argv[-3:-1] == ["sh", "-c"] and "getent passwd 0" in argv[-1]  # root のログインシェルを引く


def test_provision_installs_noto_and_ships_wellformed_fontconfig():
    """provision.sh が埋め込む fontconfig の設定は、XML として正しく、Noto CJK をフォールバックにする。"""
    import re
    import xml.etree.ElementTree as ET

    from kali_incus.lifecycle import script

    text = script("provision.sh")
    assert "fonts-noto-core" in text and "fonts-noto-cjk" in text
    assert "/etc/fonts/conf.d/69-kali-incus-noto-cjk.conf" in text
    m = re.search(r"<<'EOT'\n(.*?)\nEOT", text, re.S)
    assert m, "fontconfig の heredoc が見つからない"
    root = ET.fromstring(
        m.group(1).split("?>", 1)[1].split("<fontconfig>", 1)[0]
        + "<fontconfig>"
        + m.group(1).split("<fontconfig>", 1)[1]
    )
    prefers = {
        a.findtext("family"): [f.text for f in a.iter("family") if f.text != a.findtext("family")]
        for a in root.iter("alias")
    }
    assert prefers["sans-serif"] == [f"Noto Sans CJK {r}" for r in ("JP", "SC", "TC", "KR")]  # 既定は日本語
    assert prefers["serif"][0] == "Noto Serif CJK JP" and prefers["monospace"][0] == "Noto Sans Mono CJK JP"
    # 中国語・韓国語のページでは、地域に合った字形を先に選ぶ（3 総称 × 4 言語）
    edits = {
        (m_.find("test[@name='lang']/string").text, m_.find("test[@name='family']/string").text): m_.find(
            "edit/string"
        ).text
        for m_ in root.iter("match")
    }
    assert (
        edits[("zh-cn", "sans-serif")] == "Noto Sans CJK SC" and edits[("ko", "monospace")] == "Noto Sans Mono CJK KR"
    )
    assert edits[("zh-hk", "serif")] == "Noto Serif CJK HK" and len(edits) == 12
    assert "Cantarell" not in m.group(1)  # UI のフォントは変えない


def test_provision_masks_rpc_pipefs_mount_after_installing_packages():
    """権限のないコンテナでは rpc_pipefs をマウントできず、systemd が degraded になる。mask して防ぐ。"""
    from kali_incus.lifecycle import script

    text = script("provision.sh")
    link = "ln -sf /dev/null /etc/systemd/system/run-rpc_pipefs.mount"
    assert link in text
    assert text.index(link) > text.index('apt-get install -y "$@"')  # nfs-common が入ったあと
    assert "timeout 30 systemctl daemon-reload" in text  # systemd の応答が遅くても固まらない
