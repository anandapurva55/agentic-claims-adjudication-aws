"""Build the fine-tuning dataset: incident narrative in, six judgement flags out.

The task is the one the claims system actually struggles with: reading customer text and deciding whether a driver was intoxicated,
the car was used commercially, and so on, including negations ("had not consumed any alcohol") and traps ("collecting a parcel a
friend sent" is not commercial use).

Honesty about generalisation: the training narratives and the held-out test narratives are built from DISJOINT phrase banks, so the
test set contains wording the model never saw in training. A model that only memorised templates will fail it. The 63 narratives from
the golden claims set are a second held-out set (they come from a different generator).

Usage: python finetune/make_dataset.py        writes finetune/data/{train,dev,test_unseen,test_golden}.jsonl
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "data"
FLAGS = ["intoxicated", "commercial_use", "unlicensed_driver", "mechanical_failure", "tyre_only", "theft"]

SYSTEM = (
    "You read the incident narrative of a motor insurance claim and decide six judgement flags. Reply with JSON only, with exactly these "
    "keys and true or false values: intoxicated, commercial_use, unlicensed_driver, mechanical_failure, tyre_only, theft. A flag is true only "
    "when the narrative states that it happened. A negated statement, such as the driver had not been drinking, means false."
)

# Each bank has a TRAIN list and a TEST list. The test list never appears in training.
BASE = {
    "train": [
        "Rear ended at a traffic signal by another vehicle.", "Hit a stationary truck while reversing in a parking lot.",
        "Side swiped by an auto rickshaw on a narrow road.", "Collided with a divider while changing lanes.",
        "The car skidded on a wet road and hit a roadside barrier.", "Another car cut across at a junction and the two vehicles collided.",
        "Struck a pole while turning into a lane near the market.", "A bike rider swerved in front and the car hit the kerb to avoid him.",
        "The vehicle scraped a wall in a tight basement ramp.", "A cow crossed the road suddenly and the driver braked and hit a tree.",
        "A truck backed into the parked car at a petrol pump.", "The car ran into the back of a bus at a bus stop.",
        "Hit a pothole and then slid into a drain.", "A falling branch damaged the roof and bonnet.", "Cyclist fell onto the bonnet at a crossing.",
        "Another vehicle reversed into the front bumper at a mall.", "The car was hit from the side at a roundabout.", "Door was dented by a passing tempo.",
    ],
    "test": [
        "At a crossroads a delivery van jumped the light and clipped our front wing.", "While parking outside a clinic the vehicle bumped a concrete bollard.",
        "A lorry pulled out of a side street without looking and caught the rear quarter panel.", "The vehicle was in a minor pile up on the flyover during rush hour.",
        "A scooter rider fell in front of the vehicle and the bumper took the impact.", "The nearside mirror and door were crushed against a gate post.",
        "Heavy rain made the road slick and the vehicle slid into a median.", "A shopping trolley rolled into the parked car in a supermarket lot.",
    ],
}

POSITIVE = {
    "intoxicated": {
        "train": ["The driver had been drinking before the trip.", "The driver admitted to having a few drinks at a party earlier.", "He smelled strongly of liquor at the scene.",
                  "Witnesses said the driver seemed drunk.", "A breath test at the scene showed alcohol above the legal limit.", "The driver confessed to taking several beers before driving.",
                  "The driver was visibly intoxicated and slurring his words.", "The driver had been at a bar all evening.", "Empty liquor bottles were found in the car.",
                  "She was feeling tipsy after a wedding reception.", "The driver said he had two pegs of whisky with dinner.", "Police noted the driver was under the influence of alcohol.",
                  "The driver had taken a sedative drug and was drowsy.", "He had been celebrating with friends and drinking heavily.", "The driver admitted to being a little drunk.",
                  "Alcohol was suspected, the driver reeked of rum."],
        "test": ["The driver owned up to downing some whiskey at his cousin's engagement before he got behind the wheel.", "Bystanders said the driver was unsteady and swaying, with a bottle in the footwell.",
                 "The attending officer wrote that the driver's blood alcohol reading was over the limit.", "After a long evening of toasts, the driver took the car home half cut."],
    },
    "commercial_use": {
        "train": ["The car was being used to carry paying passengers through a ride app.", "The driver was delivering food orders for an app at the time.",
                  "The vehicle was on a paid taxi trip when the collision happened.", "The owner was ferrying customers for a cab aggregator.", "The car was carrying goods for a courier company.",
                  "The driver had a fare in the back seat booked through a mobile app.", "The vehicle was being used as a taxi that night.", "He was dropping a paying rider at the airport.",
                  "The car was on a commercial delivery run with parcels for customers.", "It was being rented out and the hirer was driving.", "The driver does part time taxi work and had a passenger on board.",
                  "The vehicle was carrying a load of vegetables for sale at the market."],
        "test": ["The owner was on a rideshare shift and a booked passenger was in the back.", "The vehicle was hauling grocery orders for a delivery startup when it was hit.",
                 "The car was out on a paid chauffeur booking for a hotel guest."],
    },
    "unlicensed_driver": {
        "train": ["The driver does not hold a driving licence.", "The driver's licence had expired a year earlier.", "The car was being driven by a friend who has no licence.",
                  "The driver only had a learner permit that had lapsed.", "The driver could not produce any licence at the scene.", "The person driving was a minor without a licence.",
                  "His licence had been suspended and he was driving anyway.", "The driver admitted he had never obtained a licence."],
        "test": ["The cousin at the wheel had only a lapsed learner's permit and no full licence.", "The driver could not show any valid driving document when the police asked.",
                 "The person driving never sat the driving test."],
    },
    "mechanical_failure": {
        "train": ["The engine failed and the car stopped on the highway. No collision occurred.", "The gearbox broke down on the road, there was no accident.",
                  "The car overheated and the engine seized, no other vehicle was involved.", "A transmission fault left the car stranded, with no impact at all.",
                  "The clutch burned out and the vehicle stopped. Nothing hit the car.", "The engine stopped suddenly because of a mechanical breakdown."],
        "test": ["The motor packed up on the bypass and the car coasted to a halt, with no crash.", "A failed timing belt wrecked the engine while driving, and no other vehicle was involved."],
    },
    "tyre_only": {
        "train": ["Two tyres were damaged after hitting a pothole. No other damage to the vehicle.", "A tyre burst and nothing else on the car was damaged.",
                  "Only the front tyre was cut by a nail, the body is untouched.", "The tyres were slashed but the vehicle has no other damage.",
                  "A tyre was damaged by debris and there is no other damage to the car."],
        "test": ["A rear tyre was punctured by a metal shard, the rest of the vehicle is undamaged.", "Only the tyres were harmed in the pothole, nothing else is damaged."],
    },
    "theft": {
        "train": ["The car was stolen from outside the house overnight.", "The vehicle was stolen from the parking lot while the owner was shopping.",
                  "Thieves drove the car away from the street.", "The owner found the car missing in the morning and reported the theft.",
                  "The car was taken from the basement by an unknown person."],
        "test": ["Someone drove off with the car from the car park while the owner was at work.", "The vehicle vanished from the lane overnight and the owner lodged a theft report."],
    },
}

# Negations and traps: sentences that mention a topic but mean the flag is FALSE.
NEGATED = {
    "intoxicated": {
        "train": ["The driver had not consumed any alcohol.", "The breath test at the scene was negative.", "The driver does not drink and was fully sober.",
                  "Alcohol was ruled out by the police.", "The driver had only had tea that evening.", "No alcohol or drugs were involved."],
        "test": ["A sobriety check at the scene came back clear.", "The driver had nothing stronger than a soft drink all day."],
    },
    "commercial_use": {
        "train": ["The owner was returning home after collecting a parcel that a friend had sent.", "The car was being used for a family outing.",
                  "The owner was picking up his own groceries from the market.", "A courier delivered a package to the owner's house earlier but the car was not used for it.",
                  "The vehicle was carrying the owner's relatives to a temple."],
        "test": ["The owner was bringing home a gift that his brother had mailed to a shop.", "The car was only used for the owner's daily commute to the office."],
    },
    "unlicensed_driver": {
        "train": ["The driver showed a valid licence to the police.", "The driver has held a licence for ten years.", "A valid licence was produced at the scene."],
        "test": ["The driver handed over a current licence when asked."],
    },
    "mechanical_failure": {
        "train": ["After the collision the engine would not start.", "The engine was running fine until the other vehicle hit the car.", "The car was recently serviced and had no fault."],
        "test": ["The vehicle had no mechanical trouble before the impact."],
    },
    "tyre_only": {
        "train": ["A tyre burst and the car then hit a divider, damaging the bumper and bonnet.", "The tyre was fine but the door and fender were badly damaged.",
                  "Besides a flat tyre, the headlamp and bonnet were also crushed."],
        "test": ["The tyre blew out and the car then hit a wall, wrecking the bumper and the radiator."],
    },
    "theft": {
        "train": ["Someone tried to steal the car but failed and only scratched the door.", "The car was not stolen, it was towed by traffic police.",
                  "The owner thought the car was stolen but it had been moved by his brother."],
        "test": ["An attempted break in left the lock damaged, but the car was never taken."],
    },
}

# Opening sentence when there was no collision. Different wording per split, so the placeholder itself cannot leak.
LOSS = {"train": "Reported loss.", "test": "A loss was lodged with the insurer."}

EXTRA = {
    "train": ["The incident happened at about six in the evening.", "It was raining at the time.", "The road was crowded.", "It was a Sunday.", "The incident took place near the station."],
    "test": ["This happened late at night.", "Visibility was poor because of fog.", "It occurred close to the ring road."],
}


def compose(rng: random.Random, split: str) -> dict:
    """One narrative. A base sentence, then 0 to 2 flag sentences (asserted or negated, never both for one flag), then maybe filler."""
    parts = [rng.choice(BASE[split])]
    labels = {f: False for f in FLAGS}
    chosen = rng.sample(FLAGS, k=rng.choice([0, 1, 1, 2]))
    for f in chosen:
        if rng.random() < 0.55:
            parts.append(rng.choice(POSITIVE[f][split]))
            labels[f] = True
        else:
            parts.append(rng.choice(NEGATED[f][split]))
    # Physical consistency: mechanical failure and a collision do not co-occur, and tyre_only implies nothing else was damaged.
    if labels["mechanical_failure"] or labels["tyre_only"]:
        parts[0] = LOSS[split]
    if labels["theft"]:
        parts[0] = LOSS[split]
    if rng.random() < 0.4:
        parts.append(rng.choice(EXTRA[split]))
    return {"narrative": " ".join(parts), "labels": labels}


def to_example(item: dict) -> dict:
    return {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": item["narrative"]},
                         {"role": "assistant", "content": json.dumps(item["labels"])}], **item}


def golden() -> list[dict]:
    """The 63 narratives from the claims golden set, labelled with the ground truth flags. A second, different held-out set."""
    import sys
    root = HERE.parent
    sys.path.insert(0, str(root / "backend"))
    from app.services import data  # noqa: PLC0415
    cases = json.loads((root / "evals" / "golden" / "cases.json").read_text())
    return [{"narrative": data.extract_claim(c["claim_id"])["narrative"], "labels": c["expected"]["flags"]} for c in cases]


def write(name: str, items: list[dict]) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.jsonl").write_text("\n".join(json.dumps(to_example(i)) for i in items) + "\n")


def main() -> None:
    rng = random.Random(7)
    seen: set[str] = set()

    def unique(split: str, n: int) -> list[dict]:
        out = []
        while len(out) < n:
            item = compose(rng, split)
            if item["narrative"] not in seen:
                seen.add(item["narrative"])
                out.append(item)
        return out

    train, dev, test = unique("train", 1200), unique("train", 150), unique("test", 300)
    write("train", train)
    write("dev", dev)
    write("test_unseen", test)
    write("test_golden", golden())
    train_sentences = {sent for x in train for sent in x["narrative"].split(". ")}
    gold_items = golden()
    shared = sum(1 for g in gold_items if any(sent in train_sentences for sent in g["narrative"].split(". ")))
    print(f"golden narratives sharing at least one sentence with the training data: {shared} of {len(gold_items)} (so test_golden is NOT a clean held-out set)")
    rate = {f: round(sum(i["labels"][f] for i in train) / len(train), 2) for f in FLAGS}
    print(f"train {len(train)}  dev {len(dev)}  test_unseen {len(test)}  test_golden 63")
    print("positive rate in train:", rate)


if __name__ == "__main__":
    main()
