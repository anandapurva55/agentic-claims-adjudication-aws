"""QLoRA fine-tune versus prompting, in one run. Runs inside a SageMaker training job, or locally with a tiny model for a smoke test.

What it does, in order, on the SAME held-out narratives:
  1. Prompts the base model zero-shot and few-shot (the baselines).
  2. Trains a LoRA adapter (4-bit quantised base model when a CUDA GPU is present: that is QLoRA).
  3. Evaluates the tuned model, zero-shot, on the same test sets.
Writes metrics.json and predictions.jsonl, and saves the adapter.

Held-out sets: test_unseen (wording the model never saw in training) and test_golden (63 narratives from the claims system, which share
some wording with training: see the README, it is not a clean held-out set).
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig
from scoring import FLAGS, parse_flags, score  # noqa: F401
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer


def args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--eval-batch", type=int, default=16)
    ap.add_argument("--no-4bit", action="store_true", help="plain LoRA in 16 bit instead of QLoRA (needed on a Mac, which has no CUDA)")
    ap.add_argument("--max-train", type=int, default=0, help="smoke test: use only this many training examples")
    ap.add_argument("--max-test", type=int, default=0, help="smoke test: use only this many test examples per set")
    ap.add_argument("--train-dir", default=os.environ.get("SM_CHANNEL_TRAIN", "finetune/data"))
    ap.add_argument("--test-dir", default=os.environ.get("SM_CHANNEL_TEST", "finetune/data"))
    ap.add_argument("--out-dir", default=os.environ.get("SM_OUTPUT_DATA_DIR", "finetune/out"))
    ap.add_argument("--model-dir", default=os.environ.get("SM_MODEL_DIR", "finetune/out/model"))
    return ap.parse_args()


def load(path: Path, limit: int = 0) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows[:limit] if limit else rows


@torch.no_grad()
def generate(model, tok, prompts: list[list[dict]], batch: int) -> tuple[list[str], float]:
    """Greedy answers for a list of chat prompts. Returns the texts and the average seconds per narrative."""
    tok.padding_side = "left"
    texts, t0 = [], time.perf_counter()
    for i in range(0, len(prompts), batch):
        chunk = [tok.apply_chat_template(p, tokenize=False, add_generation_prompt=True) for p in prompts[i:i + batch]]
        enc = tok(chunk, return_tensors="pt", padding=True).to(model.device)
        out = model.generate(**enc, max_new_tokens=70, do_sample=False, pad_token_id=tok.pad_token_id)
        texts += tok.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
    return texts, (time.perf_counter() - t0) / max(1, len(prompts))


def evaluate(model, tok, rows: list[dict], few_shot: list[dict] | None, batch: int) -> tuple[dict, list[dict]]:
    sys_msg = rows[0]["messages"][0]
    shots = []
    for ex in few_shot or []:
        shots += [{"role": "user", "content": ex["messages"][1]["content"]}, {"role": "assistant", "content": ex["messages"][2]["content"]}]
    prompts = [[sys_msg, *shots, {"role": "user", "content": r["messages"][1]["content"]}] for r in rows]
    texts, sec = generate(model, tok, prompts, batch)
    scored = []
    for r, t in zip(rows, texts, strict=True):
        pred, valid = parse_flags(t)
        scored.append({"narrative": r["narrative"], "gold": r["labels"], "pred": pred, "valid": valid, "raw": t.strip()[:200]})
    s = score(scored)
    s["seconds_per_narrative"] = round(sec, 4)
    return s, scored


def pick_shots(train: list[dict]) -> list[dict]:
    """Four fixed examples covering a positive, a negation and a clean narrative, for the few-shot baseline."""
    def first(pred):
        return next(x for x in train if pred(x["labels"]))
    return [first(lambda L: L["intoxicated"]), first(lambda L: not any(L.values())), first(lambda L: L["commercial_use"]),
            first(lambda L: L["unlicensed_driver"])]


def main() -> None:
    a = args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    train = load(Path(a.train_dir) / "train.jsonl", a.max_train)
    dev = load(Path(a.train_dir) / "dev.jsonl", a.max_train)
    tests = {"test_unseen": load(Path(a.test_dir) / "test_unseen.jsonl", a.max_test), "test_golden": load(Path(a.test_dir) / "test_golden.jsonl", a.max_test)}

    cuda = torch.cuda.is_available()
    use_4bit = cuda and not a.no_4bit
    bf16 = cuda and torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float16 if cuda else torch.float32
    tok = AutoTokenizer.from_pretrained(a.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype) if use_4bit else None
    model = AutoModelForCausalLM.from_pretrained(a.model, quantization_config=quant, dtype=dtype, device_map="auto" if cuda else None)
    if not cuda and torch.backends.mps.is_available():
        model = model.to("mps")
    model.eval()
    info = {"model": a.model, "gpu": torch.cuda.get_device_name(0) if cuda else "none", "qlora_4bit": use_4bit, "dtype": str(dtype),
            "train_examples": len(train), "epochs": a.epochs, "lora_rank": a.rank, "learning_rate": a.lr}
    print("config:", info, flush=True)
    results: dict = {"config": info, "baselines": {}, "tuned": {}}
    preds: list[dict] = []

    # 1. baselines: the base model, prompted
    shots = pick_shots(train) if len(train) >= 20 else []
    for name, rows in tests.items():
        for mode, fs in (("zero_shot", None), ("few_shot", shots or None)):
            s, sc = evaluate(model, tok, rows, fs, a.eval_batch)
            results["baselines"][f"{name}/{mode}"] = s
            preds += [{"set": name, "system": f"base_{mode}", **x} for x in sc]
            print(f"base {mode:9} {name:12} exact={s['exact_match']:.3f} microF1={s['micro_f1']:.3f} missed_denials={s['missed_denials']}", flush=True)

    # 2. train the adapter
    conv = lambda rows: Dataset.from_list([{"prompt": r["messages"][:2], "completion": [r["messages"][2]]} for r in rows])  # noqa: E731
    wanted = dict(output_dir=str(out / "trainer"), num_train_epochs=a.epochs, per_device_train_batch_size=a.batch, gradient_accumulation_steps=a.grad_accum,
                  learning_rate=a.lr, lr_scheduler_type="cosine", warmup_ratio=0.03, logging_steps=10, save_strategy="no", report_to="none",
                  bf16=bf16, fp16=cuda and not bf16, gradient_checkpointing=cuda, max_length=a.max_len, max_seq_length=a.max_len,
                  completion_only_loss=True, eval_strategy="epoch", per_device_eval_batch_size=a.batch, use_cpu=not cuda and not torch.backends.mps.is_available())
    allowed = set(inspect.signature(SFTConfig.__init__).parameters)
    cfg = SFTConfig(**{k: v for k, v in wanted.items() if k in allowed})
    lora = LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=conv(train), eval_dataset=conv(dev), processing_class=tok, peft_config=lora)
    t0 = time.perf_counter()
    trainer.train()
    results["train_seconds"] = round(time.perf_counter() - t0)
    results["train_loss_log"] = [{k: v for k, v in h.items() if k in ("step", "loss", "eval_loss", "epoch")} for h in trainer.state.log_history if "loss" in h or "eval_loss" in h]

    # 3. the tuned model, zero-shot, on the same held-out sets
    tuned = trainer.model
    tuned.eval()
    for name, rows in tests.items():
        s, sc = evaluate(tuned, tok, rows, None, a.eval_batch)
        results["tuned"][name] = s
        preds += [{"set": name, "system": "qlora_tuned", **x} for x in sc]
        print(f"tuned zero_shot {name:12} exact={s['exact_match']:.3f} microF1={s['micro_f1']:.3f} missed_denials={s['missed_denials']}", flush=True)

    trainer.save_model(a.model_dir)
    (out / "metrics.json").write_text(json.dumps(results, indent=2))
    (out / "predictions.jsonl").write_text("\n".join(json.dumps(p) for p in preds) + "\n")
    print("done", flush=True)


if __name__ == "__main__":
    main()
