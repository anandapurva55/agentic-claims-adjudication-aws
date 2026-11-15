"""Seed AgentCore long term memory with senior adjuster guidance. Usage: python scripts/seed_memory.py
Needs CLAIMS_MODE=live and CLAIMS_MEMORY_ID. Idempotent: it skips guidance that is already stored."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import memory  # noqa: E402
from app.config import settings  # noqa: E402

if not (settings.mode == "live" and settings.memory_id):
    sys.exit("set CLAIMS_MODE=live and CLAIMS_MEMORY_ID first")

existing = {h["text"] for h in memory.recall("driver claim guidance", 50)} if settings.memory_id else set()
n = 0
for item in json.loads((ROOT / "data" / "lessons_seed.json").read_text()):
    if item["text"] not in existing:
        memory.store_lesson(item["text"], {"source": item["source"]})
        n += 1
print(f"stored {n} lessons in AgentCore memory {settings.memory_id}")
