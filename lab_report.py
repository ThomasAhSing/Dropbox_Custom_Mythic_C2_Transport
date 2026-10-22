"""Summarize durable lab evidence without message contents or credentials."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sqlite3


def report(paths):
    workers, processed, all_rtt, state_errors = [], Counter(), [], []
    for path in paths:
        db = None
        try:
            db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
            db.execute("BEGIN")
            identity = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0]
            node, run_id = identity.split(":")
            events = dict(db.execute("SELECT event,count(*) FROM events GROUP BY event"))
            statuses = dict(db.execute("SELECT status,count(*) FROM outbox WHERE kind='heartbeat' GROUP BY status"))
            rtt = [max(0, row[0]) for row in db.execute(
                "SELECT acked-sent FROM outbox WHERE kind='heartbeat' AND acked IS NOT NULL AND sent IS NOT NULL")]
            queue_latency = [max(0, row[0]) for row in db.execute(
                "SELECT acked-created FROM outbox WHERE kind='heartbeat' AND acked IS NOT NULL")]
            for (mid,) in db.execute("SELECT id FROM inbox WHERE kind='heartbeat'"):
                processed[(run_id, node, mid)] += 1
            total = sum(statuses.values())
            acked = statuses.get("acknowledged", 0)
            workers.append(dict(state=Path(path).name, node=node, run_id=run_id,
                                heartbeat_status=statuses, events=events,
                                unacknowledged_fraction=(total - acked) / total if total else None,
                                storage_attempt_failure_rate=(events.get("storage_attempt_failure", 0) / events["storage_attempt"]
                                                              if events.get("storage_attempt") else None),
                                ack_roundtrip_seconds=rtt, scheduled_to_ack_seconds=queue_latency))
            all_rtt.extend(rtt)
        except (sqlite3.Error, TypeError, ValueError):
            state_errors.append(dict(state=Path(path).name, code="unreadable_state"))
        finally:
            if db is not None:
                db.close()
    all_rtt.sort()
    def percentile(p):
        return all_rtt[max(0, math.ceil(len(all_rtt) * p) - 1)] if all_rtt else None
    return dict(workers=workers, state_errors=state_errors, unique_processed_heartbeats=len(processed),
                cross_worker_duplicate_processing=sum(count - 1 for count in processed.values()),
                ack_roundtrip_seconds=dict(samples=len(all_rtt), p50=percentile(.5), p95=percentile(.95),
                                           maximum=max(all_rtt) if all_rtt else None),
                interpretation="RTT uses the sender clock. Unacknowledged is a deadline outcome, not proven message loss. "
                               "Duplicate observations are repeated polls; cross-worker duplicates are separate processing effects.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("states", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()
    evidence = report(args.states)
    result = json.dumps(evidence, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(result + "\n", encoding="utf-8")
    print(result)
    return 1 if evidence["state_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
