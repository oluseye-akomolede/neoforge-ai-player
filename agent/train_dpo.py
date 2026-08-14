"""DPO fine-tune of the L3 planner (qwen2.5:14b-instruct) — v11 R3 step 2.

Consumes the TRL-format dataset produced by `build_dpo_dataset.py`
(prompt/chosen/rejected JSONL) and runs `DPOTrainer` with QLoRA 4-bit on the
A4000×2 node (bf16). The adapter is saved for R5's merge → GGUF export.

This is the *offline* step (R3): preference pairs from the archive/trajectory,
no live execution. R4 (GRPO) reuses the same model + reward and is a separate
script.

Run inside the training image (TRL + peft + bitsandbytes + unsloth) with both
GPUs visible:

    python3 train_dpo.py \
        --dataset dpo_dataset.jsonl \
        --base-model qwen2.5:14b-instruct   # or the local HF snapshot path
        --output ./runs/dpo-lora

Notes:
  - `--base-model` is expected to be a local HuggingFace snapshot path (the
    ollama model must be exported/loaded to HF first), not the ollama tag.
  - QLoRA needs bitsandbytes (4-bit NF4). bf16 assumes Ampere+ (the A4000s).
  - unsloth (`from unsloth import FastLanguageModel`) is optional; if absent the
    plain transformers/peft path is used.
"""
from __future__ import annotations

import argparse
import json


def load_dataset(path: str) -> dict[str, list[str]]:
    prompts, chosen, rejected = [], [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if not (r.get("chosen") and r.get("rejected")):
                continue
            prompts.append(r["prompt"])
            chosen.append(r["chosen"])
            rejected.append(r["rejected"])
    return {"prompt": prompts, "chosen": chosen, "rejected": rejected}


def tokenize(tokenizer, d: dict[str, list[str]]):
    """Tokenize chosen/rejected against the model chat template."""
    def _tok(msgs):
        return tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=False)

    out = {}
    for key in ("chosen", "rejected"):
        toks = [_tok([{"role": "user", "content": p},
                      {"role": "assistant", "content": r}])
                 for p, r in zip(d["prompt"], d[key])]
        out[key] = toks
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--base-model", required=True)
    ap.add_argument("--output", default="./runs/dpo-lora")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--use-unsloth", action="store_true")
    args = ap.parse_args()

    d = load_dataset(args.dataset)
    n = len(d["prompt"])
    print(f"loaded {n} DPO pairs")
    if n < 50:
        print("WARNING: <50 pairs — DPO on a 14B model will overfit. "
              "Accumulate more trajectory data before a real run.")

    import torch
    from transformers import AutoTokenizer, TrainingArguments

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)

    if args.use_unsloth:
        from unsloth import FastLanguageModel, is_bfloat16_supported
        model, _ = FastLanguageModel.from_pretrained(
            args.base_model,
            max_seq_length=4096,
            load_in_4bit=True,
        )
        model = FastLanguageModel.get_peft_model(
            model, r=16, lora_alpha=16, target_modules=[
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj",
            ],
            use_gradient_checkpointing="unsloth",
        )
        bf16 = is_bfloat16_supported()
    else:
        from transformers import BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.base_model, quantization_config=bnb,
            torch_dtype=torch.bfloat16, trust_remote_code=True,
        )
        lora = LoraConfig(r=16, lora_alpha=16, lora_dropout=0.05, bias="none",
                          task_type="CAUSAL_LM")
        model = get_peft_model(model, lora)
        bf16 = True

    train_args = TrainingArguments(
        output_dir=args.output,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        bf16=bf16,
        logging_steps=1,
        save_strategy="epoch",
        report_to="none",
    )

    from trl import DPOTrainer
    trainer = DPOTrainer(
        model=model,
        train_dataset=tokenize(tokenizer, d),
        tokenizer=tokenizer,
        args=train_args,
        beta=args.beta,
    )
    trainer.train()
    trainer.save_model(args.output)
    print(f"saved LoRA adapter to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
