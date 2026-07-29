#!/usr/bin/env python3
"""Scheduled rotation of the verb-themes spinner verb pack.

Two modes:

  hook mode (no arguments)
      Run from the plugin's SessionStart hook. Exits silently and changes
      nothing unless the user has turned rotation on. When rotation IS on it
      does two independent things, in this order:
        1. announces the pack that is live in THIS session, then
        2. picks the next pack if the schedule says one is due.
      The order matters: Claude Code reads settings.json once at startup and
      memoises it, so a pack written here is not live until the next session.
      Announcing first is what makes the message land in the session where the
      verbs actually changed.

  CLI mode (--enable / --disable / --rotate-now / --touch / --status)
      Driven by the /verb-themes schedule wizard. Prints a JSON summary on
      stdout so the command can report it back to the user. Keeping all
      settings writes in here means the locking is in one place.
"""

import argparse
import contextlib
import fcntl
import glob
import json
import os
import random
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
SETTINGS_PATH = os.path.join(CLAUDE_DIR, "settings.json")
STATE_PATH = os.path.join(CLAUDE_DIR, "verb-themes-state.json")
LOCK_PATH = os.path.join(CLAUDE_DIR, "verb-themes.lock")

NAMED_INTERVALS = {
    "session": timedelta(0),
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}
UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


class Busy(Exception):
    """Another instance holds the lock; it is doing the work for us."""


# --- small helpers -----------------------------------------------------------


def now_utc():
    return datetime.now(timezone.utc)


def to_iso(dt, precise=False):
    """Second precision for display; sub-second where ordering matters."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ" if precise else "%Y-%m-%dT%H:%M:%SZ")


def from_iso(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_interval(value):
    """'daily', '6h', '90m'… -> timedelta. Raises ValueError on anything else."""
    key = str(value or "").strip().lower()
    if key in NAMED_INTERVALS:
        return NAMED_INTERVALS[key]
    match = re.fullmatch(r"(\d+)\s*([mhdw])", key)
    if not match:
        raise ValueError(
            "interval must be session, hourly, daily, weekly, or a number "
            "followed by m/h/d/w (e.g. 6h, 3d)"
        )
    return timedelta(**{UNITS[match.group(2)]: int(match.group(1))})


def plugin_root():
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env and os.path.isdir(os.path.join(env, "themes")):
        return env
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_themes():
    """name -> theme dict, skipping anything that will not parse."""
    themes = {}
    for path in sorted(glob.glob(os.path.join(plugin_root(), "themes", "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                theme = json.load(handle)
        except (OSError, ValueError):
            continue
        name = theme.get("name")
        if isinstance(name, str) and isinstance(theme.get("verbs"), list) and theme["verbs"]:
            themes[name] = theme
    return themes


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return default
    return value if isinstance(value, dict) else default


def detect_indent(raw):
    """Match the file's existing indentation so we do not reflow it needlessly."""
    for line in raw.split("\n")[1:]:
        stripped = line.lstrip(" ")
        if stripped.startswith('"') and len(line) > len(stripped):
            return len(line) - len(stripped)
    return 2


def write_json_atomic(path, data, indent=2):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, prefix=".verb-themes-", suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(data, handle, indent=indent, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(handle.name)
        raise


@contextlib.contextmanager
def exclusive_lock(timeout=2.0):
    """Serialise rotation across concurrent Claude Code sessions.

    Non-blocking with a short retry budget: a stuck holder must never stall a
    session start. A loser that gives up has nothing to do anyway — the winner
    advances the timestamps it would have written.
    """
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise Busy()
                time.sleep(0.05)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# --- state / settings --------------------------------------------------------


def get_rotation(state):
    rotation = state.get("rotation")
    return dict(rotation) if isinstance(rotation, dict) else {}


def save_state(state, rotation):
    state["rotation"] = rotation
    state["updatedAt"] = to_iso(now_utc())
    write_json_atomic(STATE_PATH, state)


def apply_pack(theme, mode):
    """Write one pack's verbs into settings.json, touching only spinnerVerbs.

    Re-reads the file immediately before writing (we are inside the lock) so the
    window in which a concurrent writer could be clobbered is as small as we can
    make it.
    """
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            raw = handle.read()
        settings = json.loads(raw)
        indent = detect_indent(raw)
    except (OSError, ValueError):
        settings, indent = {}, 2
    if not isinstance(settings, dict):
        settings, indent = {}, 2

    seen, verbs = set(), []
    for verb in theme["verbs"]:
        if isinstance(verb, str) and verb.strip() and verb.lower() not in seen:
            seen.add(verb.lower())
            verbs.append(verb)

    settings["spinnerVerbs"] = {"mode": mode, "verbs": verbs}
    write_json_atomic(SETTINGS_PATH, settings, indent=indent)
    return verbs


def candidate_names(rotation, themes):
    pool = [name for name in rotation.get("pool") or [] if name in themes]
    return pool or sorted(themes)


def is_due(rotation, at=None):
    try:
        interval = parse_interval(rotation.get("interval", "daily"))
    except ValueError:
        interval = NAMED_INTERVALS["daily"]
    last = from_iso(rotation.get("lastRotatedAt"))
    if last is None or not interval:
        return True
    return (at or now_utc()) >= last + interval


def next_due(rotation):
    try:
        interval = parse_interval(rotation.get("interval", "daily"))
    except ValueError:
        return None
    last = from_iso(rotation.get("lastRotatedAt"))
    if last is None or not interval:
        return None
    return to_iso(last + interval)


def rotate(state, rotation, themes):
    """Pick the next pack and write it. Returns the chosen theme."""
    names = candidate_names(rotation, themes)
    if len(names) > 1 and rotation.get("lastPack") in names:
        names = [name for name in names if name != rotation["lastPack"]]
    theme = themes[random.choice(names)]

    mode = state.get("mode") if state.get("mode") in ("append", "replace") else "append"
    verbs = apply_pack(theme, mode)

    state["activeThemes"] = [theme["name"]]
    state["mode"] = mode
    rotation["lastPack"] = theme["name"]
    rotation["lastRotatedAt"] = to_iso(now_utc(), precise=True)
    return theme, verbs, mode


def describe(theme, verbs=None, mode=None, extra=None):
    verbs = verbs if verbs is not None else theme["verbs"]
    summary = {
        "name": theme["name"],
        "title": theme.get("title", theme["name"]),
        "emoji": theme.get("emoji", "🌀"),
        "description": theme.get("description", ""),
        "verbCount": len(verbs),
        "samples": random.sample(verbs, min(5, len(verbs))),
    }
    if mode:
        summary["mode"] = mode
    if extra:
        summary.update(extra)
    return summary


# --- hook mode ---------------------------------------------------------------


def announce(theme):
    message = (
        "The verb-themes plugin rotated your spinner verb pack on schedule. "
        "Live in this session: {emoji} {title} — {description} "
        "Sample verbs: {samples}. "
        "Before anything else in your first reply, tell the user about it in one "
        "short playful line (include the emoji and pack title), then carry on with "
        "whatever they asked. Do not repeat it later in the session. "
        "`/verb-themes schedule off` stops the rotation."
    ).format(
        emoji=theme.get("emoji", "🌀"),
        title=theme.get("title", theme["name"]),
        description=theme.get("description", ""),
        samples=", ".join(random.sample(theme["verbs"], min(3, len(theme["verbs"])))),
    )
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


def run_hook():
    # Taken before anything else, so it is reliably earlier than any rotation
    # written by a session that started alongside this one. See the announce
    # guard below.
    started = now_utc()

    # Cheap unlocked pre-check: the overwhelming majority of sessions belong to
    # users who never turned rotation on, and they should pay nothing for it.
    if not get_rotation(read_json(STATE_PATH, {})).get("enabled"):
        return

    themes = load_themes()
    if not themes:
        return

    to_announce = None
    # Short budget: a session start must never stall behind a stuck lock. If we
    # lose, another session is already doing this work and we have nothing to do.
    with exclusive_lock(timeout=0.25):
        state = read_json(STATE_PATH, {})
        rotation = get_rotation(state)
        if not rotation.get("enabled"):
            return

        # 1. Announce what is live right now. settings.json was read and cached
        #    by Claude Code before this hook ran, so the pack recorded in state
        #    is the one this session is actually using -- unless it was written
        #    after we started, which happens when two sessions launch at once
        #    and one of them wins the lock first. That pack is not live here
        #    either, so leave it for the next session to announce.
        live = rotation.get("lastPack")
        rotated_at = from_iso(rotation.get("lastRotatedAt"))
        if (
            live
            and live in themes
            and live != rotation.get("lastAnnouncedPack")
            and (rotated_at is None or rotated_at < started)
        ):
            to_announce = themes[live]
            rotation["lastAnnouncedPack"] = live

        # 2. Then queue up the next one, which becomes live next session.
        rotated = is_due(rotation) and rotate(state, rotation, themes)

        if to_announce or rotated:
            save_state(state, rotation)

    if to_announce:
        announce(to_announce)


# --- CLI mode ----------------------------------------------------------------


def emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def status_payload(state, rotation, themes, extra=None):
    live = rotation.get("lastPack")
    payload = {
        "ok": True,
        "enabled": bool(rotation.get("enabled")),
        "interval": rotation.get("interval", "daily"),
        "pool": [name for name in rotation.get("pool") or [] if name in themes],
        "mode": state.get("mode", "append"),
        "lastRotatedAt": rotation.get("lastRotatedAt"),
        "nextDueAt": next_due(rotation) if rotation.get("enabled") else None,
        "currentPack": describe(themes[live]) if live in themes else None,
    }
    if extra:
        payload.update(extra)
    return payload


def cmd_status(args, themes):
    state = read_json(STATE_PATH, {})
    return status_payload(state, get_rotation(state), themes)


def cmd_enable(args, themes):
    interval = parse_interval(args.interval)  # validated before we touch state
    pool = [name.strip() for name in (args.pool or "").split(",") if name.strip()]
    unknown = [name for name in pool if name not in themes]
    if unknown:
        raise ValueError("unknown theme(s): " + ", ".join(unknown))

    with exclusive_lock():
        state = read_json(STATE_PATH, {})
        rotation = get_rotation(state)
        rotation.update({"enabled": True, "interval": str(args.interval).strip().lower(), "pool": pool})
        # Pick one straight away so turning it on visibly does something.
        theme, verbs, mode = rotate(state, rotation, themes)
        save_state(state, rotation)
    return status_payload(
        state, rotation, themes, {"justApplied": describe(theme, verbs, mode), "intervalSeconds": int(interval.total_seconds())}
    )


def cmd_rotate_now(args, themes):
    with exclusive_lock():
        state = read_json(STATE_PATH, {})
        rotation = get_rotation(state)
        theme, verbs, mode = rotate(state, rotation, themes)
        save_state(state, rotation)
    return status_payload(state, rotation, themes, {"justApplied": describe(theme, verbs, mode)})


def cmd_disable(args, themes):
    with exclusive_lock():
        state = read_json(STATE_PATH, {})
        rotation = get_rotation(state)
        rotation["enabled"] = False
        save_state(state, rotation)
    return status_payload(state, rotation, themes)


def cmd_touch(args, themes):
    """Reset the schedule clock after the user picked packs by hand.

    Stops the next session start from overwriting a deliberate choice, and drops
    any pending announcement (they just saw what they chose). lastPack is kept
    rather than cleared, so the next rotation still avoids repeating it.
    """
    with exclusive_lock():
        state = read_json(STATE_PATH, {})
        rotation = get_rotation(state)
        if not rotation:
            return {"ok": True, "enabled": False}
        rotation["lastRotatedAt"] = to_iso(now_utc(), precise=True)
        rotation["lastAnnouncedPack"] = rotation.get("lastPack")
        save_state(state, rotation)
    return status_payload(state, rotation, themes)


COMMANDS = {
    "status": cmd_status,
    "enable": cmd_enable,
    "rotate_now": cmd_rotate_now,
    "disable": cmd_disable,
    "touch": cmd_touch,
}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_const", const="status", dest="cmd")
    group.add_argument("--enable", action="store_const", const="enable", dest="cmd")
    group.add_argument("--disable", action="store_const", const="disable", dest="cmd")
    group.add_argument("--rotate-now", action="store_const", const="rotate_now", dest="cmd")
    group.add_argument("--touch", action="store_const", const="touch", dest="cmd")
    parser.add_argument("--interval", default="daily", help="session|hourly|daily|weekly|<N>[mhdw]")
    parser.add_argument("--pool", default="", help="comma-separated theme names; empty means all")
    args = parser.parse_args(argv)

    if args.cmd is None:
        # Hook mode. Never let a bad state file or a stray exception put noise in
        # front of a user who may not even use this feature.
        try:
            run_hook()
        except Busy:
            pass
        except Exception:
            pass
        return 0

    themes = load_themes()
    if not themes:
        emit({"ok": False, "error": "no theme packs found in the plugin's themes/ directory"})
        return 1
    try:
        emit(COMMANDS[args.cmd](args, themes))
    except Busy:
        emit({"ok": False, "error": "another Claude Code session is updating the rotation; try again"})
        return 1
    except (ValueError, OSError) as exc:
        emit({"ok": False, "error": str(exc)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
