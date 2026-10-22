"""Launch two real Python processes, optionally kill/restart B, and save evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from lab_report import report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["local", "dropbox"], default="local")
    parser.add_argument("--duration", type=float, default=12)
    parser.add_argument("--scenario", choices=["baseline", "restart", "replicas"], default="baseline")
    parser.add_argument("--output", default="artifacts")
    args = parser.parse_args()
    if args.duration < 8 or args.duration > 3600:
        parser.error("duration must be 8–3600 seconds (use 120 or more with Dropbox)")
    run_id = str(uuid4())
    root = Path(args.output).resolve() / run_id
    root.mkdir(parents=True)
    processes, handles, timeline, codes = [], [], [], []
    project = Path(__file__).resolve().parent
    states = []

    def launch(node, state, duration, heartbeats=5):
        output = open(root / f"{state}-{len(processes)}.jsonl", "w", encoding="utf-8")
        handles.append(output)
        state_path = root / f"{state}.sqlite"
        if state_path not in states:
            states.append(state_path)
        process = subprocess.Popen([
            sys.executable, str(project / "lab_app.py"), "--node", node,
            "--run-id", run_id, "--state", str(state_path), "--provider", args.provider,
            "--root", str(root / "store"), "--duration", str(duration),
            "--poll", "0.2" if args.provider == "local" else "2", "--heartbeats", str(heartbeats),
            "--heartbeat-interval", "1",
        ], stdout=output, stderr=output, cwd=project)
        processes.append(process)
        timeline.append(dict(event="launch", worker=state, utc=datetime.now(timezone.utc).isoformat()))
        return process

    print(f"Run {run_id}: {args.provider}, {args.scenario}", flush=True)
    try:
        a = launch("node-a", "a", args.duration)
        b = launch("node-b", "b", args.duration, 0 if args.scenario == "replicas" else 5)
        if args.scenario == "replicas":
            launch("node-b", "b-replica", args.duration, 0)
        if args.scenario == "restart":
            time.sleep(1.5)
            b.kill()
            b.wait(timeout=10)
            timeline.append(dict(event="killed", worker="b", utc=datetime.now(timezone.utc).isoformat()))
            time.sleep(2)
            b = launch("node-b", "b", args.duration)
        for process in processes:
            # Windows kill returns positive 1; record killed process separately below.
            if args.scenario == "restart" and process is processes[1]:
                continue
            codes.append(process.wait(timeout=args.duration + 90))
    except subprocess.TimeoutExpired:
        codes.append(124)
        timeline.append(dict(event="runner_timeout", utc=datetime.now(timezone.utc).isoformat()))
    except KeyboardInterrupt:
        codes.append(130)
        timeline.append(dict(event="interrupted", utc=datetime.now(timezone.utc).isoformat()))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        for handle in handles:
            handle.close()
    available = [path for path in states if path.exists()]
    result = report(available)
    result["missing_worker_state"] = [path.name for path in states if not path.exists()]
    result.update(provider=args.provider, scenario=args.scenario, run_id=run_id,
                  timeline=timeline, exit_codes=codes)
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Evidence: {root / 'report.json'}")
    return 0 if (codes and all(code == 0 for code in codes)
                 and not result["missing_worker_state"] and not result["state_errors"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
