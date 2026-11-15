"""The fine-tuning dataset must be honest: the unseen test set shares no wording with training, and every label follows from the text."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import make_dataset as md  # noqa: E402

DATA = Path(__file__).parent / "data"


def load(name):
    return [json.loads(line) for line in (DATA / f"{name}.jsonl").read_text().splitlines() if line.strip()]


def sentences(items):
    return {s for x in items for s in x["narrative"].split(". ")}


def banks(split):
    out = set(md.BASE[split]) | set(md.EXTRA[split]) | {md.LOSS[split]}
    for f in md.FLAGS:
        out |= set(md.POSITIVE[f][split]) | set(md.NEGATED[f][split])
    return {s.rstrip(".") for s in out}


def test_phrase_banks_for_train_and_test_are_disjoint():
    assert banks("train").isdisjoint(banks("test"))


def test_unseen_test_narratives_share_no_sentence_with_training():
    shared = {s.rstrip(".") for s in sentences(load("train"))} & {s.rstrip(".") for s in sentences(load("test_unseen"))}
    assert shared == set(), shared


def test_labels_follow_from_the_text():
    for split in ("train", "test_unseen"):
        key = "train" if split == "train" else "test"
        for item in load(split):
            for f in md.FLAGS:
                asserted = any(p in item["narrative"] for p in md.POSITIVE[f][key])
                assert item["labels"][f] == asserted, (f, item["narrative"])


def test_assistant_message_is_valid_json_with_exactly_the_six_keys():
    for item in load("train")[:200] + load("test_unseen")[:100]:
        out = json.loads(item["messages"][-1]["content"])
        assert list(out) == md.FLAGS and all(isinstance(v, bool) for v in out.values())


def test_every_flag_has_positive_and_negative_examples():
    train = load("train")
    for f in md.FLAGS:
        pos = sum(x["labels"][f] for x in train)
        assert 40 < pos < len(train) - 40, (f, pos)


def test_dataset_sizes():
    assert (len(load("train")), len(load("dev")), len(load("test_unseen")), len(load("test_golden"))) == (1200, 150, 300, 63)
