#!/bin/bash
# コンテナ作成直後に root で 1 回実行する初期設定。冪等に書いてある。
#   引数: $1=ユーザーの UID  $2=作成するユーザー名
set -eu
uid=$1
name=$2

# ネットワーク（DNS だけでなく TCP 接続）が使えるようになるまで待つ。
# 使えなければ終了コード 42 で終わり、呼び出し側が対処方法を案内する。
reachable() { timeout -s KILL 4 bash -c 'exec 3<>/dev/tcp/http.kali.org/80' 2>/dev/null; }
ok=0
for _ in $(seq 1 15); do
  if reachable; then ok=1; break; fi
  sleep 1
done
if [ "$ok" -eq 0 ]; then
  echo "http.kali.org:80 に接続できません" >&2
  exit 42
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# kali-defaults は Kali 標準の zsh 設定を /etc/skel に置く。useradd は作成時に /etc/skel を
# コピーするので、ユーザーを作る前に入れること（後だと ~/.zshrc が無いまま zsh が起動する）
apt-get install -y -qq sudo xauth zsh dbus-user-session \
  kali-defaults zsh-autosuggestions zsh-syntax-highlighting ncurses-term >/dev/null

if ! getent passwd "$uid" >/dev/null; then
  getent group "$uid" >/dev/null || groupadd -g "$uid" "$name"
  useradd -m -u "$uid" -g "$uid" -s /usr/bin/zsh "$name"
fi
user=$(getent passwd "$uid" | cut -d: -f1)

# render は kali up の直後にはまだ無い（udev の導入時に作られる）ので、あるときだけ入る。入らなくても支障はない:
# GPU デバイスは gid=44 (video) で渡しているので、video に所属していれば足りる
for g in sudo video render; do
  if getent group "$g" >/dev/null; then usermod -aG "$g" "$user"; fi
done

# コンテナ内 sudo はパスワードなし（コンテナの root はホストでは非特権ユーザー）
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$user" >/etc/sudoers.d/90-kali-incus
chmod 0440 /etc/sudoers.d/90-kali-incus

# ユーザーの systemd / D-Bus セッションを常時起動させる
timeout 30 loginctl enable-linger "$user" 2>/dev/null || true
