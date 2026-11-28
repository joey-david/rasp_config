"""Scripted benchmark procedures for tuning find, lock-on, follow, and power gauge."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

from skills import find as find_skill
from skills import follow as follow_skill
from skills import lock_on as lock_skill
from skills.runtime import SkillStatus, timed_velocity, turn_bounds

LOG_PATH = Path(
    os.environ.get(
        "PROCEDURE_LOG_FILE",
        Path.home() / ".local" / "state" / "mischief-bot" / "procedures.jsonl",
    )
)

PROCEDURES = [
    {
        "id": "power_gauge",
        "title": "1. Power Gauge",
        "setup": "Place robot on the flat table with ~20 cm spin clearance and stay still.",
        "steps": [
            "Ramp alternating in-place micro-turns from 15% until visual odometry sees rotation.",
            "Confirm both turn directions and save the minimum power floor.",
        ],
    },
    {
        "id": "find_bench",
        "title": "2. Find Person (Turn Away + Search)",
        "setup": "Sit at the far end of the table (~1–2 m away) facing the robot.",
        "steps": [
            "Turn the robot ~120° away from you in place.",
            "Run find(target) to scan back and center on you.",
            "Record search duration, scan cycles, and final offset.",
        ],
    },
    {
        "id": "lock_bench",
        "title": "3. Lock-On Tracking (8 s)",
        "setup": "Sit facing the robot. After 2 s, lean left, pause 2 s, then lean right.",
        "steps": [
            "Run lock_on(target) for 8 s while logging offset and turn commands.",
            "Compute mean offset, direction reversals, and seen rate.",
        ],
    },
    {
        "id": "follow_bench",
        "title": "4. Follow Approach (6 s, Edge-Safe)",
        "setup": "Place robot at the far end of the clear table facing you (~1–2 m). Keep a hand ready near edges.",
        "steps": [
            "Check that Level 0 edge safety is ready and clear.",
            "Run follow(target) for 6 s while logging pulses, reversals, and vetoes.",
            "Report height progress, pulse counts, and any safety vetoes.",
        ],
    },
    {
        "id": "full_suite",
        "title": "5. Full Suite (Gauge → Find → Lock → Follow)",
        "setup": "Robot at far end of the clear table facing you (~1–2 m). Stay still for Gauge, lean left/right in Lock, guard edges in Follow.",
        "steps": [
            "Calibrate minimum breakaway power.",
            "Turn away and run find(target).",
            "Track with lock_on(target) for 6 s.",
            "Approach with follow(target) for 6 s.",
        ],
    },
]

_BY_ID = {p["id"]: p for p in PROCEDURES}
_stop = threading.Event()
_state = SkillStatus({"running": False})


def list_procedures() -> list[dict]:
    return [dict(p) for p in PROCEDURES]


def _append_log(record: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        print(f"[procedure] log write failed: {exc}", flush=True)


def _step_power_gauge(robot) -> dict:
    started = time.monotonic()
    out = robot.calibrate_power()
    elapsed = round(time.monotonic() - started, 2)
    return {
        "step": "power_gauge",
        "ok": bool(out.get("ok")),
        "elapsed_s": elapsed,
        "breakaway_turn": out.get("breakaway_turn"),
        "min_turn": out.get("min_turn"),
        "trials": len(out.get("trials") or []),
        "error": out.get("error") or "",
        "summary": (
            f"breakaway {out.get('breakaway_turn')}% -> min {out.get('min_turn')}% ({elapsed}s)"
            if out.get("ok")
            else f"failed: {out.get('error', 'unknown')}"
        ),
    }


def _step_find(robot, target: str) -> dict:
    min_turn, _ = turn_bounds(robot)
    timed_velocity(
        robot,
        _stop,
        0,
        max(35.0, min_turn),
        1.15,
        "proc:turn-away",
        settle_seconds=0.25,
    )
    if _stop.is_set():
        return {"step": "find", "ok": False, "error": "stopped", "summary": "stopped"}
    started = time.monotonic()
    out = find_skill.find(robot, target=target, max_cycles=14)
    elapsed = round(time.monotonic() - started, 2)
    st = out.get("status") or {}
    offset = st.get("offset")
    ok = bool(out.get("found") and out.get("centered"))
    return {
        "step": "find",
        "ok": ok,
        "elapsed_s": elapsed,
        "found": bool(out.get("found")),
        "centered": bool(out.get("centered")),
        "cycles": out.get("cycles"),
        "offset": offset,
        "summary": (
            f"found in {elapsed}s ({out.get('cycles')} scans, off {offset})"
            if ok
            else f"seen but uncentered (offset {offset})" if out.get("found") else f"not found after {elapsed}s"
        ),
    }


def _run_sampled_skill(robot, target_fn, status_fn, stop_fn, duration_s: float, step_name: str) -> dict:
    started = time.monotonic()
    samples = []
    worker = robot.owner.thread(target_fn, name=step_name)
    last_key = None
    deadline = started + float(duration_s)
    try:
        while worker.is_alive() and time.monotonic() < deadline and not _stop.is_set():
            st = status_fn()
            key = (st.get("frame_id"), st.get("cycle"), st.get("turn"), st.get("linear"), st.get("phase"))
            if st.get("running") and key != last_key:
                samples.append(dict(st))
                last_key = key
            _stop.wait(0.05)
    finally:
        stop_fn()
        worker.join(timeout=2.0)

    elapsed = round(time.monotonic() - started, 2)
    seen = [s for s in samples if s.get("seen")]
    offsets = [abs(float(s["raw_offset"])) for s in seen if s.get("raw_offset") is not None]
    turns = [float(s["turn"]) for s in seen if s.get("turn")]
    reversals = sum(1 for a, b in zip(turns, turns[1:]) if a * b < 0)
    heights = [float(s["height"]) for s in seen if s.get("height") is not None]
    vetoes = [s.get("veto") for s in samples if s.get("veto")]
    fwd_pulses = sum(1 for s in seen if (s.get("linear") or 0) > 0)
    turn_pulses = sum(1 for s in seen if s.get("turn") and not (s.get("linear") or 0))
    mean_off = round(sum(offsets) / len(offsets), 3) if offsets else None
    final_off = round(float(seen[-1]["raw_offset"]), 3) if seen and seen[-1].get("raw_offset") is not None else None
    seen_pct = round(100 * len(seen) / len(samples)) if samples else 0

    if step_name == "lock":
        ok = bool(samples and samples[-1].get("seen") and final_off is not None
                  and abs(final_off) <= lock_skill.TURN_DEADBAND)
        summary = (
            f"{elapsed}s · seen {seen_pct}% · mean off {mean_off} · final {final_off} · {reversals} rev"
            if seen
            else f"{elapsed}s · target not seen"
        )
    else:
        dh = round(heights[-1] - heights[0], 3) if len(heights) >= 2 else 0.0
        ok = bool(samples and samples[-1].get("seen") and heights and fwd_pulses and dh > 0)
        veto_note = f" · veto:{vetoes[-1]}" if vetoes else ""
        summary = (
            f"{elapsed}s · fwd {fwd_pulses} turn {turn_pulses} · {reversals} rev · dh {dh:+.2f}{veto_note}"
            if seen
            else f"{elapsed}s · target not seen"
        )

    return {
        "step": step_name,
        "ok": ok and not _stop.is_set(),
        "elapsed_s": elapsed,
        "samples": len(samples),
        "seen_pct": seen_pct,
        "mean_abs_offset": mean_off,
        "final_offset": final_off,
        "reversals": reversals,
        "fwd_pulses": fwd_pulses,
        "turn_pulses": turn_pulses,
        "height_start": round(heights[0], 3) if heights else None,
        "height_end": round(heights[-1], 3) if heights else None,
        "veto": vetoes[-1] if vetoes else "",
        "summary": summary,
    }


def _step_lock(robot, target: str, duration_s: float = 8.0) -> dict:
    return _run_sampled_skill(
        robot,
        lambda: lock_skill.lock_on(robot, target=target),
        lock_skill.status,
        lock_skill.stop_lock,
        duration_s,
        "lock",
    )


def _step_follow(robot, target: str, duration_s: float = 6.0) -> dict:
    safety = (robot.status(force=True).get("safety") or {}) if hasattr(robot, "status") else {}
    edge = safety.get("edge") or {}
    if edge.get("enabled") and (edge.get("danger") or not edge.get("ready")):
        reason = edge.get("reason") or "edge safety not ready"
        return {"step": "follow", "ok": False, "error": reason, "summary": f"blocked: {reason}"}
    return _run_sampled_skill(
        robot,
        lambda: follow_skill.follow(robot, target=target),
        follow_skill.status,
        follow_skill.stop_follow,
        duration_s,
        "follow",
    )


def run_procedure(robot, proc_id: str, target: str = "person") -> dict:
    proc = _BY_ID.get(str(proc_id or "").strip())
    if not proc:
        return {"ok": False, "error": f"unknown procedure: {proc_id!r}"}

    _stop.clear()
    target = str(target or "person").strip() or "person"
    started_at = time.time()
    plan = {
        "power_gauge": [("Calibrate min power", lambda: _step_power_gauge(robot))],
        "find_bench": [("Turn away & find target", lambda: _step_find(robot, target))],
        "lock_bench": [("Lock-on tracking (8 s)", lambda: _step_lock(robot, target, 8.0))],
        "follow_bench": [("Follow approach (6 s)", lambda: _step_follow(robot, target, 6.0))],
        "full_suite": [
            ("Calibrate min power", lambda: _step_power_gauge(robot)),
            ("Turn away & find target", lambda: _step_find(robot, target)),
            ("Lock-on tracking (6 s)", lambda: _step_lock(robot, target, 6.0)),
            ("Follow approach (6 s)", lambda: _step_follow(robot, target, 6.0)),
        ],
    }[proc["id"]]

    results = []
    pg_before = robot.power_gauge.status() if hasattr(robot, "power_gauge") else {}
    _state.reset(
        running=True,
        id=proc["id"],
        title=proc["title"],
        target=target,
        setup=proc["setup"],
        steps=list(proc["steps"]),
        step_index=0,
        step_total=len(plan),
        step_label=plan[0][0],
        results=[],
        summary="",
        error="",
    )
    print(f"[procedure] start id={proc['id']} target={target!r}", flush=True)
    try:
        for idx, (label, fn) in enumerate(plan):
            if _stop.is_set():
                break
            _state.update(step_index=idx, step_label=label)
            res = fn()
            results.append(res)
            _state.update(results=list(results))
            print(f"[procedure] {proc['id']} step {idx + 1}/{len(plan)} ({label}): {res.get('summary')}", flush=True)
            if not res.get("ok") and proc["id"] == "full_suite" and idx == 0:
                break
            if idx + 1 < len(plan) and not _stop.is_set():
                _stop.wait(0.5)

        stopped = _stop.is_set()
        ok = bool(results) and all(r.get("ok") for r in results) and not stopped
        summary = " | ".join(f"{r['step']}: {r.get('summary', '')}" for r in results)
        if stopped:
            summary = f"stopped ({summary})" if summary else "stopped"
        pg_after = robot.power_gauge.status() if hasattr(robot, "power_gauge") else {}
        if pg_after.get("min_turn") is not None and proc["id"] != "power_gauge":
            summary = f"{summary} | min {pg_after['min_turn']}%"
        out = {
            "ok": ok,
            "id": proc["id"],
            "title": proc["title"],
            "target": target,
            "stopped": stopped,
            "started_at": round(started_at, 3),
            "elapsed_s": round(time.time() - started_at, 2),
            "results": results,
            "summary": summary,
            "power_before": {"min_turn": pg_before.get("min_turn"), "min_forward": pg_before.get("min_forward")},
            "power_after": {"min_turn": pg_after.get("min_turn"), "min_forward": pg_after.get("min_forward")},
        }
        _append_log(out)
        _state.update(
            running=False,
            step_index=len(plan),
            step_label="stopped" if stopped else "done",
            results=results,
            summary=summary,
            ok=ok,
            error="" if ok else (results[-1].get("error", "") if results else "stopped"),
        )
        return out
    finally:
        robot.movement.stop(source="procedure")
        _state.update(running=False)


def stop_procedure() -> dict:
    _stop.set()
    find_skill.stop_find()
    follow_skill.stop_follow()
    lock_skill.stop_lock()
    return status()


def is_running() -> bool:
    return bool(_state.snapshot().get("running"))


def status() -> dict:
    return _state.snapshot()
