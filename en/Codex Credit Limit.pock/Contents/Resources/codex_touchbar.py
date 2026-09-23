#!/usr/bin/python3
"""Backend shared by the Pock/BTT widgets for Codex quota and task status."""

from __future__ import annotations

__author__ = "jtan289"
__copyright__ = "Copyright (c) 2026 jtan289"
__license__ = "MIT"

import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import time


APP_CANDIDATES = (
    "/Applications/ChatGPT.app/Contents/Resources/codex",
    "/Applications/Codex.app/Contents/Resources/codex",
)
CACHE_DIR = Path(
    os.environ.get(
        "CODEX_TOUCHBAR_CACHE_DIR",
        str(Path.home() / "Library" / "Caches" / "CodexTouchBar"),
    )
)
CACHE_FILE = CACHE_DIR / "last-rate-limits.json"
LOCK_FILE = CACHE_DIR / "refresh.lock"
WIDGET_IMAGE = CACHE_DIR / "widget.png"
SESSION_DIR = Path.home() / ".codex" / "sessions"
RENDERER = Path(__file__).with_name("codex_touchbar_render")
BAR_WIDTH = 12
ICON_CANDIDATES = (
    str(Path(__file__).with_name("codex-icon.png")),
    "/Applications/ChatGPT.app/Contents/Resources/icon-codex-light.png",
    "/Applications/Codex.app/Contents/Resources/icon-codex-light.png",
)
THREAD_SOURCE_KINDS = ("cli", "vscode", "exec", "appServer", "unknown")
FAST_CACHE_STALE_AFTER = 120
FIVE_HOUR_WINDOW_MINS = 300
WEEKLY_WINDOW_MINS = 10080


def find_codex() -> str:
    for candidate in APP_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    executable = shutil.which("codex")
    if executable:
        return executable
    raise FileNotFoundError("Codex CLI not found")


def send(process: subprocess.Popen[str], message: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def wait_for_response(
    process: subprocess.Popen[str], request_id: int, timeout: float
) -> dict:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            events = selector.select(max(0.0, deadline - time.monotonic()))
            if not events:
                break
            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(str(message["error"]))
                return message.get("result", {})
    finally:
        selector.close()
    raise TimeoutError(f"Codex request {request_id} timed out")


def last_task_event(path: Path) -> str | None:
    """Read a JSONL file backwards and return its latest task lifecycle event.

    Search the serialized event envelope directly.  Some Codex log records are
    several megabytes long, so rebuilding/parsing lines while walking backwards
    can make a five-second status check take several seconds.
    """
    markers = {
        b'"type":"event_msg","payload":{"type":"task_started"': "task_started",
        b'"type":"event_msg","payload":{"type":"task_complete"': "task_complete",
    }
    overlap_size = max(len(marker) for marker in markers) - 1
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            suffix = b""
            while position > 0:
                read_size = min(65536, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size) + suffix
                latest_index = -1
                latest_event = None
                for marker, event_type in markers.items():
                    marker_index = chunk.rfind(marker)
                    if marker_index > latest_index:
                        latest_index = marker_index
                        latest_event = event_type
                if latest_event is not None:
                    return latest_event
                suffix = chunk[:overlap_size]
    except OSError:
        pass
    return None


def active_thread_ids_from_logs() -> set[str]:
    """Find active root tasks without counting internal subagent sessions."""
    active_ids: set[str] = set()
    today = dt.date.today()
    cutoff = time.time() - 3 * 86400
    for offset in range(3):
        day = today - dt.timedelta(days=offset)
        day_dir = SESSION_DIR / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        try:
            candidates = day_dir.glob("*.jsonl")
        except OSError:
            continue
        for path in candidates:
            try:
                if path.stat().st_mtime < cutoff:
                    continue
                with path.open("r", encoding="utf-8") as handle:
                    metadata = json.loads(handle.readline())
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if metadata.get("type") != "session_meta":
                continue
            payload = metadata.get("payload") or {}
            source = payload.get("source")
            if payload.get("parent_thread_id") is not None:
                continue
            if isinstance(source, dict) and "subagent" in source:
                continue
            thread_id = payload.get("id")
            if isinstance(thread_id, str) and last_task_event(path) == "task_started":
                active_ids.add(thread_id)
    return active_ids


def fetch_dashboard(include_running_count: bool = True) -> tuple[dict, int]:
    codex = find_codex()
    commands = (
        [codex, "app-server", "proxy"],
        [codex, "app-server", "--stdio"],
    )
    last_error: Exception | None = None

    for command in commands:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        try:
            send(
                process,
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "codex-touchbar",
                            "version": "1.1.0",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                },
            )
            wait_for_response(process, 1, 8.0)
            send(process, {"method": "initialized"})
            send(
                process,
                {
                    "id": 2,
                    "method": "account/rateLimits/read",
                    "params": {"excludeResetCreditDetails": True},
                },
            )
            result = wait_for_response(process, 2, 12.0)
            by_id = result.get("rateLimitsByLimitId") or {}
            snapshot = by_id.get("codex") or result.get("rateLimits")
            if not isinstance(snapshot, dict):
                raise RuntimeError("Codex returned no rate-limit snapshot")

            running_count = 0
            if include_running_count:
                active_thread_ids: set[str] = set()
                try:
                    send(
                        process,
                        {
                            "id": 3,
                            "method": "thread/list",
                            "params": {
                                "limit": 100,
                                "sortKey": "updated_at",
                                "sortDirection": "desc",
                                "sourceKinds": list(THREAD_SOURCE_KINDS),
                            },
                        },
                    )
                    thread_result = wait_for_response(process, 3, 8.0)
                    threads = thread_result.get("data") or []
                    for thread in threads:
                        if not isinstance(thread, dict):
                            continue
                        status = thread.get("status")
                        thread_id = thread.get("id")
                        if (
                            isinstance(status, dict)
                            and status.get("type") == "active"
                            and isinstance(thread_id, str)
                        ):
                            active_thread_ids.add(thread_id)
                except Exception:
                    pass

                active_thread_ids.update(active_thread_ids_from_logs())
                running_count = len(active_thread_ids)

            return snapshot, running_count
        except Exception as error:
            last_error = error
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()

    if last_error is not None:
        raise last_error
    raise RuntimeError("Unable to start Codex App Server")


def read_cache_payload() -> tuple[dict | None, int | None]:
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        snapshot = payload.get("snapshot")
        saved_at = payload.get("savedAt")
        if not isinstance(snapshot, dict):
            snapshot = None
        if not isinstance(saved_at, int):
            saved_at = None
        return snapshot, saved_at
    except (OSError, ValueError, AttributeError):
        return None, None


def read_cache() -> dict | None:
    return read_cache_payload()[0]


def write_cache(snapshot: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"savedAt": int(time.time()), "snapshot": snapshot}
    temp_file = CACHE_FILE.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp_file.replace(CACHE_FILE)


def format_countdown(timestamp: object) -> str:
    if not isinstance(timestamp, (int, float)):
        return "--"
    seconds = max(0, int(timestamp - time.time()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


def format_reset_clock(timestamp: object) -> str:
    if not isinstance(timestamp, (int, float)):
        return "--:--"
    return time.strftime("%H:%M", time.localtime(timestamp))


def progress_bar(used: int) -> str:
    filled = round(BAR_WIDTH * used / 100)
    empty = BAR_WIDTH - filled
    return "▰" * filled + "▱" * empty


def remaining_percent(window: dict) -> int:
    used = max(0, min(100, int(window.get("usedPercent", 0))))
    return 100 - used


def display_percent(window: dict, display_mode: str) -> int:
    used = max(0, min(100, int(window.get("usedPercent", 0))))
    return used if display_mode == "used" else 100 - used


def window_duration(window: dict) -> int | None:
    value = window.get("windowDurationMins")
    if isinstance(value, (int, float)):
        return int(value)
    return None


def classify_windows(snapshot: dict) -> tuple[dict | None, dict | None]:
    """Return five-hour and weekly windows without duplicating a lone window."""
    named_windows = [
        (name, value)
        for name, value in (
            ("primary", snapshot.get("primary")),
            ("secondary", snapshot.get("secondary")),
        )
        if isinstance(value, dict)
    ]
    if not named_windows:
        return None, None

    primary = next(
        (
            value
            for _, value in named_windows
            if window_duration(value) == FIVE_HOUR_WINDOW_MINS
        ),
        None,
    )
    weekly = next(
        (
            value
            for _, value in named_windows
            if window_duration(value) == WEEKLY_WINDOW_MINS
        ),
        None,
    )

    unassigned = [
        (name, value)
        for name, value in named_windows
        if value is not primary and value is not weekly
    ]
    if primary is None:
        primary = next(
            (
                value
                for _, value in unassigned
                if (window_duration(value) or sys.maxsize) < 1440
            ),
            None,
        )
    if weekly is None:
        weekly = next(
            (
                value
                for _, value in unassigned
                if (window_duration(value) or 0) >= 1440
            ),
            None,
        )

    remaining = [
        (name, value)
        for name, value in unassigned
        if value is not primary and value is not weekly
    ]
    if primary is None:
        primary = next((value for name, value in remaining if name == "primary"), None)
    if weekly is None:
        weekly = next((value for name, value in remaining if name == "secondary"), None)
    return primary, weekly


def render(
    snapshot: dict,
    stale: bool = False,
    show_reset: bool = True,
    display_mode: str = "remaining",
) -> str:
    primary, weekly = classify_windows(snapshot)
    if primary is None and weekly is None:
        raise RuntimeError("No usage windows found")

    warning = " ⚠" if stale else ""
    rows: list[str] = []
    if primary is not None:
        percent = display_percent(primary, display_mode)
        reset = (
            f"  ↻{format_reset_clock(primary.get('resetsAt'))}{warning}"
            if show_reset
            else ""
        )
        rows.append(f"5h    {progress_bar(percent)} {percent}%{reset}")
    if weekly is not None:
        percent = display_percent(weekly, display_mode)
        reset = (
            f"  ↻{format_countdown(weekly.get('resetsAt'))}{warning}"
            if show_reset
            else ""
        )
        rows.append(f"7d    {progress_bar(percent)} {percent}%{reset}")
    return "\n".join(rows)


def find_icon() -> str:
    for candidate in ICON_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError("Codex light icon not found")


def render_widget_image(
    snapshot: dict,
    stale: bool,
    running_count: int,
    show_reset: bool,
    display_mode: str,
    widget_width: float,
    progress_length: float,
    progress_color: str,
) -> Path:
    primary, weekly = classify_windows(snapshot)
    if primary is None and weekly is None:
        raise RuntimeError("No usage windows found")
    layout = "both" if primary is not None and weekly is not None else (
        "primary" if primary is not None else "weekly"
    )
    subprocess.run(
        [
            str(RENDERER),
            str(WIDGET_IMAGE),
            find_icon(),
            str(display_percent(primary, display_mode)) if primary is not None else "0",
            str(display_percent(weekly, display_mode)) if weekly is not None else "0",
            format_reset_clock(primary.get("resetsAt")) if primary is not None else "--:--",
            format_countdown(weekly.get("resetsAt")) if weekly is not None else "--",
            str(max(0, running_count)),
            "1" if stale else "0",
            layout,
            "1" if show_reset else "0",
            f"{widget_width:.0f}",
            f"{progress_length:.0f}",
            progress_color,
            str(remaining_percent(primary)) if primary is not None else "0",
            str(remaining_percent(weekly)) if weekly is not None else "0",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
    return WIDGET_IMAGE


def btt_result(text: str, error: bool = False, icon_path: Path | None = None) -> str:
    result = {
        "text": text,
        "background_color": "0,0,0,255",
        "font_color": "255,255,255,255" if not error else "255,180,60,255",
        "font_size": 10,
    }
    if icon_path is not None:
        result["text"] = "\u200b"
        result["icon_path"] = str(icon_path)
    return json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def local_running_count() -> int:
    try:
        return len(active_thread_ids_from_logs())
    except Exception:
        return 0


def output_widget(
    snapshot: dict | None,
    stale: bool,
    running_count: int,
    show_reset: bool,
    display_mode: str,
    widget_width: float,
    progress_length: float,
    progress_color: str,
) -> bool:
    if not snapshot:
        return False
    try:
        image_path = render_widget_image(
            snapshot,
            stale=stale,
            running_count=running_count,
            show_reset=show_reset,
            display_mode=display_mode,
            widget_width=widget_width,
            progress_length=progress_length,
            progress_color=progress_color,
        )
        print(btt_result("", icon_path=image_path))
        return True
    except Exception:
        try:
            print(
                btt_result(
                    render(
                        snapshot,
                        stale=stale,
                        show_reset=show_reset,
                        display_mode=display_mode,
                    )
                )
            )
            return True
        except Exception:
            return False


def option_value(name: str, default: str) -> str:
    try:
        index = sys.argv.index(name)
        return sys.argv[index + 1]
    except (ValueError, IndexError):
        return default


def option_bool(name: str, default: bool) -> bool:
    value = option_value(name, "1" if default else "0").strip().lower()
    return value not in {"0", "false", "no", "off"}


def option_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(option_value(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def main() -> None:
    language = option_value("--language", "zh-Hans")
    unavailable_message = (
        "Codex quota temporarily unavailable"
        if language == "en"
        else "Codex 额度暂不可用"
    )
    show_badge = option_bool("--show-badge", True)
    show_reset = option_bool("--show-reset", True)
    display_mode = option_value("--display-mode", "remaining")
    if display_mode not in {"remaining", "used"}:
        display_mode = "remaining"
    widget_width = option_float("--widget-width", 153, 140, 240)
    progress_length = option_float("--progress-length", 44, 25, 132)
    progress_color = option_value("--progress-color", "adaptive")
    if progress_color not in {"adaptive", "green", "blue", "purple", "orange", "red"}:
        progress_color = "adaptive"

    if "--cache-only" in sys.argv[1:]:
        snapshot, saved_at = read_cache_payload()
        stale = saved_at is None or time.time() - saved_at > FAST_CACHE_STALE_AFTER
        running_count = local_running_count() if show_badge else 0
        if output_widget(
            snapshot,
            stale=stale,
            running_count=running_count,
            show_reset=show_reset,
            display_mode=display_mode,
            widget_width=widget_width,
            progress_length=progress_length,
            progress_color=progress_color,
        ):
            return
        print(btt_result(unavailable_message, error=True))
        return

    stale = False
    snapshot = None
    running_count = 0
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        lock_context = LOCK_FILE.open("a+", encoding="utf-8")
    except OSError:
        lock_context = None

    if lock_context is None:
        try:
            snapshot, running_count = fetch_dashboard(include_running_count=show_badge)
        except Exception:
            snapshot = read_cache()
            running_count = local_running_count() if show_badge else 0
            stale = True
    else:
        with lock_context as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                snapshot, running_count = fetch_dashboard(include_running_count=show_badge)
                write_cache(snapshot)
            except BlockingIOError:
                snapshot = read_cache()
                running_count = local_running_count() if show_badge else 0
                stale = True
            except Exception:
                snapshot = read_cache()
                running_count = local_running_count() if show_badge else 0
                stale = True

    if output_widget(
        snapshot,
        stale=stale,
        running_count=running_count,
        show_reset=show_reset,
        display_mode=display_mode,
        widget_width=widget_width,
        progress_length=progress_length,
        progress_color=progress_color,
    ):
        return
    print(btt_result(unavailable_message, error=True))


if __name__ == "__main__":
    main()
