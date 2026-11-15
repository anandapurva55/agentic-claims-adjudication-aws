"""Write one small document per policy clause, with the clause id as metadata.

A Bedrock Knowledge Base returns raw text chunks without clause ids, so agents cannot cite properly. A clause card carries its
id as metadata, so a retrieved card is already a citation. Cards are built from data/rules.json, which holds verbatim quotes.
Usage: python scripts/make_clause_cards.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "clause_cards"
OUT.mkdir(parents=True, exist_ok=True)

for f in OUT.glob("*"):
    f.unlink()
rules = json.loads((ROOT / "data" / "rules.json").read_text())
for cid, r in rules.items():
    internal = cid.startswith("INT.")
    text = f"Clause {cid} ({r['source']}).\n{r['quote']}"
    (OUT / f"{cid}.txt").write_text(text)
    meta = {"metadataAttributes": {"clause_id": cid, "origin": "internal control" if internal else "policy wording"}}
    (OUT / f"{cid}.txt.metadata.json").write_text(json.dumps(meta))
print(f"wrote {len(rules)} clause cards to {OUT}")
