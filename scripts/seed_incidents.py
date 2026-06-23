"""Demo: post N resolved-incident reports to the LIVE backend so the retrain
loop has feedback to learn from (the Analytics page / Retrain button).

Each report hits POST /incident/report, which writes a linked prediction+outcome
pair to the server's feedback store -- the same thing an officer submission does.
Timestamps are spread over the past ~10 days so the time-based validation split
behaves like production.

"""
import random
import sys
from datetime import datetime, timedelta

import requests

API = (sys.argv[1] if len(sys.argv) > 1 else "https://kilgamash-gridlock.hf.space").rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20

CAUSES = ["engine_failure", "tyre_burst", "accident", "stalled_vehicle",
          "overheating", "fuel_shortage"]
VEHICLES = ["truck", "bus", "car", "auto", "two_wheeler"]

random.seed(42)
print(f"seeding {N} incidents -> {API}")
print("fetching corridor list (cold Space may take ~30s to wake)...")
corridors = [c["corridor"] for c in requests.get(f"{API}/corridors/all", timeout=180).json()]

ok = 0
for i in range(N):
    started = datetime.now() - timedelta(days=i * 0.5, minutes=random.randint(0, 600))
    duration = random.randint(20, 180)
    payload = {
        "corridor": random.choice(corridors),
        "cause": random.choice(CAUSES),
        "veh_type": random.choice(VEHICLES),
        "cause_severity": random.randint(2, 5),
        "road_closure": random.random() < 0.3,
        "duration_min": duration,
        "corridors_affected": random.randint(1, 4),
        "started_at": started.isoformat(),
        "notes": "seeded demo incident",
    }
    r = requests.post(f"{API}/incident/report", json=payload, timeout=60)
    ok += r.status_code == 200
    print(f"  {i+1:2d}/{N}  {r.status_code}  {payload['corridor']:<24} "
          f"{payload['cause']:<16} {duration}min")

info = requests.get(f"{API}/model-info", timeout=60).json()
print(f"\ndone: {ok}/{N} accepted. resolved_incidents on server = "
      f"{info.get('resolved_incidents')}")
print("Now click Retrain on the Analytics page, or:  "
      f'curl -X POST {API}/retrain')
