"""エラー型、メッセージ出力、確認プロンプト、表の整形。"""

import sys
from collections.abc import Sequence


class KaliError(Exception):
    """利用者に見せるエラー。メッセージだけを表示して終了コード 1 で終わる。"""


def info(msg: str) -> None:
    print(f"kali: {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"kali: 警告: {msg}", file=sys.stderr)


def confirm(question: str, assume_yes: bool) -> bool:
    """y / yes のときだけ True。標準入力が閉じていれば False（何も実行しない）。"""
    if assume_yes:
        return True
    print(f"kali: {question} [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        answer = input()
    except EOFError:
        print(file=sys.stderr)
        return False
    return answer.strip().lower() in ("y", "yes")


def format_table(rows: Sequence[Sequence[str]]) -> str:
    """先頭行を見出しとして、列幅をそろえた表にする。"""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip() for row in rows)
