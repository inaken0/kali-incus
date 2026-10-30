#!/bin/bash
# Docker が FORWARD の既定ポリシーを DROP にするため、Incus のブリッジの通信が捨てられる。
# DOCKER-USER チェーン（Docker が書き換えない、ユーザー用のチェーン）に許可ルールを足す／外す。
#   使い方: docker-fw.sh start|stop
#   環境変数 KALI_BRIDGE: 対象のブリッジ名（既定: incusbr0）
# 何度実行しても同じ結果になる（既にあるルールは重ねて追加しない）。
set -euo pipefail

bridge=${KALI_BRIDGE:-incusbr0}
action=${1:-}

case $action in
  start | stop) ;;
  *)
    echo "使い方: ${0##*/} start|stop" >&2
    exit 2
    ;;
esac

rules=(
  "-i $bridge -j ACCEPT"
  "-o $bridge -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
)

chain_exists() { "$1" -w -S DOCKER-USER >/dev/null 2>&1; }

apply() {
  local ipt=$1 rule
  for rule in "${rules[@]}"; do
    # $rule は意図的に単語分割する（iptables の引数に展開するため）
    # shellcheck disable=SC2086
    case $action in
      start) "$ipt" -w -C DOCKER-USER $rule 2>/dev/null || "$ipt" -w -I DOCKER-USER $rule ;;
      stop) while "$ipt" -w -C DOCKER-USER $rule 2>/dev/null; do "$ipt" -w -D DOCKER-USER $rule; done ;;
    esac
  done
}

if ! chain_exists iptables; then
  # Docker が動いていなければ外すものもない
  [[ $action == stop ]] && exit 0
  echo "DOCKER-USER チェーンがありません。Docker が起動しているか確認してください" >&2
  exit 1
fi
apply iptables
# IPv6 は Docker が ip6tables を使っているときだけ
if command -v ip6tables >/dev/null && chain_exists ip6tables; then
  apply ip6tables
fi
