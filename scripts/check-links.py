#!/usr/bin/env python3
"""Markdown 상대 링크가 실제 파일을 가리키는지 검사합니다.

인자 없이 실행하면 templates/ 아래의 각 티어를 검사하고,
디렉터리를 인자로 주면 그 디렉터리를 독립 저장소로 보고 검사합니다.
"""
import os
import pathlib
import re
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def check(base):
    broken = []
    for path in sorted(base.rglob("*.md")):
        if any(part in {".git", ".venv", "node_modules", "artifacts"} for part in path.relative_to(base).parts):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                rel = urllib.parse.unquote(target.split("#")[0])
                if not rel:
                    continue
                if not os.path.exists((path.parent / rel).resolve()):
                    broken.append(f"{path.relative_to(base)}:{lineno} -> {target}")
    return broken


def main(argv):
    if argv:
        bases = [pathlib.Path(a).resolve() for a in argv]
    else:
        bases = sorted(p for p in (ROOT / "templates").iterdir() if p.is_dir())

    total = 0
    for base in bases:
        broken = check(base)
        total += len(broken)
        print(f"{base.name}: {'OK' if not broken else f'{len(broken)}건 깨짐'}")
        for item in broken:
            print(f"  {item}", file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
