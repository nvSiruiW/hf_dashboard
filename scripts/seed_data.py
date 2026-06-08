"""Seed the SQLite DB with a handful of sample HF model × backend rows.

Run once after first install so the Test Matrix page has something to render.
Safe to re-run — uses UPSERT.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hf_dashboard.services import db  # noqa: E402


SAMPLES = [
    # (model_name, backend, gpu, status, ai_reason, bug_id)
    ("meta-llama/Llama-3.1-8B-Instruct", "trtllm", "H100", "passed",
     "Generated coherent English completions across 5 prompts; no errors.", ""),
    ("meta-llama/Llama-3.1-8B-Instruct", "vllm",   "H100", "passed",
     "Three test prompts produced fluent English answers; clean shutdown.", ""),
    ("meta-llama/Llama-3.1-8B-Instruct", "sglang", "H100", "failed",
     "CUDA OOM during second prompt; KV cache could not allocate.", "4567890"),
    ("Qwen/Qwen3-30B-A3B", "trtllm", "H200", "passed",
     "MOE routing initialized; produced bilingual output without garbling.", ""),
    ("Qwen/Qwen3-30B-A3B", "vllm",   "H200", "pending", "", ""),
    ("Qwen/Qwen3-30B-A3B", "sglang", "H200", "running", "", ""),
    ("deepseek-ai/DeepSeek-V3", "trtllm", "B200", "broken",
     "Log truncated before any generation; suspect node preemption.", ""),
    ("deepseek-ai/DeepSeek-V3", "vllm",   "B200", "failed",
     "Output was repeating '!!!!!' tokens after first 12 chars — garbled.", "4571234"),
    ("mistralai/Mixtral-8x7B-Instruct-v0.1", "trtllm", "H100", "passed", "", ""),
    ("mistralai/Mixtral-8x7B-Instruct-v0.1", "vllm",   "H100", "passed", "", ""),
    ("google/gemma-3-1b-it", "trtllm", "L40s", "passed", "", ""),
    ("google/gemma-3-1b-it", "sglang", "L40s", "pending", "", ""),
]


def main():
    db.init_db()
    for model, backend, gpu, status, reason, bug in SAMPLES:
        db.upsert_test(
            model_name=model,
            backend=backend,
            gpu_name=gpu,
            test_status=status,
            ai_reason=reason,
            bug_id=bug or None,
        )
    print(f"Seeded {len(SAMPLES)} rows into {db.DB_PATH}")


if __name__ == "__main__":
    main()
