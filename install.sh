#!/usr/bin/env bash
# kali-incus のインストーラ。
#   ./install.sh                         ~/.local へ入れる（既定）
#   sudo ./install.sh PREFIX=/usr/local  システム全体へ入れる
#   ./install.sh --uninstall [PREFIX=...] 入れたファイルだけを削除する
# 環境変数 PREFIX / DESTDIR でも指定できる。sudo は自動では実行しない。
set -euo pipefail

SRC_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PREFIX=${PREFIX:-$HOME/.local}
DESTDIR=${DESTDIR:-}
uninstall=0

die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

for arg in "$@"; do
  case $arg in
    --uninstall) uninstall=1 ;;
    PREFIX=*)    PREFIX=${arg#PREFIX=} ;;
    DESTDIR=*)   DESTDIR=${arg#DESTDIR=} ;;
    -h|--help)   sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           die "不明な引数: $arg" ;;
  esac
done

root=${DESTDIR}${PREFIX}
bin_dir=$root/bin
lib_dir=$root/lib/kali-incus
share_dir=$root/share
bash_comp=$share_dir/bash-completion/completions/kali
zsh_comp=$share_dir/zsh/site-functions/_kali
doc_dir=$share_dir/doc/kali-incus

# 書き込み先の最初の既存ディレクトリに書けるか確認する（sudo は実行しない）
probe=$root
while [[ ! -e $probe ]]; do probe=$(dirname "$probe"); done
if [[ ! -w $probe ]]; then
  die "${probe} に書き込めません。管理者権限が必要なら次のように実行してください:
  sudo $0 $* PREFIX=${PREFIX}"
fi

if (( uninstall )); then
  rm -f "$bin_dir/kali" "$bash_comp" "$zsh_comp"
  rm -rf "$lib_dir" "$doc_dir"
  echo "削除しました: ${root} 配下の kali-incus"
  exit 0
fi

command -v python3 >/dev/null || die "python3 が見つかりません"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10 以上が必要です"

install -d "$bin_dir" "$lib_dir" "$(dirname "$bash_comp")" "$(dirname "$zsh_comp")" "$doc_dir"
rm -rf "$lib_dir/kali_incus"
cp -r "$SRC_DIR/src/kali_incus" "$lib_dir/kali_incus"
find "$lib_dir" -name __pycache__ -prune -exec rm -rf {} +
install -m 0755 "$SRC_DIR/bin/kali" "$bin_dir/kali"
install -m 0644 "$SRC_DIR/completions/kali.bash" "$bash_comp"
install -m 0644 "$SRC_DIR/completions/_kali" "$zsh_comp"
install -m 0644 "$SRC_DIR/README.md" "$doc_dir/README.md"
# root で入れると一般ユーザーは .pyc を書けないため、ここで生成しておく
python3 -m compileall -q "$lib_dir/kali_incus" || true

echo "インストールしました: ${bin_dir}/kali"
case ":$PATH:" in
  *":$PREFIX/bin:"*) ;;
  *) echo "注意: ${PREFIX}/bin が PATH に含まれていません。再ログインするか PATH に追加してください" ;;
esac
if [[ $PREFIX == "$HOME"/* ]]; then
  echo "zsh の補完を使うには、~/.zshrc の compinit より前に次の行を追加してください（自動では書き換えません）:"
  echo "  fpath=(${PREFIX}/share/zsh/site-functions \$fpath)"
fi
