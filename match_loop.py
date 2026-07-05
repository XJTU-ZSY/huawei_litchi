#!/usr/bin/env python3
"""
Repeated match runner.

This script starts:
1. one local Python server,
2. two client commands,
3. copies the generated replay file to a target directory,
4. waits for two analysis-done marker files,
5. repeats.

The notification mechanism is intentionally simple: marker files.  For match N,
after the replay is copied, the runner writes a manifest JSON that tells both
clients/tools which marker files to create.  By default:

    <replay-stem>.client_a.done
    <replay-stem>.client_b.done

When both files exist, the next match starts.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent

DEFAULTS: dict[str, object] = {
    "client_a_cmd": "",
    "client_b_cmd": "",
    "client_a_cwd": str(ROOT),
    "client_b_cwd": str(ROOT),
    "client_a_player_id": "1001",
    "client_b_player_id": "1002",
    "client_a_analysis_cmd": "",
    "client_b_analysis_cmd": "",
    "client_a_analysis_cwd": "",
    "client_b_analysis_cwd": "",
    "replay_out_dir": "",
    "run_root": str(ROOT / "match_runs" / "loop"),
    "host": "127.0.0.1",
    "port": 0,
    "tick_ms": 500,
    "duration_round": 600,
    "seed": 20260630,
    "max_matches": 0,
    "start_index": 1,
    "match_timeout": 900.0,
    "analysis_timeout": 0.0,
    "poll_seconds": 2.0,
    "server_start_delay": 1.0,
    "client_start_gap": 0.3,
    "status_interval": 10.0,
    "stop_file": "",
    "no_wait": False,
}

INT_KEYS = {
    "port",
    "tick_ms",
    "duration_round",
    "seed",
    "max_matches",
    "start_index",
}
FLOAT_KEYS = {
    "match_timeout",
    "analysis_timeout",
    "poll_seconds",
    "server_start_delay",
    "client_start_gap",
    "status_interval",
}
BOOL_KEYS = {"no_wait"}


@dataclass
class ProcessSpec:
    name: str
    command: str
    cwd: Path
    stdout_path: Path
    stderr_path: Path


@dataclass
class MatchArtifacts:
    match_index: int
    run_id: str
    run_dir: Path
    port: int
    replay_source: Path
    replay_target: Path
    manifest_path: Path
    client_a_done: Path
    client_b_done: Path


@dataclass
class AnalysisSpec:
    name: str
    command: str
    cwd: Path
    stdout_path: Path
    stderr_path: Path
    done_path: Path
    player_id: str


def log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def choose_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def format_command(template: str, **values: object) -> str:
    return template.format(**values)


def start_process(spec: ProcessSpec) -> subprocess.Popen:
    if not spec.cwd.is_dir():
        raise FileNotFoundError(f"{spec.name} cwd does not exist or is not a directory: {spec.cwd}")
    spec.stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout = spec.stdout_path.open("wb")
    stderr = spec.stderr_path.open("wb")
    if os.name == "nt":
        proc = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            shell=True,
            stdout=stdout,
            stderr=stderr,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        proc = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            shell=True,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    proc._runner_stdout = stdout  # type: ignore[attr-defined]
    proc._runner_stderr = stderr  # type: ignore[attr-defined]
    log(f"started {spec.name} pid={proc.pid} command={spec.command}")
    return proc


def close_process_files(proc: subprocess.Popen) -> None:
    for attr in ("_runner_stdout", "_runner_stderr"):
        fp = getattr(proc, attr, None)
        if fp:
            with contextlib.suppress(Exception):
                fp.close()


def terminate_process_tree(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        close_process_files(proc)
        return
    log(f"terminating {name} pid={proc.pid}")
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    finally:
        close_process_files(proc)


def wait_process(proc: subprocess.Popen, timeout: Optional[float], name: str) -> int:
    try:
        code = proc.wait(timeout=timeout)
    finally:
        close_process_files(proc)
    log(f"{name} exited code={proc.returncode}")
    return int(code if code is not None else proc.returncode or 0)


def tail_file(path: Path, max_lines: int = 20) -> list[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.splitlines()[-max_lines:]


def log_file_tail(label: str, path: Path, max_lines: int = 20) -> None:
    lines = tail_file(path, max_lines)
    if not lines:
        return
    log(f"{label} tail {path}:")
    for line in lines:
        print(f"    {line}", flush=True)


def log_process_logs(spec: ProcessSpec, max_lines: int = 20) -> None:
    log_file_tail(f"{spec.name} stderr", spec.stderr_path, max_lines)
    log_file_tail(f"{spec.name} stdout", spec.stdout_path, max_lines)


def process_state(proc: subprocess.Popen) -> str:
    code = proc.poll()
    return "running" if code is None else f"exited({code})"


def wait_for_match_server(
    server_proc: subprocess.Popen,
    client_procs: dict[str, subprocess.Popen],
    specs: dict[str, ProcessSpec],
    args: argparse.Namespace,
) -> int:
    started_at = time.monotonic()
    last_status = 0.0
    reported_client_exits: set[str] = set()
    log(f"waiting match completion; timeout={args.match_timeout}s")

    while True:
        now = time.monotonic()
        elapsed = now - started_at
        server_code = server_proc.poll()

        for name, proc in client_procs.items():
            code = proc.poll()
            if code is None or name in reported_client_exits:
                continue
            reported_client_exits.add(name)
            log(f"{name} exited while server is {process_state(server_proc)} code={code}")
            if code != 0 or server_code is None:
                log_process_logs(specs[name])
            if server_code is None and code != 0:
                raise RuntimeError(f"{name} exited with code {code} before match completed; see {specs[name].stderr_path}")

        if server_code is not None:
            close_process_files(server_proc)
            log(f"server exited code={server_code}")
            return int(server_code)

        if elapsed >= args.match_timeout:
            for name, spec in specs.items():
                log_process_logs(spec, max_lines=30)
            raise TimeoutError(f"match timed out after {args.match_timeout} seconds")

        if args.status_interval > 0 and now - last_status >= args.status_interval:
            last_status = now
            states = ", ".join(
                [f"server={process_state(server_proc)}"]
                + [f"{name}={process_state(proc)}" for name, proc in client_procs.items()]
            )
            log(f"match status elapsed={elapsed:.1f}s {states}")
            log(f"logs: {specs['server'].stdout_path.parent}")

        time.sleep(min(1.0, max(0.1, args.status_interval if args.status_interval > 0 else 1.0)))


def newest_replay(server_log_dir: Path) -> Path:
    candidates = sorted(server_log_dir.glob("*.replay.jsonl"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"no replay file found in {server_log_dir}")
    return candidates[-1]


def write_manifest(artifacts: MatchArtifacts, args: argparse.Namespace) -> None:
    manifest = {
        "matchIndex": artifacts.match_index,
        "runId": artifacts.run_id,
        "port": artifacts.port,
        "runDir": str(artifacts.run_dir),
        "replay": str(artifacts.replay_target),
        "clientA": {
            "playerId": args.client_a_player_id,
            "doneFile": str(artifacts.client_a_done),
        },
        "clientB": {
            "playerId": args.client_b_player_id,
            "doneFile": str(artifacts.client_b_done),
        },
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }
    artifacts.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_done_marker(path: Path, client_name: str, player_id: str, source: str) -> None:
    payload = {
        "client": client_name,
        "playerId": player_id,
        "source": source,
        "doneAt": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def side_values(
    artifacts: MatchArtifacts,
    args: argparse.Namespace,
    side: str,
    player_id: str,
    done_file: Path,
) -> dict[str, object]:
    return {
        "player_id": player_id,
        "player_id_a": args.client_a_player_id,
        "player_id_b": args.client_b_player_id,
        "side": side,
        "host": args.host,
        "port": artifacts.port,
        "match_index": artifacts.match_index,
        "run_id": artifacts.run_id,
        "run_dir": str(artifacts.run_dir),
        "replay_dir": str(Path(args.replay_out_dir)),
        "replay": str(artifacts.replay_target),
        "manifest": str(artifacts.manifest_path),
        "done_file": str(done_file),
    }


def analysis_specs(artifacts: MatchArtifacts, args: argparse.Namespace) -> list[AnalysisSpec]:
    specs: list[AnalysisSpec] = []
    entries = [
        (
            "client_a",
            "A",
            args.client_a_player_id,
            artifacts.client_a_done,
            args.client_a_analysis_cmd,
            Path(args.client_a_analysis_cwd or args.client_a_cwd),
        ),
        (
            "client_b",
            "B",
            args.client_b_player_id,
            artifacts.client_b_done,
            args.client_b_analysis_cmd,
            Path(args.client_b_analysis_cwd or args.client_b_cwd),
        ),
    ]
    for name, side, player_id, done_file, template, cwd in entries:
        if not template:
            continue
        values = side_values(artifacts, args, side, player_id, done_file)
        specs.append(
            AnalysisSpec(
                name=f"{name}_analysis",
                command=format_command(template, **values),
                cwd=cwd,
                stdout_path=artifacts.run_dir / f"{name}_analysis.stdout.log",
                stderr_path=artifacts.run_dir / f"{name}_analysis.stderr.log",
                done_path=done_file,
                player_id=player_id,
            )
        )
    return specs


def run_analysis_commands(artifacts: MatchArtifacts, args: argparse.Namespace) -> None:
    specs = analysis_specs(artifacts, args)
    if not specs:
        return
    procs: dict[str, subprocess.Popen] = {}
    deadline = None if args.analysis_timeout <= 0 else time.monotonic() + args.analysis_timeout
    try:
        for spec in specs:
            procs[spec.name] = start_process(
                ProcessSpec(
                    spec.name,
                    spec.command,
                    spec.cwd,
                    spec.stdout_path,
                    spec.stderr_path,
                )
            )
        for spec in specs:
            proc = procs[spec.name]
            timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                code = wait_process(proc, timeout, spec.name)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"{spec.name} timed out after {args.analysis_timeout} seconds") from exc
            if code != 0:
                raise RuntimeError(f"{spec.name} exited with code {code}; see {spec.stderr_path}")
            write_done_marker(spec.done_path, spec.name, spec.player_id, "analysis_command_exit_0")
            log(f"analysis marker written: {spec.done_path}")
    finally:
        for name, proc in procs.items():
            terminate_process_tree(proc, name)


def wait_for_analysis(artifacts: MatchArtifacts, args: argparse.Namespace) -> None:
    if args.no_wait:
        log("analysis wait disabled; continuing")
        return
    deadline = None if args.analysis_timeout <= 0 else time.monotonic() + args.analysis_timeout
    log(f"waiting analysis markers: {artifacts.client_a_done.name}, {artifacts.client_b_done.name}")
    while True:
        if args.stop_file and Path(args.stop_file).exists():
            raise KeyboardInterrupt(f"stop file exists: {args.stop_file}")
        missing = [path for path in (artifacts.client_a_done, artifacts.client_b_done) if not path.exists()]
        if not missing:
            log("both analysis markers detected")
            return
        if deadline is not None and time.monotonic() >= deadline:
            names = ", ".join(path.name for path in missing)
            raise TimeoutError(f"analysis markers not found before timeout: {names}")
        time.sleep(args.poll_seconds)


def run_one_match(match_index: int, args: argparse.Namespace) -> MatchArtifacts:
    host = args.host
    port = args.port if args.port else choose_free_port(host)
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_m{match_index:04d}"
    run_dir = Path(args.run_root) / run_id
    server_log_dir = run_dir / "server_logs"
    client_log_dir = run_dir / "client_logs"
    replay_dir = Path(args.replay_out_dir)
    server_log_dir.mkdir(parents=True, exist_ok=True)
    client_log_dir.mkdir(parents=True, exist_ok=True)
    replay_dir.mkdir(parents=True, exist_ok=True)
    log(f"run_dir={run_dir}")
    log(f"server_log_dir={server_log_dir}")
    log(f"replay_out_dir={replay_dir}")

    common_values = {
        "host": host,
        "port": port,
        "match_index": match_index,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "replay_dir": str(replay_dir),
        "player_id_a": args.client_a_player_id,
        "player_id_b": args.client_b_player_id,
    }

    server_cmd = (
        f'"{sys.executable}" -B "{ROOT / "server.py"}" '
        f"--host {host} --port {port} --tick-ms {args.tick_ms} "
        f"--duration-round {args.duration_round} --seed {args.seed + match_index} "
        f"--allowed-player-ids {args.client_a_player_id},{args.client_b_player_id} "
        f'--log-dir "{server_log_dir}"'
    )
    client_a_cmd = format_command(
        args.client_a_cmd,
        **common_values,
        player_id=args.client_a_player_id,
        side="A",
    )
    client_b_cmd = format_command(
        args.client_b_cmd,
        **common_values,
        player_id=args.client_b_player_id,
        side="B",
    )

    specs = {
        "server": ProcessSpec("server", server_cmd, ROOT, run_dir / "server.stdout.log", run_dir / "server.stderr.log"),
        "client_a": ProcessSpec("client_a", client_a_cmd, Path(args.client_a_cwd), run_dir / "client_a.stdout.log", run_dir / "client_a.stderr.log"),
        "client_b": ProcessSpec("client_b", client_b_cmd, Path(args.client_b_cwd), run_dir / "client_b.stdout.log", run_dir / "client_b.stderr.log"),
    }
    for spec in specs.values():
        log(f"{spec.name} cwd={spec.cwd}")
        log(f"{spec.name} stdout={spec.stdout_path} stderr={spec.stderr_path}")

    procs: dict[str, subprocess.Popen] = {}
    try:
        procs["server"] = start_process(specs["server"])
        time.sleep(args.server_start_delay)
        if procs["server"].poll() is not None:
            log_process_logs(specs["server"])
            raise RuntimeError(f"server exited early, see {specs['server'].stderr_path}")
        procs["client_a"] = start_process(specs["client_a"])
        time.sleep(args.client_start_gap)
        procs["client_b"] = start_process(specs["client_b"])

        wait_for_match_server(
            procs["server"],
            {"client_a": procs["client_a"], "client_b": procs["client_b"]},
            specs,
            args,
        )

        for name in ("client_a", "client_b"):
            proc = procs[name]
            if proc.poll() is None:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    wait_process(proc, 10, name)
            else:
                close_process_files(proc)
                log(f"{name} exited code={proc.returncode}")
                if proc.returncode:
                    log_process_logs(specs[name])

        replay_source = newest_replay(server_log_dir)
        replay_target = replay_dir / f"match_{match_index:04d}_{replay_source.name}"
        shutil.copy2(replay_source, replay_target)
        client_a_done = replay_dir / f"{replay_target.stem}.client_a.done"
        client_b_done = replay_dir / f"{replay_target.stem}.client_b.done"
        manifest_path = replay_dir / f"{replay_target.stem}.manifest.json"
        for stale_done in (client_a_done, client_b_done):
            if stale_done.exists():
                stale_done.unlink()
        artifacts = MatchArtifacts(
            match_index=match_index,
            run_id=run_id,
            run_dir=run_dir,
            port=port,
            replay_source=replay_source,
            replay_target=replay_target,
            manifest_path=manifest_path,
            client_a_done=client_a_done,
            client_b_done=client_b_done,
        )
        write_manifest(artifacts, args)
        log(f"replay copied to {replay_target}")
        log(f"manifest written to {manifest_path}")
        if not args.no_wait:
            run_analysis_commands(artifacts, args)
        return artifacts
    finally:
        for name, proc in procs.items():
            terminate_process_tree(proc, name)


def parse_bool(value: object, key: str, parser: argparse.ArgumentParser) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    parser.error(f"config key {key!r} must be boolean")
    raise AssertionError("unreachable")


def coerce_config_value(key: str, value: object, parser: argparse.ArgumentParser) -> object:
    try:
        if key in INT_KEYS:
            if isinstance(value, bool):
                raise ValueError
            return int(value)
        if key in FLOAT_KEYS:
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if key in BOOL_KEYS:
            return parse_bool(value, key, parser)
        return "" if value is None else str(value)
    except (TypeError, ValueError):
        parser.error(f"config key {key!r} has invalid value: {value!r}")
        raise AssertionError("unreachable")


def load_config(path: str, parser: argparse.ArgumentParser) -> dict[str, object]:
    if not path:
        return {}
    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        parser.error(f"config file not found: {config_path}")
    except json.JSONDecodeError as exc:
        parser.error(f"config file is not valid JSON: {config_path}: {exc}")
    if not isinstance(data, dict):
        parser.error(f"config file root must be a JSON object: {config_path}")

    values: dict[str, object] = {}
    for raw_key, raw_value in data.items():
        key = str(raw_key).replace("-", "_")
        if key not in DEFAULTS:
            parser.error(f"unknown config key: {raw_key!r}")
        values[key] = coerce_config_value(key, raw_value, parser)
    return values


def add_argument(
    parser: argparse.ArgumentParser,
    *flags: str,
    **kwargs: object,
) -> None:
    kwargs.setdefault("default", argparse.SUPPRESS)
    parser.add_argument(*flags, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repeated server/client matches and wait for replay analysis markers.")
    parser.add_argument("--config", default="", help="JSON config file; CLI options override config values")
    add_argument(parser, "--client-a-cmd", help="command template for client A")
    add_argument(parser, "--client-b-cmd", help="command template for client B")
    add_argument(parser, "--client-a-cwd", help="working directory for client A")
    add_argument(parser, "--client-b-cwd", help="working directory for client B")
    add_argument(parser, "--client-a-player-id")
    add_argument(parser, "--client-b-player-id")
    add_argument(parser, "--client-a-analysis-cmd", help="optional command template run after replay is copied; exit code 0 writes client A done marker")
    add_argument(parser, "--client-b-analysis-cmd", help="optional command template run after replay is copied; exit code 0 writes client B done marker")
    add_argument(parser, "--client-a-analysis-cwd", help="working directory for client A analysis command; defaults to client A cwd")
    add_argument(parser, "--client-b-analysis-cwd", help="working directory for client B analysis command; defaults to client B cwd")
    add_argument(parser, "--replay-out-dir", help="directory where replay and manifest files are copied")
    add_argument(parser, "--run-root", help="directory for raw per-match logs")
    add_argument(parser, "--host")
    add_argument(parser, "--port", type=int, help="fixed port; 0 chooses a free port per match")
    add_argument(parser, "--tick-ms", type=int)
    add_argument(parser, "--duration-round", type=int)
    add_argument(parser, "--seed", type=int)
    add_argument(parser, "--max-matches", type=int, help="0 means infinite loop")
    add_argument(parser, "--start-index", type=int)
    add_argument(parser, "--match-timeout", type=float)
    add_argument(parser, "--analysis-timeout", type=float, help="0 means wait forever")
    add_argument(parser, "--poll-seconds", type=float)
    add_argument(parser, "--server-start-delay", type=float)
    add_argument(parser, "--client-start-gap", type=float)
    add_argument(parser, "--status-interval", type=float, help="seconds between match status logs; 0 disables periodic status")
    add_argument(parser, "--stop-file", help="if this file exists, stop before starting or while waiting")
    add_argument(parser, "--no-wait", action="store_true", help="do not wait for analysis markers")
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    required = ["client_a_cmd", "client_b_cmd", "replay_out_dir"]
    missing = [key for key in required if not str(getattr(args, key, "")).strip()]
    if missing:
        parser.error("missing required options: " + ", ".join(f"--{key.replace('_', '-')}" for key in missing))
    if args.tick_ms <= 0:
        parser.error("--tick-ms must be positive")
    if args.duration_round <= 0:
        parser.error("--duration-round must be positive")
    if args.max_matches < 0:
        parser.error("--max-matches must be >= 0")
    if args.start_index <= 0:
        parser.error("--start-index must be positive")
    if args.match_timeout <= 0:
        parser.error("--match-timeout must be positive")
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    if args.status_interval < 0:
        parser.error("--status-interval must be >= 0")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = build_parser()
    cli_args = parser.parse_args(argv)
    merged = dict(DEFAULTS)
    merged.update(load_config(cli_args.config, parser))
    merged.update({key: value for key, value in vars(cli_args).items() if key != "config"})
    merged["config"] = cli_args.config
    args = argparse.Namespace(**merged)
    validate_args(args, parser)
    return args


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.config:
        log(f"config={args.config}")
    log(
        "settings "
        f"clientA={args.client_a_player_id} clientB={args.client_b_player_id} "
        f"max_matches={args.max_matches} tick_ms={args.tick_ms} "
        f"duration_round={args.duration_round} status_interval={args.status_interval}"
    )
    match_index = args.start_index
    completed = 0
    try:
        while args.max_matches <= 0 or completed < args.max_matches:
            if args.stop_file and Path(args.stop_file).exists():
                log(f"stop file exists before next match: {args.stop_file}")
                break
            log(f"starting match index={match_index}")
            artifacts = run_one_match(match_index, args)
            wait_for_analysis(artifacts, args)
            match_index += 1
            completed += 1
    except KeyboardInterrupt as exc:
        log(f"stopped: {exc}")
        return 130
    except Exception as exc:
        log(f"failed: {exc}")
        return 1
    log(f"done completed={completed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
