"""AI-powered analyzer for HF model deployment .out logs.

The analyzer extracts everything from the log itself - backend, GPU, models
under test, pass/fail verdict per model, and a sample of normal output text
for passed models. The caller only needs to provide the log file path.

The slurm log for a single run can be 1-10 MB and tests dozens of models in
sequence. We don't send the raw file to the model:

1. Split the log on `Deploying model: ...` anchor lines.
2. For each per-model section, keep a head snippet (deploy command +
   start-of-loading) and a tail snippet (test prompts + final markers).
   Drop the megabytes of CUDA/TRT compilation noise in the middle.
3. Always keep the job header (GPU info, S3 mounts) and run footer.

This typically reduces an 800 KB log to ~80-150 KB of relevant context.

Uses the OpenAI-compatible NVIDIA Inference gateway, which proxies Claude
via AWS Bedrock. Configuration via env:

    NVIDIA_API_KEY            (required)   Inference key from
                                           https://inference.nvidia.com/key-management
    NVIDIA_INFERENCE_BASE_URL (optional)   default: https://inference-api.nvidia.com/v1
    LLM_MODEL                 (optional)   default: aws/anthropic/claude-opus-4-5
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field


DEFAULT_BASE_URL = "https://inference-api.nvidia.com/v1"
DEFAULT_MODEL = "aws/anthropic/claude-opus-4-5"

# Smart-extraction budget. Real-world logs we've seen:
#   - 45 models * ~18 KB raw section each = 810 KB total raw
#   - Compressed to 45 * 4 KB = ~180 KB after head/tail-per-section keeps
# We aim to stay under ~200K tokens of context (rough upper bound).
JOB_HEADER_BYTES = 5_000        # GPU info, Docker image, S3 mounts
JOB_FOOTER_BYTES = 3_000        # final cleanup
PER_MODEL_HEAD_BYTES = 1_200    # deploy command + initial setup
PER_MODEL_TAIL_BYTES = 4_500    # test prompts + final markers (most signal)
# Hard cap on final payload. Bedrock Opus 4.5 context window is 200K tokens.
# At ~3.3 chars/token for log content, 500KB ≈ 150K tokens — leaves headroom
# for the system prompt and ~32K completion. Was 800KB which blew past 200K.
ABSOLUTE_MAX_BYTES = 500_000

# Regex matching the anchor lines that delimit per-model sections.
_MODEL_ANCHOR_RE = re.compile(
    r"^Deploying model:\s*(\S+)\s+with backend:\s*(\S+)\s*$",
    re.MULTILINE,
)


SYSTEM_PROMPT = """You are a QA engineer analyzing an LLM-deployment slurm .out log.

The log is from a slurm job that deploys MANY HuggingFace models sequentially on
one inference backend (TensorRT-LLM, vLLM, or SGLang), sends test prompts, and
prints the model output. A single log may cover 1, 10, or 50+ models.

The log has been pre-processed: per-model sections are demarcated by header
lines like `>>> MODEL i/N: <name>` and middle-noise (CUDA / TRT compilation)
has been elided. Trust these markers and report ONE result per marker — do
not merge models, do not drop models.

Extract ALL of the following:

ENVIRONMENT (from the JOB HEADER at the top, plus per-model boot logs):
- backend: trtllm / vllm / sglang / unknown
- backend_version: the version printed by the backend (e.g. "trtllm version: 0.21.0rc1" → "0.21.0rc1", or vllm/sglang version). "" if not found.
- gpu: GPU name (H100, H200, A100, B200, L40s, GB200, ...) — "unknown" if not detectable
- gpu_count: integer (default 1)
- docker_image: full container image tag if visible (e.g. "nvcr.io/nvidia/tritonserver:25.04-trtllm-py3"), else ""
- container_id: short Docker container id (first 12 chars) if printed, else ""
- driver_version: NVIDIA driver version like "595.58.03", else ""
- cuda_version: CUDA version like "12.6", else ""
- node: hostname / slurm node name (e.g. "umbriel-b200-069"), else ""
- job_id: slurm job id (numeric, from `Job ID: xxxxxx`), else ""
- extra_notes: cluster/partition/anything else useful, else ""

FOR EACH `>>> MODEL i/N:` MARKER (in order):
- model_name: the model id printed after the marker (keep the org/ prefix, e.g. "nvidia/Llama-3.1-8B-Instruct-FP8")
- verdict: "passed" / "failed" / "inconclusive"
- reason: 1-2 sentences summarizing the verdict (concise — details go in `evidence`)
- error_type: if failed, ONE of: oom / cuda_error / garbled_output /
  unsupported_architecture / timeout / import_error / empty_output / other.
  "" if passed or inconclusive.
- sample_output: ALL prompt/response pairs for this model, copied verbatim
  from the log, joined by newlines. Format each pair as:
      Prompt: '<prompt text>'
      Generated text: '<response text>'
  If passed: include EVERY `Prompt:` / `Generated text:` pair you can find for
  this model (do not abbreviate, do not pick "one representative" — give them all).
  If failed: copy the full error snippet (traceback / RuntimeError / "out of
  memory" / etc.) so the user can debug. Aim for a complete picture; up to
  ~1500 characters is fine, more if there are many prompts.
  Empty string only if inconclusive AND no useful text exists.

PASS criteria (ALL must hold):
- Section contains one or more `Prompt: '...', Generated text: '...'` pairs
  (or equivalent) where the generated text is coherent natural language.
- No Traceback / RuntimeError / CUDA error AFTER text generation started.

FAIL criteria (any one):
- Section ends mid-deploy (no `Prompt:`/`Generated text:` produced).
- Output is garbled (repeating tokens, only punctuation, only <unk>).
- Section contains a Traceback / RuntimeError / OOM / CUDA error.
- Section ends abruptly without the `✓ Removed: ...` cleanup marker AND
  has no Prompt/Generated-text pairs.

INCONCLUSIVE: section is truncated or you genuinely cannot tell.

Provide a 1-sentence `summary` of the overall run."""


class TestEnvironment(BaseModel):
    backend: Literal["trtllm", "vllm", "sglang", "unknown"]
    backend_version: str = ""
    gpu: str = Field(description="GPU name or 'unknown'")
    gpu_count: int = 1
    docker_image: str = ""
    container_id: str = ""
    driver_version: str = ""
    cuda_version: str = ""
    node: str = ""
    job_id: str = ""
    extra_notes: str = ""


class ModelResult(BaseModel):
    model_name: str = Field(description="HuggingFace repo id of the model under test")
    verdict: Literal["passed", "failed", "inconclusive"]
    reason: str
    error_type: str = ""
    sample_output: str = ""


class LogAnalysis(BaseModel):
    environment: TestEnvironment
    models: list[ModelResult]
    summary: str


# ---------------------------------------------------------------------------
# Log preprocessing
# ---------------------------------------------------------------------------

def _slice(text: str, lo: int, hi: int) -> str:
    lo = max(0, lo)
    hi = min(len(text), hi)
    return text[lo:hi] if lo < hi else ""


def _model_count(content: str) -> int:
    return len(_MODEL_ANCHOR_RE.findall(content))


def _build_extracted_payload(content: str) -> str:
    """Return a compact textual representation of the log for the LLM.

    If we find at least one `Deploying model:` anchor, we split the log on
    those anchors and keep only the start/end of each per-model section.
    Otherwise (small or unstructured log) we return the file in full
    up to ABSOLUTE_MAX_BYTES.
    """
    anchors = [(m.start(), m.group(1)) for m in _MODEL_ANCHOR_RE.finditer(content)]

    if not anchors:
        # Small or unstructured log — return as much as fits.
        return content[:ABSOLUTE_MAX_BYTES]

    parts: list[str] = []
    parts.append("=== JOB HEADER ===")
    parts.append(_slice(content, 0, JOB_HEADER_BYTES).rstrip())
    parts.append("")

    total = len(anchors)
    for i, (start, name) in enumerate(anchors):
        end = anchors[i + 1][0] if i + 1 < total else len(content)
        section = _slice(content, start, end)
        parts.append(f">>> MODEL {i + 1}/{total}: {name}")
        if len(section) <= PER_MODEL_HEAD_BYTES + PER_MODEL_TAIL_BYTES:
            parts.append(section.rstrip())
        else:
            head = section[:PER_MODEL_HEAD_BYTES].rstrip()
            tail = section[-PER_MODEL_TAIL_BYTES:].lstrip()
            parts.append(head)
            parts.append("... [CUDA/TRT compile noise elided] ...")
            parts.append(tail)
        parts.append("")

    parts.append("=== JOB FOOTER ===")
    parts.append(_slice(content, max(0, len(content) - JOB_FOOTER_BYTES), len(content)).lstrip())

    payload = "\n".join(parts)
    if len(payload) > ABSOLUTE_MAX_BYTES:
        # Should be rare; truncate from the middle (preserve per-model markers
        # at start, footer at end).
        keep_each_side = ABSOLUTE_MAX_BYTES // 2 - 100
        payload = (
            payload[:keep_each_side]
            + "\n\n... [PAYLOAD TRUNCATED TO FIT BUDGET] ...\n\n"
            + payload[-keep_each_side:]
        )
    return payload


def read_log_extracted(path: str | Path) -> tuple[str, int, int]:
    """Read a log file and return (extracted_payload, total_size_bytes, model_count)."""
    p = Path(path)
    size = p.stat().st_size
    raw = p.read_bytes().decode("utf-8", errors="replace")
    return _build_extracted_payload(raw), size, _model_count(raw)


# ---------------------------------------------------------------------------
# OpenAI client + analyzer
# ---------------------------------------------------------------------------

def _make_client() -> OpenAI:
    """Construct an OpenAI client pointed at the NVIDIA Inference gateway."""
    api_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("NVIDIA_INFERENCE_BASE_URL", DEFAULT_BASE_URL)
    return OpenAI(api_key=api_key, base_url=base_url)


def _build_user_content(payload: str, total_size: int, model_count: int,
                         out_file_path: str | Path) -> str:
    return f"""Log file: {out_file_path}
Total raw size: {total_size:,} bytes
Models found via `Deploying model:` anchors: {model_count}

The log below has been pre-extracted: per-model sections are bounded by
`>>> MODEL i/N: <name>` markers. Report exactly {model_count} `models[]`
entries in the same order — one per marker.

--- LOG (pre-extracted) ---
{payload}
--- END LOG ---

Extract environment, per-model results (one entry per >>> MODEL marker),
and overall summary."""


def analyze_log(out_file_path: str | Path) -> LogAnalysis:
    """Run the model on the log file. Returns the full structured analysis.

    Raises FileNotFoundError if missing; openai.APIError on API failure.
    """
    payload, total_size, model_count = read_log_extracted(out_file_path)
    user_content = _build_user_content(payload, total_size, model_count, out_file_path)

    client = _make_client()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    response = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=LogAnalysis,
        max_tokens=32000,
        temperature=0.1,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError(
            "Model returned a response that could not be parsed against the "
            "LogAnalysis schema (refusal or schema violation)."
        )
    return parsed


def _snapshot_to_dict(parsed) -> dict | None:
    """Normalize a snapshot (Pydantic instance or partial dict) to a plain dict.

    Returns None if there is nothing useful yet.
    """
    if parsed is None:
        return None
    if hasattr(parsed, "model_dump"):
        try:
            return parsed.model_dump()
        except Exception:
            return None
    if isinstance(parsed, dict):
        return parsed
    return None


def analyze_log_stream(out_file_path: str | Path):
    """Stream the analysis from the model.

    Yields incremental snapshots (as plain dicts) as the model emits more JSON.
    Each yielded dict has at least as many `models` entries as the previous
    yield. The final yield is the fully-parsed result as a dict.

    Yielded snapshots may contain partial fields — callers should use
    dict.get(...) with defaults rather than attribute access.

    Raises FileNotFoundError if missing; openai.APIError on API failure.
    """
    payload, total_size, model_count = read_log_extracted(out_file_path)
    user_content = _build_user_content(payload, total_size, model_count, out_file_path)

    client = _make_client()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    with client.beta.chat.completions.stream(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=LogAnalysis,
        max_tokens=32000,
        temperature=0.1,
    ) as stream:
        last_yield_count = -1
        for _event in stream:
            try:
                snapshot = stream.current_completion_snapshot
                parsed = snapshot.choices[0].message.parsed
            except (AttributeError, IndexError, TypeError):
                continue
            data = _snapshot_to_dict(parsed)
            if not data:
                continue
            models = data.get("models") or []
            current_count = len(models)
            if current_count > last_yield_count:
                last_yield_count = current_count
                yield data

        # Final snapshot
        final = stream.get_final_completion()
        try:
            final_parsed = final.choices[0].message.parsed
        except (AttributeError, IndexError):
            final_parsed = None
        final_data = _snapshot_to_dict(final_parsed)
        if not final_data:
            raise RuntimeError(
                "Model returned a response that could not be parsed against the "
                "LogAnalysis schema (refusal or schema violation)."
            )
        yield final_data


def api_key_configured() -> bool:
    return bool(os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENAI_API_KEY"))
