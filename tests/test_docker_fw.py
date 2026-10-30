"""contrib/systemd/docker-fw.sh を、状態を持つ偽 iptables / ip6tables で検証する。"""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

SCRIPT = ROOT / "contrib" / "systemd" / "docker-fw.sh"

FAKE_IPT = """#!/usr/bin/env python3
import os, sys
rules_file = os.environ["FAKE_RULES_DIR"] + "/" + os.path.basename(sys.argv[0])
chain = os.environ.get("FAKE_CHAIN_" + os.path.basename(sys.argv[0]), "1") == "1"
args = [a for a in sys.argv[1:] if a != "-w"]
op, name, rule = args[0], args[1], " ".join(args[2:])
rules = open(rules_file).read().splitlines() if os.path.exists(rules_file) else []
if not chain:
    sys.exit(1)
if op == "-S":
    sys.exit(0)
elif op == "-C":
    sys.exit(0 if rule in rules else 1)
elif op == "-I":
    rules.insert(0, rule)
elif op == "-D":
    rules.remove(rule)
open(rules_file, "w").write("\\n".join(rules) + ("\\n" if rules else ""))
"""


@pytest.fixture
def fw(tmp_path: Path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("iptables", "ip6tables"):
        p = bindir / name
        p.write_text(FAKE_IPT)
        p.chmod(0o755)
    (tmp_path / "rules").mkdir()
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_RULES_DIR": str(tmp_path / "rules")}

    def run(action: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(SCRIPT), action], env={**env, **extra}, text=True, capture_output=True)

    def rules(name: str) -> list[str]:
        f = tmp_path / "rules" / name
        return f.read_text().splitlines() if f.exists() else []

    return run, rules


def test_start_adds_rules_for_both_families(fw):
    run, rules = fw
    assert run("start").returncode == 0
    for name in ("iptables", "ip6tables"):
        assert sorted(rules(name)) == sorted(
            ["-i incusbr0 -j ACCEPT", "-o incusbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"]
        )


def test_start_is_idempotent(fw):
    run, rules = fw
    run("start")
    run("start")
    assert len(rules("iptables")) == 2


def test_stop_removes_only_our_rules(fw, tmp_path):
    run, rules = fw
    (tmp_path / "rules" / "iptables").write_text("-i docker0 -j ACCEPT\n")
    run("start")
    assert run("stop").returncode == 0
    assert rules("iptables") == ["-i docker0 -j ACCEPT"]
    assert rules("ip6tables") == []


def test_custom_bridge(fw):
    run, rules = fw
    run("start", KALI_BRIDGE="br-test")
    assert "-i br-test -j ACCEPT" in rules("iptables")


def test_start_without_docker_chain_fails_but_stop_succeeds(fw):
    run, _ = fw
    r = run("start", FAKE_CHAIN_iptables="0")
    assert r.returncode == 1 and "Docker" in r.stderr
    assert run("stop", FAKE_CHAIN_iptables="0").returncode == 0


def test_ipv6_skipped_when_chain_missing(fw):
    run, rules = fw
    assert run("start", FAKE_CHAIN_ip6tables="0").returncode == 0
    assert len(rules("iptables")) == 2 and rules("ip6tables") == []


def test_bad_action(fw):
    run, _ = fw
    assert run("restart").returncode == 2
