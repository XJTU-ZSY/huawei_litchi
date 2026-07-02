from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INCLUDE_PATHS = [
    ROOT / "start.sh",
    ROOT / "litchi_bot",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build contest submission zip")
    parser.add_argument("output", nargs="?", default="dist/litchi_bot.zip")
    args = parser.parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in INCLUDE_PATHS:
            if path.is_file():
                _write_file(archive, path)
            else:
                for child in sorted(path.rglob("*")):
                    if child.is_file() and "__pycache__" not in child.parts and child.suffix != ".pyc":
                        _write_file(archive, child)
    print(output)


def _write_file(archive: zipfile.ZipFile, path: Path) -> None:
    arcname = path.relative_to(ROOT).as_posix()
    info = zipfile.ZipInfo.from_file(path, arcname)
    if arcname == "start.sh":
        info.external_attr = (stat.S_IFREG | 0o755) << 16
    archive.writestr(info, path.read_bytes())


if __name__ == "__main__":
    main()
