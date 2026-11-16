"""Write a harder benchmark: free-form claim narratives written by a DIFFERENT model family, with labels checked by a third.

  python evals/freeform/generate.py [--per-label 20]

The golden and held-out sets are built from templates, so a system that learned the templates scores well without understanding language. Here Mistral Large 3
writes each narrative from a short fact brief (never from keywords alone), in varied styles, half of them with the obvious words forbidden so the fact has to be
implied. Then gpt-oss-120b labels every narrative WITHOUT seeing the intended label. A narrative is kept only when the independent label matches the intended
one, and every dropped narrative is recorded with the reason. Neither writer nor verifier is a model the product or the single-call baseline uses.
Writes evals/freeform/narratives.json (committed, so the set is reproducible without calling a model again).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config

HERE = Path(__file__).parent
WRITER = "mistral.mistral-large-3-675b-instruct"
VERIFIER = "openai.gpt-oss-120b-1:0"
FLAGS = ("intoxicated", "commercial_use", "unlicensed_driver", "mechanical_failure", "tyre_only", "theft")

# label -> fact briefs the writer expands. The brief states the facts, the writer decides the words.
BRIEFS: dict[str, list[str]] = {
    "clean": [
        "Another car rear-ended the driver at a red light. Nobody was hurt. The rear bumper is damaged.",
        "The driver hit a deep pothole on a rainy night and the front bumper and a headlamp cracked.",
        "While reversing out of a tight parking garage the driver scraped a concrete pillar with the rear bumper.",
        "A cyclist swerved in front of the car, the driver braked hard and scraped the left door against a wall.",
        "A heavy branch fell during a storm and dented the bonnet while the car was parked at home.",
        "In a narrow lane the driver folded a side mirror and scratched a door on a parked truck.",
    ],
    "clean_decoy": [
        "The accident was a minor collision at a junction. The driver stresses that there was no alcohol at all: a breath test at the scene was negative.",
        "A collision at a junction. The car is used only for the family. That day the driver was taking their own children to school, not carrying anyone for money.",
        "A scrape in a car park. The driver is the policyholder's spouse, who is a named permitted driver and holds a valid licence, shown to the police.",
        "A collision on a main road. The car had just been serviced and the accident was entirely the other driver's fault, nothing was wrong with the car.",
        "The driver was carrying a birthday cake to a friend's party as a favour, nobody paid for it, when another car clipped the bumper.",
        "A collision damaged the front bumper and bonnet and also scuffed one tyre. The tyre still holds air.",
    ],
    "intoxicated": [
        "The driver had been drinking beer at a friend's wedding and misjudged a turn on the way home, hitting a divider.",
        "After several whiskeys at a bar, the driver drove off and hit a parked auto-rickshaw.",
        "The driver had smoked cannabis with friends and then drove, drifting into a roadside barrier.",
        "Returning from a bachelor party where the driver had a lot to drink, the car hit a tree.",
        "The driver admits two glasses of wine at dinner and then clipped a bollard while parking outside the restaurant.",
    ],
    "commercial_use": [
        "The driver was delivering food orders for a delivery app when another car hit the side of the vehicle.",
        "The driver was carrying paying passengers booked through a ride-hailing app when the accident happened.",
        "The driver was transporting a customer's furniture across the city for a fee when the car hit a divider.",
        "The car had been hired out for the weekend to a tourist for a daily rental charge, and the tourist had the accident.",
        "The driver runs a small side business collecting school children for monthly payments and the accident happened on a pick-up round.",
    ],
    "unlicensed_driver": [
        "The policyholder's nephew, who does not have a driving licence yet, took the car without asking and hit a wall.",
        "The driver's licence had expired three months earlier and was not renewed. They were driving when a truck clipped the car.",
        "A learner driver was practising alone with no licensed adult in the car and rolled into a gate.",
        "A friend borrowed the car for an errand. He has never held a driving licence. He scraped a pole.",
        "The driver's licence was suspended after earlier traffic offences, and the accident happened during that suspension.",
    ],
    "mechanical_failure": [
        "The engine overheated and seized on the highway. No collision, the car stopped and would not restart.",
        "The gearbox failed while driving and the car lost drive. Nothing hit the car.",
        "A short circuit in the wiring caused smoke and burnt the dashboard and wiring. There was no accident.",
        "The clutch plate burnt out and the engine started making a grinding noise until the vehicle stopped.",
    ],
    "tyre_only": [
        "A tyre burst after driving over a nail. Nothing else on the vehicle was damaged.",
        "The sidewall of the front tyre was cut by a kerb. The only damage is the tyre itself.",
        "A puncture on the highway ruined the tyre. The car body and everything else are untouched.",
    ],
    "theft": [
        "The car was parked outside the house overnight and was gone in the morning.",
        "The vehicle was stolen from a mall parking lot while the owner was shopping.",
        "The owner left the car on the street and when they returned it had disappeared.",
    ],
}
STYLES = ["a formal incident report", "rambling and emotional", "short and blunt, like a text message", "polite non-native English", "detailed with times and street names",
          "full of irrelevant details about the rest of the day", "hedged and uncertain wording"]
FORBIDDEN = {  # words the writer must not use in an implicit narrative, so the fact has to be implied
    "intoxicated": "alcohol, drunk, drinking, intoxicated, beer, whiskey, wine, cannabis, drugs, high",
    "commercial_use": "delivery, delivering, passengers, taxi, hire, hired, rental, fee, paid, commercial, business",
    "unlicensed_driver": "licence, license, unlicensed, learner, permit",
    "mechanical_failure": "breakdown, mechanical, engine failure, gearbox, seized",
    "tyre_only": "puncture, burst",
    "theft": "stolen, theft, thief",
}
DEFS = """intoxicated: the driver was under the influence of alcohol or drugs.
commercial_use: the vehicle was being used for hire, delivery or other commercial purposes at the time.
unlicensed_driver: the driver did not hold a valid licence or was not a permitted driver.
mechanical_failure: the loss was a mechanical or electrical breakdown rather than an accident.
tyre_only: only tyres were damaged and nothing else on the vehicle.
theft: the vehicle was stolen."""


def client() -> object:
    return boto3.client("bedrock-runtime", region_name="us-east-1", config=Config(retries={"max_attempts": 12, "mode": "adaptive"}, read_timeout=180))


def text_of(resp: dict) -> str:
    return "".join(b.get("text", "") for b in resp["output"]["message"]["content"])  # a reasoning model also returns reasoning blocks: keep only the text


def converse(c, model: str, system: str, user: str, max_tokens: int, temperature: float) -> str:
    return text_of(c.converse(modelId=model, system=[{"text": system}], messages=[{"role": "user", "content": [{"text": user}]}],
                              inferenceConfig={"maxTokens": max_tokens, "temperature": temperature}))


def write(c, item: dict) -> str:
    system = ("You write the incident description section of a motor insurance claim form, as the policy holder, in the first person. Write 2 to 5 sentences. "
              "Make it sound like a real person, not a template. Do not mention an insurance company, policy number, amounts or dates. Reply with the description only.")
    user = f"Facts to describe: {item['brief']}\nWriting style: {item['style']}."
    if item["implicit"] and item["forbidden"]:
        user += f"\nImportant: do NOT use any of these words: {item['forbidden']}. Make the facts clear through concrete details instead."
    return converse(c, WRITER, system, user, 400, 0.9).strip().strip('"')


def verify(c, narrative: str) -> dict:
    system = (f"You label motor insurance claim narratives. Flags:\n{DEFS}\nMark a flag true only when the narrative clearly supports it. A negated statement such as "
              '"had not consumed any alcohol" means the flag is false. Reply with JSON only: {"intoxicated": bool, "commercial_use": bool, "unlicensed_driver": bool, '
              '"mechanical_failure": bool, "tyre_only": bool, "theft": bool}')
    out = converse(c, VERIFIER, system, narrative, 1500, 0.0)
    m = re.search(r"\{.*\}", out, re.S)
    try:
        got = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        got = {}
    return {f: bool(got.get(f, False)) for f in FLAGS}


def intended(label: str) -> dict:
    return {f: f == {"unlicensed": "unlicensed_driver"}.get(label, label) for f in FLAGS}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="multiply the number of narratives per label")
    a = ap.parse_args()
    plan = {"clean": 24, "clean_decoy": 16, "intoxicated": 20, "commercial_use": 20, "unlicensed_driver": 20, "mechanical_failure": 16, "tyre_only": 12, "theft": 12}
    rng, items = random.Random(20261116), []
    for label, n in plan.items():
        base = label if label != "clean_decoy" else "clean"
        for i in range(round(n * a.scale)):
            brief = BRIEFS[label][i % len(BRIEFS[label])]
            implicit = label in FORBIDDEN and i % 2 == 1
            items.append({"id": f"FF-{len(items) + 1:03d}", "label": base, "decoy": label == "clean_decoy", "flags": intended(base), "brief": brief,
                          "style": rng.choice(STYLES), "implicit": implicit, "forbidden": FORBIDDEN.get(label, "")})
    c = client()
    t0 = time.time()

    def one(item: dict) -> dict:
        try:
            item["narrative"] = write(c, item)
            item["verifier_flags"] = verify(c, item["narrative"])
        except Exception as exc:  # noqa: BLE001
            item.update(narrative="", verifier_flags={}, error=str(exc)[:160])
        item["verified"] = bool(item.get("narrative")) and item["verifier_flags"] == item["flags"]
        return item
    with ThreadPoolExecutor(4) as pool:
        done = list(pool.map(one, items))
    kept = [d for d in done if d["verified"]]
    for d in done:
        if not d["verified"]:
            d["dropped_because"] = d.get("error") or ("the verifier disagreed: " + ", ".join(f for f in FLAGS if d["verifier_flags"].get(f) != d["flags"][f]))
    out = {"writer": WRITER, "verifier": VERIFIER, "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "written": len(done), "kept": len(kept),
           "dropped": len(done) - len(kept), "by_label_kept": {k: sum(d["label"] == k and not d["decoy"] for d in kept) for k in dict.fromkeys(d["label"] for d in done)},
           "decoys_kept": sum(d["decoy"] for d in kept), "narratives": done}
    (HERE / "narratives.json").write_text(json.dumps(out, indent=1))
    print(f"{len(done)} written, {len(kept)} verified, {len(done) - len(kept)} dropped in {time.time() - t0:.0f}s")
    print("kept by label:", out["by_label_kept"], "decoys kept:", out["decoys_kept"])


if __name__ == "__main__":
    main()
