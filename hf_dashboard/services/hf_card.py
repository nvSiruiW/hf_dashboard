"""Read a HuggingFace model card and ask Claude (via NVIDIA Inference) which
inference backends the model card actually documents as supported.

Returned structure is per-backend: `yes` / `no` / `unclear` + a 1-sentence
reason. Result is JSON-serialized into `hf_models.ai_backend_suggestion` so
repeat clicks on the same model don't re-pay the API cost.
"""
from __future__ import annotations

import json
import os
from typing import Literal

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field

from hf_dashboard.services import db, log_analyzer


SUPPORT_LITERAL = Literal["yes", "unclear"]


class BackendSupport(BaseModel):
    supported: SUPPORT_LITERAL = Field(
        description="'yes' if the model card explicitly documents this backend "
                    "(code example, mention in Supported Runtime Engine(s), etc.); "
                    "'unclear' for anything else — not mentioned, ambiguous, OR "
                    "explicitly listed as not supported. All three cases collapse "
                    "to 'unclear' because the user treats them identically: "
                    "don't auto-test, let them decide."
    )
    reason: str = Field(
        description="One short sentence citing the specific evidence "
                    "(e.g. 'README has a vLLM serve example' / 'Not mentioned' / "
                    "'README says vLLM not supported for diffusion models')."
    )


class ModelCardAnalysis(BaseModel):
    trtllm: BackendSupport
    vllm: BackendSupport
    sglang: BackendSupport
    architecture: str = Field(
        default="",
        description="Model family / architecture string if the card mentions it (e.g. 'Llama-3.3', 'Qwen3').",
    )
    param_count: str = Field(
        default="",
        description="Parameter count string if mentioned (e.g. '550B', '30B-A3B').",
    )
    quantization: str = Field(
        default="",
        description="Quantization format if mentioned (e.g. 'NVFP4', 'FP8').",
    )
    notes: str = Field(
        default="",
        description="Anything special — non-standard launch flags, required libs, "
                    "tokenizer caveats. <=200 chars.",
    )


SYSTEM_PROMPT = """You are a QA engineer auditing a HuggingFace model card to
decide which inference backends — TensorRT-LLM (trtllm), vLLM (vllm), and
SGLang (sglang) — the model card actually documents as supported.

Use only TWO labels per backend: "yes" or "unclear".

A backend is "yes" iff the README has any of:
  - A code/bash example showing how to launch the model with that backend
    (e.g. `python -m vllm.entrypoints.openai...`, `trtllm-serve`,
    `python -m sglang.launch_server ...`).
  - The string in a "Supported Runtime Engine(s)" / "Inference Engines" /
    "Deployment" / similar section.
  - A clear positive English statement like "supports vLLM" / "runs with SGLang".

Mark "unclear" in ALL other cases: backend not mentioned, mentioned ambiguously,
or even explicitly listed as not-supported. The downstream consumer treats all
of these identically (default to off, let the user decide).

Never emit "no". Do not guess based on the model family.

Always include a 1-sentence `reason` per backend citing the evidence
(e.g. "README has vLLM serve example", "Not mentioned in card",
"README states vLLM does not support diffusion models").

Also extract architecture (Llama / Qwen / Mixtral / DeepSeek / etc.),
parameter count, and quantization format if the card states them."""


MODEL = log_analyzer.DEFAULT_MODEL
BASE_URL = log_analyzer.DEFAULT_BASE_URL


def _make_client() -> OpenAI:
    api_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("NVIDIA_INFERENCE_BASE_URL", BASE_URL)
    return OpenAI(api_key=api_key, base_url=base_url)


# ---------------------------------------------------------------------------
# Fetch the README
# ---------------------------------------------------------------------------

MAX_README_BYTES = 80_000   # tail anything longer; >20K tokens unnecessary


def fetch_model_card(model_id: str, timeout: float = 15.0) -> tuple[str, str | None]:
    """Return (readme_text, error). Empty text + error string on failure."""
    if not model_id or "/" not in model_id:
        return "", f"Invalid model id: {model_id!r}"

    url = f"https://huggingface.co/{model_id}/raw/main/README.md"
    headers = {}
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    except httpx.RequestError as e:
        return "", f"HF fetch failed: {type(e).__name__}: {e}"

    if resp.status_code == 404:
        return "", f"No README.md in repo {model_id} (HTTP 404)."
    if resp.status_code in (401, 403):
        if not tok:
            return "", (
                f"Model {model_id} is gated. Add HF_TOKEN to ~/.hf_dashboard/env "
                "and restart."
            )
        return "", (
            f"HF_TOKEN can't read {model_id} (HTTP {resp.status_code}). "
            "You may need to request access on the HF page."
        )
    if resp.status_code >= 400:
        return "", f"HF returned HTTP {resp.status_code}."

    text = resp.text or ""
    if len(text) > MAX_README_BYTES:
        text = text[:MAX_README_BYTES // 2] + "\n\n[... README truncated ...]\n\n" + text[-MAX_README_BYTES // 2:]
    return text, None


# ---------------------------------------------------------------------------
# Analyze with Claude
# ---------------------------------------------------------------------------

def analyze_card(model_id: str, readme: str) -> tuple[ModelCardAnalysis | None, str | None]:
    """Send the README to Claude (via NVIDIA Inference) for structured analysis."""
    if not readme.strip():
        return None, "Empty README — nothing to analyze."
    if not log_analyzer.api_key_configured():
        return None, "NVIDIA_API_KEY is not set."

    user_content = f"""Model: {model_id}

Below is the model card README. Determine support per backend.

--- README ---
{readme}
--- END README ---

Analyze and produce a JSON object matching the schema."""

    try:
        client = _make_client()
        resp = client.beta.chat.completions.parse(
            model=os.environ.get("LLM_MODEL", MODEL),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format=ModelCardAnalysis,
            max_tokens=2048,
            temperature=0.1,
        )
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    parsed = resp.choices[0].message.parsed
    if parsed is None:
        return None, "Model returned an unparseable response (refusal or schema violation)."
    return parsed, None


# ---------------------------------------------------------------------------
# Cache-aware entrypoint
# ---------------------------------------------------------------------------

def get_or_analyze(
    model_id: str,
    force: bool = False,
) -> tuple[ModelCardAnalysis | None, str | None, bool]:
    """Return (analysis, error, was_cached).

    - If `hf_models.ai_backend_suggestion` already has a cached analysis and
      `force=False`, decode it and return.
    - Otherwise fetch the README + analyze + persist + return.
    """
    if not force:
        row = db.get_hf_model(model_id)
        if row and row.get("ai_backend_suggestion"):
            try:
                data = json.loads(row["ai_backend_suggestion"])
                return ModelCardAnalysis.model_validate(data), None, True
            except Exception:
                pass  # cached blob unreadable — fall through to refetch

    readme, fetch_err = fetch_model_card(model_id)
    if fetch_err:
        return None, fetch_err, False

    analysis, err = analyze_card(model_id, readme)
    if err or analysis is None:
        return None, err, False

    # Persist for next time.
    try:
        db.upsert_hf_model(
            model_id,
            ai_backend_suggestion=analysis.model_dump_json(),
        )
    except Exception:
        pass  # cache write best-effort

    return analysis, None, False
