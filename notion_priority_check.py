"""Check priority distribution in Notion vs local todo."""
import sys
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api
from notion_client import parser
from notion_client.sync import _detect_priority

config = api.get_config()
client = api.NotionClient(config)
items = client.query_items()

pri_counts = {}
phase_pri = {}
for item in items:
    p = item.get("properties", {})
    select = p.get("Priority", {}).get("select") or {}
    pri = select.get("name", "N/A") if isinstance(select, dict) else "N/A"
    pri_counts[pri] = pri_counts.get(pri, 0) + 1
    ph_s = p.get("Phase", {}).get("select") or {}
    ph = ph_s.get("name", "") if isinstance(ph_s, dict) else ""
    if ph not in phase_pri:
        phase_pri[ph] = {}
    phase_pri[ph][pri] = phase_pri[ph].get(pri, 0) + 1

print("=== Notion priorities ===")
for k, v in sorted(pri_counts.items()):
    print(f"  {k}: {v}")

print("\n=== Par Phase ===")
for ph in sorted(phase_pri.keys()):
    print(f"  {ph}: {phase_pri[ph]}")

# Local
phases = parser.parse_todo()
local_prio = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}

print("\n=== Tâches locales avec mots-clés P0/P1 ===")
for phase in phases:
    for task in phase.tasks:
        p = _detect_priority(task.text)
        local_prio[p] += 1
        if p in ("P0", "P1"):
            print(f"  [{p}] {phase.name}: {task.text[:70]}")

print("\n=== Local prio counts ===")
for k, v in sorted(local_prio.items()):
    print(f"  {k}: {v}")

client.close()
