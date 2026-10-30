"""incus に触れない純関数の単体テスト。"""

import pytest

from kali_incus import config, forward, mounts, prereq, snapshot
from kali_incus.common import KaliError, format_table


def test_target_priority():
    env = {"KALI_TARGET": "from-env"}
    assert config.resolve_target("from-cli", env) == "from-cli"
    assert config.resolve_target(None, env) == "from-env"
    assert config.resolve_target(None, {}) == "kali"
    assert config.resolve_target(None, {"KALI_TARGET": ""}) == "kali"


@pytest.mark.parametrize("bad", ["a_b", "1abc", "-a", "a-", "a b", ""])
def test_target_invalid(bad):
    with pytest.raises(KaliError):
        config.validate_target(bad)


def test_config_env_overrides():
    cfg = config.load(None, {"KALI_IMAGE": "x", "KALI_UID": "1234", "KALI_USER": "u", "KALI_LANG": "ja_JP.UTF-8"})
    assert (cfg.image, cfg.uid, cfg.user, cfg.lang) == ("x", 1234, "u", "ja_JP.UTF-8")
    with pytest.raises(KaliError):
        config.load(None, {"KALI_UID": "abc"})


def test_share_name_is_stable_and_distinct():
    a, b = mounts.share_name("/work"), mounts.share_name("/other")
    assert a == mounts.share_name("/work")
    assert a != b
    assert a.startswith("share-") and len(a) == len("share-") + 12


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("/a/b/../c", "/a/c"), ("//a///b/", "/a/b"), ("/a/./b", "/a/b")],
)
def test_normalize_kali_path(raw, expected):
    assert mounts.normalize_kali_path(raw) == expected


@pytest.mark.parametrize("bad", ["relative/path", "/", "/..", "//"])
def test_normalize_kali_path_rejects(bad):
    with pytest.raises(KaliError):
        mounts.normalize_kali_path(bad)


def test_normalize_host_path(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert mounts.normalize_host_path(str(tmp_path / "link")) == str((tmp_path / "real").resolve())
    with pytest.raises(KaliError):
        mounts.normalize_host_path(str(tmp_path / "nope"))


DEVICES = {
    "root": {"type": "disk", "path": "/", "pool": "default"},
    "x11": {"type": "disk", "source": "/tmp/.X11-unix", "path": "/mnt/.kali-host/X11-unix"},
    "wayland": {"type": "disk", "source": "/run/user/1000/wayland-0", "path": "/mnt/.kali-host/wayland"},
    "gpu": {"type": "gpu"},
    "share-aaa": {"type": "disk", "source": "/home/u/work", "path": "/work", "readonly": "false"},
    "custom": {"type": "disk", "source": "/srv/data", "path": "/data", "readonly": "true"},
}


def test_list_mounts_excludes_internal_devices():
    got = mounts.list_mounts(DEVICES)
    assert [(m.path, m.source, m.readonly) for m in got] == [
        ("/data", "/srv/data", True),
        ("/work", "/home/u/work", False),
    ]


def test_map_cwd_longest_match():
    ms = [
        mounts.Mount("a", "/home/u", "/mnt/home", False),
        mounts.Mount("b", "/home/u/proj", "/proj", False),
    ]
    assert mounts.map_cwd("/home/u/proj/src", ms) == "/proj/src"
    assert mounts.map_cwd("/home/u/proj", ms) == "/proj"
    assert mounts.map_cwd("/home/u/other", ms) == "/mnt/home/other"
    assert mounts.map_cwd("/home/u2", ms) is None  # 接頭辞の文字列一致だけでは対応付けない
    assert mounts.map_cwd("/etc", ms) is None


def test_missing_sources(tmp_path):
    here = tmp_path / "here"
    here.mkdir()
    devs = {
        "ok": {"type": "disk", "source": str(here), "path": "/ok"},
        "gone": {"type": "disk", "source": str(tmp_path / "gone"), "path": "/gone"},
        "optional": {"type": "disk", "source": str(tmp_path / "x"), "path": "/o", "optional": "true"},
        "gpu": {"type": "gpu"},
    }
    assert mounts.missing_sources(devs) == [("gone", str(tmp_path / "gone"))]


def test_ranges_cover():
    text = "alice:100000:65536\nroot:1000:1\nroot:5000:100\n# x\nbad\n"
    assert prereq.ranges_cover(text, "root", 1000)
    assert prereq.ranges_cover(text, "root", 5099)
    assert not prereq.ranges_cover(text, "root", 5100)
    assert not prereq.ranges_cover(text, "root", 100000)  # alice の範囲は root には効かない
    assert prereq.ranges_cover("root:0:65536\n", "root", 1000)


def test_forward_helpers():
    assert forward.forward_name("tcp", 8080) == "fwd-tcp-8080"
    with pytest.raises(KaliError):
        forward.parse_port("0")
    with pytest.raises(KaliError):
        forward.parse_port("70000")
    with pytest.raises(KaliError):
        forward.parse_port("abc")
    assert forward.parse_port("443") == 443


def test_snapshot_names():
    assert snapshot.default_name().startswith("snap-")
    assert snapshot.validate_name("base") == "base"
    for bad in ("ls", "rm", "-x", "a b", ""):
        with pytest.raises(KaliError):
            snapshot.validate_name(bad)


def test_format_table():
    assert format_table([["A", "BB"], ["ccc", "d"]]) == "A    BB\nccc  d"


def _fake_group(monkeypatch, *, members, session_gids, exists=True):
    import grp
    import os
    from types import SimpleNamespace

    def getgrnam(name):
        if not exists:
            raise KeyError(name)
        return SimpleNamespace(gr_gid=990, gr_mem=members)

    monkeypatch.setattr(grp, "getgrnam", getgrnam)
    monkeypatch.setattr(os, "getgroups", lambda: session_gids)
    monkeypatch.setattr(prereq.getpass, "getuser", lambda: "alice")


def test_diagnose_ignores_unrelated_errors():
    assert prereq.diagnose("Error: Not Found") is None


def test_diagnose_not_in_group(monkeypatch):
    _fake_group(monkeypatch, members=[], session_gids=[1000])
    msg = prereq.diagnose("Error: ... permission denied")
    assert "usermod -aG incus-admin alice" in msg


def test_diagnose_in_group_but_session_stale(monkeypatch):
    _fake_group(monkeypatch, members=["alice"], session_gids=[1000])
    msg = prereq.diagnose("permission denied")
    assert "再ログイン" in msg and "newgrp" not in msg


def test_diagnose_in_session_means_uninitialized(monkeypatch):
    _fake_group(monkeypatch, members=["alice"], session_gids=[990])
    assert "incus admin init" in prereq.diagnose("cannot connect")


def _split(args):
    from kali_incus.run import split_run_options

    o = split_run_options(args)
    return o.env, o.root, o.rest


def test_split_run_options():
    assert _split(["ls", "-la"]) == ({}, False, ["ls", "-la"])
    assert _split(["-e", "A=1", "--env", "B=2", "--env=C=3", "cmd", "-e", "X=9"]) == (
        {"A": "1", "B": "2", "C": "3"},
        False,
        ["cmd", "-e", "X=9"],  # コマンドより後ろの -e はコマンドの引数
    )
    assert _split(["-e", "A=b=c d", "x"])[0] == {"A": "b=c d"}  # 値に = や空白を含められる
    assert _split(["-e", "E=", "x"])[0] == {"E": ""}  # 空の値
    assert _split(["-e", "A=1", "--", "-e"]) == ({"A": "1"}, False, ["-e"])  # -- で区切る
    assert _split(["-e", "A=1", "-e", "A=2", "x"])[0] == {"A": "2"}  # 後勝ち
    assert _split([]) == ({}, False, [])


def test_split_run_options_root():
    assert _split(["--root", "zenmap"]) == ({}, True, ["zenmap"])
    assert _split(["-e", "A=1", "--root", "-e", "B=2", "zenmap"]) == ({"A": "1", "B": "2"}, True, ["zenmap"])
    assert _split(["zenmap", "--root"]) == ({}, False, ["zenmap", "--root"])  # コマンドより後ろはそのまま
    assert _split(["--root", "--", "--root"]) == ({}, True, ["--root"])


@pytest.mark.parametrize("args", [["-e"], ["--env"], ["-e", "FOO"], ["-e", "1X=2"], ["-e", "=v"], ["-e", "A-B=1"]])
def test_split_run_options_rejects(args):
    from kali_incus.run import split_run_options

    with pytest.raises(KaliError):
        split_run_options(args)
