from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping


def create_process_log(path: Path, title: str, metadata: Mapping[str, object] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    lines = [
        f"# {title}",
        "",
        "## Metadata",
        "",
    ]
    for key, value in (metadata or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Timeline", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def append_process_event(path: Path, stage: str, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        create_process_log(path, "Process Log")
    entry = "\n".join(
        [
            "",
            f"### {datetime.now().isoformat(timespec='seconds')} - {stage}",
            "",
            content.rstrip() or "(no detail)",
            "",
        ]
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    return path
