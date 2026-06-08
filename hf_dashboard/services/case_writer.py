"""Generate a new pytest case for `tests/examples/llm_ptq/test_deploy.py`.

This module is pure logic: it parses the model name, picks reasonable defaults
for `tensor_parallel_size` and `mini_sm`, decides which `test_<family>` function
the case belongs to, builds the `*ModelDeployerList(...)` snippet, and produces
a unified diff against the current file. **No git operations here.**

The caller (Inbox state) drives the user-editable fields and decides whether
to write the result to disk.

Design choices
==============
* We do not use libcst — the target file is hand-written Python with very
  consistent indentation and a single recurring shape (`@pytest.mark.parametrize`
  followed by a list of `ModelDeployerList(...)` calls). A small line-aware
  inserter is simpler to audit and produces less risky diffs than full AST
  round-tripping.
* Family detection is rule-based + extensible. Unknown families fall through
  to "append a new test function at the end of the file" (caller decides
  whether to allow that).
"""
from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Heuristic rules for tp_size / mini_sm / family
# ---------------------------------------------------------------------------

# Ordered list of (regex matched against the model name BASENAME, family slug).
# First match wins. The slug is used to build the function name `test_<slug>`.
# Each regex anchors at start and allows the family token to be immediately
# followed by a digit (e.g. Qwen3) or separator (-, _, .).
_FAMILY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)^deepseek(?:[-_.\d]|$)"),  "deepseek"),
    (re.compile(r"(?i)^llama(?:[-_.\d]|$)"),     "llama"),
    (re.compile(r"(?i)^qwen(?:[-_.\d]|$)"),      "qwen"),
    (re.compile(r"(?i)^qwq(?:[-_.\d]|$)"),       "qwen"),
    (re.compile(r"(?i)^gemma(?:[-_.\d]|$)"),     "gemma"),
    (re.compile(r"(?i)^phi(?:[-_.\d]|$)"),       "phi"),
    (re.compile(r"(?i)^mixtral(?:[-_.\d]|$)"),   "mixtral"),
    (re.compile(r"(?i)^mistral(?:[-_.\d]|$)"),   "mistral"),
    (re.compile(r"(?i)^nemotron(?:[-_.\d]|$)"),  "nemotron"),
    (re.compile(r"(?i)^kimi(?:[-_.\d]|$)"),      "kimi"),
    (re.compile(r"(?i)^minimax(?:[-_.\d]|$)"),   "minimax"),
    (re.compile(r"(?i)^step(?:[-_.\d]|$)"),      "step"),
    (re.compile(r"(?i)^glm(?:[-_.\d]|$)"),       "glm"),
]

# Per-family fallback tp_size when the model name doesn't expose a param count.
# Derived from the user's existing cases in test_deploy.py.
_FAMILY_DEFAULT_TP: dict[str, int] = {
    "deepseek": 8,   # R1 / V3 family is 671B
    "kimi":     8,   # K2 is ~556G
    "glm":      8,   # GLM-4.7 is 671B
    "minimax":  4,
    "step":     8,
}


def _basename(model_id: str) -> str:
    """`nvidia/Llama-3.1-8B-Instruct-FP8` -> `Llama-3.1-8B-Instruct-FP8`."""
    return model_id.split("/")[-1]


def detect_family(model_id: str) -> str:
    """Return a family slug (e.g. `llama`) or empty string if unknown."""
    base = _basename(model_id)
    for rx, slug in _FAMILY_RULES:
        if rx.match(base):
            return slug
    return ""


# Extract the parameter count (in billions). Handles "8B" / "70B" / "405B" /
# and MoE forms like "30B-A3B" / "235B-A22B" (we keep the total).
_PARAM_COUNT_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(\d+(?:\.\d+)?)B(?:[-_]|$)")


def detect_param_count_b(model_id: str) -> float | None:
    base = _basename(model_id)
    m = _PARAM_COUNT_RE.search(base)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def infer_tensor_parallel(param_b: float | None, family: str = "") -> int:
    """Match the buckets the user already established in test_deploy.py.

    Falls back to a family-specific default (e.g. DeepSeek=8) when the model
    name doesn't expose a parameter count.
    """
    if param_b is None:
        return _FAMILY_DEFAULT_TP.get(family, 1)
    if param_b <= 8:
        return 1
    if param_b <= 32:
        return 2
    if param_b <= 200:
        return 4
    return 8


_FP8_RE = re.compile(r"(?i)(?<![A-Za-z0-9])fp8(?![A-Za-z0-9])")
_NVFP4_RE = re.compile(r"(?i)nvfp4")


def infer_mini_sm(model_id: str) -> int | None:
    """`NVFP4` → 100 (B200), `FP8` → 89 (H100/Ada), else None (omit)."""
    base = _basename(model_id)
    if _NVFP4_RE.search(base):
        return 100
    if _FP8_RE.search(base):
        return 89
    return None


# ---------------------------------------------------------------------------
# Case spec: the exact thing we want to append
# ---------------------------------------------------------------------------

@dataclass
class CaseSpec:
    model_id: str
    backend: tuple[str, ...] = ("trtllm", "vllm", "sglang")
    tensor_parallel_size: int = 1
    mini_sm: int | None = None
    family: str = ""   # slug; empty means "new family"

    @classmethod
    def from_model(cls, model_id: str) -> "CaseSpec":
        fam = detect_family(model_id)
        return cls(
            model_id=model_id,
            tensor_parallel_size=infer_tensor_parallel(
                detect_param_count_b(model_id), fam
            ),
            mini_sm=infer_mini_sm(model_id),
            family=fam,
        )

    def to_block(self, indent: str = "    ") -> str:
        """Render as a `*ModelDeployerList(...),` snippet matching the file's style.

        `indent` is the indent of the OUTER `*ModelDeployerList(` line. Field
        lines (model_id, backend, …) get one extra indent level (4 spaces).
        """
        # Backends look like: ("vllm", "trtllm", "sglang")
        backends_repr = "(" + ", ".join(f'"{b}"' for b in self.backend) + ")"
        if len(self.backend) == 1:
            backends_repr = "(" + f'"{self.backend[0]}",' + ")"

        sub = indent + "    "  # fields indent one level deeper than the call
        lines = [
            f"{indent}*ModelDeployerList(",
            f'{sub}model_id="{self.model_id}",',
            f"{sub}backend={backends_repr},",
            f"{sub}tensor_parallel_size={self.tensor_parallel_size},",
        ]
        if self.mini_sm is not None:
            lines.append(f"{sub}mini_sm={self.mini_sm},")
        lines.append(f"{indent}),")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# File analysis & insertion
# ---------------------------------------------------------------------------

@dataclass
class FunctionLocation:
    """Where a `def test_<family>(command):` lives in the file."""
    name: str
    func_lineno: int                       # 1-based, the `def` line
    decorator_lineno: int                  # the `@pytest.mark.parametrize` line
    parametrize_list_open_lineno: int      # the `[` line opening the case list
    parametrize_list_close_lineno: int     # the `]` line closing the case list


@dataclass
class GenerationResult:
    spec: CaseSpec
    target_function: str | None      # None means "new function appended at EOF"
    diff: str                        # unified diff (preview)
    new_content: str                 # full file content after the insertion
    notes: list[str] = field(default_factory=list)
    already_exists_in: str | None = None  # function name if duplicate found


def find_existing_model(file_path: str | Path, model_id: str) -> str | None:
    """Return the name of the test_* function that already references `model_id`,
    or None if the model isn't in the file yet. Match is exact on the value of
    `model_id="..."`.
    """
    src = Path(file_path).read_text()
    needle = f'model_id="{model_id}"'
    idx = src.find(needle)
    if idx < 0:
        return None
    # Walk forward through the file to find the enclosing `def test_*` after
    # this match. Easier: walk backward through the source lines to find the
    # nearest `def test_` ABOVE the match (test functions enclose their
    # parametrize list, so the def comes earlier in the source line order
    # for a fresh single-function file, but in this file def comes AFTER the
    # decorator — so we walk forward instead.)
    after = src[idx:]
    m = re.search(r"\n\s*def\s+(test_[A-Za-z0-9_]+)\s*\(", after)
    return m.group(1) if m else "<unknown function>"


def find_test_functions(file_path: str | Path) -> dict[str, FunctionLocation]:
    """Parse `test_deploy.py` and return all `test_*` functions that take a
    `command` arg and use `@pytest.mark.parametrize`."""
    src = Path(file_path).read_text()
    tree = ast.parse(src)
    src_lines = src.splitlines()

    results: dict[str, FunctionLocation] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        if not any(a.arg == "command" for a in node.args.args):
            continue

        # Find a parametrize decorator
        decorator_line = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                f = dec.func
                if (isinstance(f, ast.Attribute) and f.attr == "parametrize"
                        and isinstance(f.value, ast.Attribute) and f.value.attr == "mark"):
                    decorator_line = dec.lineno
                    break
        if decorator_line is None:
            continue

        # Find the [ ... ] list bounds for the second arg of parametrize.
        # Easiest: scan source lines between decorator_line and the def line
        # for the first `[` after the parametrize call.
        open_line = None
        for i in range(decorator_line - 1, node.lineno):
            if "[" in src_lines[i] and "parametrize" not in src_lines[i] or src_lines[i].strip() == "[":
                # heuristic: pick the first standalone `[` line
                if src_lines[i].rstrip().endswith("["):
                    open_line = i + 1
                    break
        # Fallback: first line that has just `[`
        if open_line is None:
            for i in range(decorator_line - 1, node.lineno):
                if src_lines[i].strip() == "[":
                    open_line = i + 1
                    break

        # Find the matching close `]` by bracket counting starting from open_line.
        close_line = None
        if open_line is not None:
            depth = 0
            for i in range(open_line - 1, len(src_lines)):
                for ch in src_lines[i]:
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            close_line = i + 1
                            break
                if close_line is not None:
                    break

        if open_line is None or close_line is None:
            continue

        results[node.name] = FunctionLocation(
            name=node.name,
            func_lineno=node.lineno,
            decorator_lineno=decorator_line,
            parametrize_list_open_lineno=open_line,
            parametrize_list_close_lineno=close_line,
        )
    return results


def insert_case(file_path: str | Path, spec: CaseSpec,
                allow_new_family: bool = True) -> GenerationResult:
    """Plan the insertion of a new case. Does NOT write to disk.

    Returns a `GenerationResult` with `new_content` (full file after the edit)
    and `diff` (unified diff vs current content). Caller writes if accepted.

    If the model_id already exists in the file, the result will have empty
    `diff` / `new_content == src` and `already_exists_in` populated with the
    name of the function that already references it.
    """
    path = Path(file_path)
    src = path.read_text()
    src_lines = src.splitlines()
    notes: list[str] = []

    # Duplicate guard — bail before any edit planning.
    existing = find_existing_model(path, spec.model_id)
    if existing:
        return GenerationResult(
            spec=spec,
            target_function=existing,
            diff="",
            new_content=src,
            notes=[f"Model `{spec.model_id}` already has a case in `{existing}` — nothing to add."],
            already_exists_in=existing,
        )

    fn_locs = find_test_functions(path)

    # Decide which function to extend.
    target = f"test_{spec.family}" if spec.family else ""
    target_loc = fn_locs.get(target) if target else None

    if target_loc:
        # Match the indent of the *existing* list items so the new block looks
        # consistent. Walk lines between [ and ] backward to find the indent
        # of the last `*ModelDeployerList(` (or similar `*Something(` ) entry.
        item_indent = _detect_item_indent(
            src_lines,
            target_loc.parametrize_list_open_lineno - 1,
            target_loc.parametrize_list_close_lineno - 1,
        )
        block = spec.to_block(indent=item_indent)
        # Insert immediately before the closing `]` line.
        close_idx = target_loc.parametrize_list_close_lineno - 1  # 0-based
        new_lines = src_lines[:close_idx] + block.split("\n") + src_lines[close_idx:]
        target_function = target
        notes.append(
            f"Appending to existing function `{target}` "
            f"(closing `]` at line {target_loc.parametrize_list_close_lineno}, "
            f"item indent = {len(item_indent)} spaces)."
        )
        block_for_new_fn = None
    else:
        # New family — render the block with the file's dominant 8-space item indent.
        block_for_new_fn = spec.to_block(indent=" " * 8)
        if not allow_new_family:
            raise ValueError(
                f"No matching test_<family> function for {spec.model_id!r} "
                f"(detected family: {spec.family or 'unknown'}), and "
                "allow_new_family=False."
            )
        # Append a brand-new test function at end of file.
        slug = spec.family or _safe_slug(_basename(spec.model_id))
        new_func_name = f"test_{slug}"
        template = _new_function_template(new_func_name, block_for_new_fn)
        tail = ["", "", template, ""]
        new_lines = src_lines + tail
        target_function = new_func_name
        notes.append(
            f"No existing function for family `{slug}` — appended a new "
            f"`def {new_func_name}(command)` at end of file."
        )

    new_content = "\n".join(new_lines)
    if not new_content.endswith("\n"):
        new_content += "\n"

    diff = "".join(
        difflib.unified_diff(
            src.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=str(path) + " (before)",
            tofile=str(path) + " (after)",
            n=3,
        )
    )
    return GenerationResult(
        spec=spec,
        target_function=target_function,
        diff=diff,
        new_content=new_content,
        notes=notes,
    )


def _detect_item_indent(src_lines: list[str], open_idx: int, close_idx: int) -> str:
    """Return the indent string used by existing entries in a parametrize list.

    Scans from the closing `]` backward looking for a line that starts a list
    item (begins with `*` after whitespace, or a `ModelDeployer(` call). Falls
    back to 8 spaces (the dominant style in this file) if nothing matches.
    """
    for i in range(close_idx - 1, max(open_idx, 0) - 1, -1):
        line = src_lines[i]
        stripped = line.lstrip()
        if stripped.startswith("*") or stripped.startswith("ModelDeployer"):
            return line[: len(line) - len(stripped)]
    return " " * 8


def _safe_slug(name: str) -> str:
    """Convert a free-form model basename into a safe pytest function suffix."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return s or "model"


def _new_function_template(fn_name: str, block: str) -> str:
    return (
        "@pytest.mark.parametrize(\n"
        '    "command",\n'
        "    [\n"
        f"{block}\n"
        "    ],\n"
        "    ids=idfn,\n"
        ")\n"
        f"def {fn_name}(command):\n"
        "    command.run()"
    )
