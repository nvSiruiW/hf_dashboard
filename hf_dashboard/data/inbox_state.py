"""State for the Inbox page (Phase 1).

Each row in `hf_models` with `review_status == 'pending'` is shown as a card.
Per-card the user can:
  • flip per-backend checkboxes (trtllm / vllm / sglang)
  • edit the S3 path + tick "uploaded" when relevant
  • click Triage  → write per-backend rows into `hf_model_tests` (status=pending)
                  → flip the model's review_status to 'triaged'
  • click Skip    → flip review_status to 'skipped' (won't show up here again
                    but stays in DB so re-ingesting doesn't dupe-add)
"""
from __future__ import annotations

import reflex as rx

from hf_dashboard.data.common import BACKENDS, detect_eagle3
from hf_dashboard.services import case_writer, db, git_ops, hf_card, working_copy


class InboxItem(rx.Base):
    """One inbox card. Mirrors hf_models row + per-backend checkboxes."""
    model_name: str = ""
    hf_url: str = ""
    release_date: str = ""
    source_collection: str = ""
    architecture: str = ""
    param_count: str = ""
    notes: str = ""
    requires_s3_upload: bool = False
    s3_uploaded: bool = False
    s3_path: str = ""
    review_status: str = "pending"
    created_at: str = ""

    # Per-backend selection (mirrors BACKENDS order: trtllm / vllm / sglang).
    test_trtllm: bool = True
    test_vllm: bool = True
    test_sglang: bool = True

    # AI verdicts (from cached hf_models.ai_backend_suggestion). Empty when
    # not yet analyzed; otherwise "yes" / "no" / "unclear".
    trtllm_support: str = ""
    trtllm_reason: str = ""
    vllm_support: str = ""
    vllm_reason: str = ""
    sglang_support: str = ""
    sglang_reason: str = ""
    has_analysis: bool = False   # True iff at least one of the support fields is non-empty

    # Multi-select for batch Jenkins trigger. Ephemeral; resets on page reload.
    selected_for_trigger: bool = False


class InboxState(rx.State):
    items: list[InboxItem] = []

    # "Manually add model" form state
    show_add_form: bool = False
    new_model_name: str = ""
    new_hf_url: str = ""

    backends: list[str] = list(BACKENDS)

    # ── Bulk analyze progress ────────────────────────────────────────────
    bulk_running: bool = False
    bulk_progress: str = ""        # e.g. "Analyzing 3/9: nvidia/Foo …"
    bulk_done_count: int = 0
    bulk_error_count: int = 0

    # ── Case-generator modal ─────────────────────────────────────────────
    gen_open: bool = False
    gen_model_name: str = ""           # model being processed
    gen_backend_trtllm: bool = True
    gen_backend_vllm: bool = True
    gen_backend_sglang: bool = True
    gen_tp_size: int = 1
    gen_mini_sm_value: int = 0         # 0 means "omit"
    gen_omit_mini_sm: bool = True      # checkbox: if True, mini_sm is omitted
    gen_target_function: str = ""      # "test_llama" / "test_deepseek" / "<NEW>"
    gen_notes: str = ""                # human-readable notes (e.g. "new family")
    gen_diff: str = ""                 # unified diff preview
    gen_target_file: str = ""          # absolute path of file to be modified
    gen_error: str = ""                # populated when generation fails
    gen_applied_at: str = ""           # set after Apply succeeds (clears on close)
    gen_already_exists_in: str = ""    # function name if the model is already in the file

    # ── Git workflow state (ACT 2) ───────────────────────────────────────
    git_initialized: bool = False           # is the fork cloned?
    git_current_branch: str = ""
    git_last_commit_sha: str = ""
    git_last_commit_subject: str = ""
    git_ahead: int = 0                      # commits ahead of origin/<branch>
    git_behind: int = 0
    git_has_uncommitted: bool = False
    git_has_unpushed: bool = False
    git_branch_url: str = ""
    git_status_error: str = ""

    # Push action state
    push_running: bool = False
    push_message: str = ""                  # status / result message
    push_kind: str = ""                     # "" / "success" / "error"

    # Last commit produced by Apply (for inline display in modal)
    gen_last_commit_sha: str = ""
    gen_last_commit_subject: str = ""

    # ── HF model-card AI analysis (Phase 2) ──────────────────────────────
    gen_card_loading: bool = False
    gen_card_error: str = ""
    gen_card_analyzed: bool = False          # whether we have an analysis result yet
    gen_card_cached: bool = False            # True if loaded from DB cache
    gen_trtllm_support: str = ""             # "yes" / "no" / "unclear"
    gen_trtllm_reason: str = ""
    gen_vllm_support: str = ""
    gen_vllm_reason: str = ""
    gen_sglang_support: str = ""
    gen_sglang_reason: str = ""
    gen_card_architecture: str = ""
    gen_card_param_count: str = ""
    gen_card_quantization: str = ""
    gen_card_notes: str = ""

    # --- Lifecycle --------------------------------------------------------

    def load(self):
        rows = db.list_hf_models(review_status="pending")
        self.items = [self._row_to_item(r) for r in rows]
        self._refresh_git_status()

    def _refresh_git_status(self):
        st = git_ops.status()
        self.git_initialized = st.initialized
        self.git_current_branch = st.current_branch
        self.git_last_commit_sha = st.last_commit_sha
        self.git_last_commit_subject = st.last_commit_subject
        self.git_ahead = st.ahead
        self.git_behind = st.behind
        self.git_has_uncommitted = st.has_uncommitted
        self.git_has_unpushed = st.has_unpushed
        self.git_branch_url = git_ops.branch_url()
        self.git_status_error = st.error

    @staticmethod
    def _row_to_item(r: dict) -> InboxItem:
        # Cached HF card analysis sets the per-backend checkbox default.
        # Strict policy: ONLY check the box when the AI verdict is "yes".
        # "no" / "unclear" / missing all leave the box unchecked — the user
        # can flip it on if they want to test anyway.
        # When no analysis at all exists, default everything to True so the
        # user isn't forced to manually check 3 boxes per new card.
        import json as _json
        sup_trtllm = sup_vllm = sup_sglang = ""
        rsn_trtllm = rsn_vllm = rsn_sglang = ""
        chk_trtllm = chk_vllm = chk_sglang = True   # used only when no analysis
        cache = r.get("ai_backend_suggestion") or ""
        if cache:
            try:
                data = _json.loads(cache)
                t = (data.get("trtllm") or {})
                v = (data.get("vllm") or {})
                s = (data.get("sglang") or {})
                sup_trtllm = (t.get("supported") or "").strip()
                sup_vllm   = (v.get("supported") or "").strip()
                sup_sglang = (s.get("supported") or "").strip()
                rsn_trtllm = t.get("reason") or ""
                rsn_vllm   = v.get("reason") or ""
                rsn_sglang = s.get("reason") or ""
                # Strict policy: only "yes" gets checked.
                chk_trtllm = sup_trtllm == "yes"
                chk_vllm   = sup_vllm   == "yes"
                chk_sglang = sup_sglang == "yes"
            except Exception:
                pass

        return InboxItem(
            model_name=r["model_name"] or "",
            hf_url=r["hf_url"] or "",
            release_date=r["release_date"] or "",
            source_collection=r["source_collection"] or "",
            architecture=r["architecture"] or "",
            param_count=r["param_count"] or "",
            notes=r["notes"] or "",
            requires_s3_upload=bool(r["requires_s3_upload"]),
            s3_uploaded=bool(r["s3_uploaded"]),
            s3_path=r["s3_path"] or "",
            review_status=r["review_status"] or "pending",
            created_at=r["created_at"] or "",
            test_trtllm=chk_trtllm,
            test_vllm=chk_vllm,
            test_sglang=chk_sglang,
            trtllm_support=sup_trtllm,
            trtllm_reason=rsn_trtllm,
            vllm_support=sup_vllm,
            vllm_reason=rsn_vllm,
            sglang_support=sup_sglang,
            sglang_reason=rsn_sglang,
            has_analysis=bool(sup_trtllm or sup_vllm or sup_sglang),
        )

    # --- Manual add -------------------------------------------------------

    def toggle_add_form(self):
        self.show_add_form = not self.show_add_form
        if not self.show_add_form:
            self.new_model_name = ""
            self.new_hf_url = ""

    def set_new_model_name(self, v: str):
        self.new_model_name = v

    def set_new_hf_url(self, v: str):
        self.new_hf_url = v

    def add_model_manually(self):
        name = self.new_model_name.strip()
        if not name:
            yield rx.toast.error("Enter a model name like org/repo")
            return
        url = self.new_hf_url.strip() or f"https://huggingface.co/{name}"
        needs_s3 = detect_eagle3(name)
        db.upsert_hf_model(
            name,
            hf_url=url,
            requires_s3_upload=1 if needs_s3 else 0,
            review_status="pending",
        )
        self.new_model_name = ""
        self.new_hf_url = ""
        self.show_add_form = False
        self.load()
        yield rx.toast.success(f"Added {name}")

    # --- Per-card edits ---------------------------------------------------

    def _replace(self, idx: int, **changes) -> None:
        if not (0 <= idx < len(self.items)):
            return
        old = self.items[idx]
        merged = old.dict()
        merged.update(changes)
        new = list(self.items)
        new[idx] = InboxItem(**merged)
        self.items = new

    def toggle_backend(self, idx: int, backend: str):
        key = f"test_{backend}"
        if 0 <= idx < len(self.items):
            old = self.items[idx]
            current = getattr(old, key, False)
            self._replace(idx, **{key: not current})

    def toggle_select_for_trigger(self, idx: int):
        if 0 <= idx < len(self.items):
            self._replace(idx, selected_for_trigger=not self.items[idx].selected_for_trigger)

    def clear_trigger_selection(self):
        for i, it in enumerate(self.items):
            if it.selected_for_trigger:
                self._replace(i, selected_for_trigger=False)

    def set_s3_path(self, idx: int, value: str):
        self._replace(idx, s3_path=value)

    def toggle_s3_uploaded(self, idx: int):
        if 0 <= idx < len(self.items):
            self._replace(idx, s3_uploaded=not self.items[idx].s3_uploaded)

    def set_notes(self, idx: int, value: str):
        self._replace(idx, notes=value)

    # --- Triage / skip ----------------------------------------------------

    def triage(self, idx: int):
        if not (0 <= idx < len(self.items)):
            return
        item = self.items[idx]

        # Persist user-edited fields back to hf_models first.
        db.upsert_hf_model(
            item.model_name,
            s3_path=item.s3_path,
            s3_uploaded=1 if item.s3_uploaded else 0,
            requires_s3_upload=1 if item.requires_s3_upload else 0,
            notes=item.notes,
            review_status="triaged",
        )

        selected_backends = []
        if item.test_trtllm:
            selected_backends.append("trtllm")
        if item.test_vllm:
            selected_backends.append("vllm")
        if item.test_sglang:
            selected_backends.append("sglang")

        if not selected_backends:
            yield rx.toast.error("Pick at least one backend to test, or click Skip.")
            return

        # Block triage of an Eagle3 model that hasn't been uploaded yet —
        # otherwise the deploy job will fail.
        if item.requires_s3_upload and not item.s3_uploaded:
            yield rx.toast.error(
                "This model needs an S3 upload first. Tick 'S3 uploaded' or click Skip."
            )
            return

        # Write one hf_model_tests row per selected backend.
        for backend in selected_backends:
            db.upsert_test(
                model_name=item.model_name,
                backend=backend,
                gpu_name="",
                test_status="pending",
                hf_url=item.hf_url,
                hf_release_date=item.release_date,
                requires_s3_upload=1 if item.requires_s3_upload else 0,
                s3_uploaded=1 if item.s3_uploaded else 0,
                notes=item.notes,
            )

        # Optionally mark non-selected backends as 'unsupported' so the matrix
        # shows a clear "we explicitly don't test this" instead of a blank.
        for backend in self.backends:
            if backend not in selected_backends:
                db.upsert_test(
                    model_name=item.model_name,
                    backend=backend,
                    gpu_name="",
                    test_status="unsupported",
                    hf_url=item.hf_url,
                    notes="Marked unsupported during triage",
                )

        self.load()
        n = len(selected_backends)
        yield rx.toast.success(
            f"Triaged {item.model_name} → {n} backend{'s' if n != 1 else ''} pending in matrix"
        )

    def skip(self, idx: int):
        if not (0 <= idx < len(self.items)):
            return
        item = self.items[idx]
        db.upsert_hf_model(item.model_name, review_status="skipped")
        self.load()
        yield rx.toast.success(f"Skipped {item.model_name}")

    # --- Bulk pre-analyze every pending card ------------------------------

    def analyze_all_pending(self):
        """For each pending model without a cached HF analysis, fetch & cache it.

        Iterates synchronously and `yield`s after each one so the user sees
        progress live in the UI.
        """
        # Snapshot the list before we start (it'll be mutated by reloads).
        targets = list(self.items)
        if not targets:
            yield rx.toast.info("No pending models to analyze.")
            return

        # Filter to those without an analysis yet.
        todo = [t for t in targets if not t.has_analysis]
        if not todo:
            yield rx.toast.success("All pending models already analyzed.")
            return

        self.bulk_running = True
        self.bulk_done_count = 0
        self.bulk_error_count = 0
        total = len(todo)
        yield

        for i, item in enumerate(todo, start=1):
            self.bulk_progress = f"Analyzing {i}/{total}: {item.model_name}"
            yield
            try:
                _, err, _ = hf_card.get_or_analyze(item.model_name)
                if err:
                    self.bulk_error_count += 1
                else:
                    self.bulk_done_count += 1
            except Exception:
                self.bulk_error_count += 1
            yield

        self.bulk_running = False
        self.bulk_progress = ""
        # Reload items so the new cached analyses populate the cards.
        self.load()
        yield rx.toast.success(
            f"Analyzed {self.bulk_done_count}/{total} cards"
            + (f"  ({self.bulk_error_count} errors)" if self.bulk_error_count else "")
        )

    # --- Case generator (open / edit / recompute / apply) ----------------

    def open_generate(self, idx: int):
        """Open the case-generator modal for one inbox item.

        Initializes the modal's backend checkboxes from the CARD's current
        checkbox state (so any unchecks you've already done on the card carry
        through to the generated case), and pre-fills tp_size / mini_sm via
        rule-based defaults. The HF model card analysis is fetched/loaded for
        the badge display but does NOT clobber the checkboxes — the card has
        already absorbed the analysis at row-load time.
        """
        if not (0 <= idx < len(self.items)):
            return
        item = self.items[idx]
        spec = case_writer.CaseSpec.from_model(item.model_name)
        self.gen_model_name = item.model_name
        # Inherit checkbox state from the inbox card so the user's per-card
        # toggles drive the generated case 1:1.
        self.gen_backend_trtllm = item.test_trtllm
        self.gen_backend_vllm = item.test_vllm
        self.gen_backend_sglang = item.test_sglang
        self.gen_tp_size = spec.tensor_parallel_size
        if spec.mini_sm is None:
            self.gen_omit_mini_sm = True
            self.gen_mini_sm_value = 0
        else:
            self.gen_omit_mini_sm = False
            self.gen_mini_sm_value = spec.mini_sm
        self.gen_error = ""
        self.gen_applied_at = ""
        self.gen_already_exists_in = ""
        self.gen_target_file = str(working_copy.test_deploy_path())
        # Reset card-analysis state
        self._reset_card_state()
        self.gen_open = True
        # Push the modal-open + loading state immediately so the user sees
        # the spinner before the network round-trip to NVIDIA Inference.
        self.gen_card_loading = True
        self._recompute_diff()
        yield

        # Slow part: fetch + analyze HF README.
        analysis, err, cached = hf_card.get_or_analyze(item.model_name)
        self.gen_card_loading = False
        if err:
            self.gen_card_error = err
            yield
            return
        if analysis is None:
            self.gen_card_error = "Analysis returned no result."
            yield
            return

        self._apply_card_analysis(analysis, cached=cached)
        self._recompute_diff()
        yield

    def _reset_card_state(self):
        self.gen_card_loading = False
        self.gen_card_error = ""
        self.gen_card_analyzed = False
        self.gen_card_cached = False
        self.gen_trtllm_support = ""
        self.gen_trtllm_reason = ""
        self.gen_vllm_support = ""
        self.gen_vllm_reason = ""
        self.gen_sglang_support = ""
        self.gen_sglang_reason = ""
        self.gen_card_architecture = ""
        self.gen_card_param_count = ""
        self.gen_card_quantization = ""
        self.gen_card_notes = ""

    def _apply_card_analysis(self, analysis, cached: bool):
        """Update the modal's BADGE display from a (cached or fresh) analysis.

        Deliberately does NOT update the backend checkboxes — those follow the
        inbox card's state, which was set from this same analysis at row-load
        time. Touching them here would silently undo any user-flips made on
        the card.
        """
        self.gen_card_analyzed = True
        self.gen_card_cached = cached
        self.gen_trtllm_support = analysis.trtllm.supported
        self.gen_trtllm_reason = analysis.trtllm.reason
        self.gen_vllm_support = analysis.vllm.supported
        self.gen_vllm_reason = analysis.vllm.reason
        self.gen_sglang_support = analysis.sglang.supported
        self.gen_sglang_reason = analysis.sglang.reason
        self.gen_card_architecture = analysis.architecture
        self.gen_card_param_count = analysis.param_count
        self.gen_card_quantization = analysis.quantization
        self.gen_card_notes = analysis.notes

    def reanalyze_card(self):
        """Force a fresh HF model card fetch + Claude analysis, bypassing cache."""
        if not self.gen_model_name:
            return
        self.gen_card_loading = True
        self.gen_card_error = ""
        yield
        analysis, err, _ = hf_card.get_or_analyze(self.gen_model_name, force=True)
        self.gen_card_loading = False
        if err:
            self.gen_card_error = err
            yield
            return
        if analysis is None:
            self.gen_card_error = "Re-analysis returned no result."
            yield
            return
        self._apply_card_analysis(analysis, cached=False)
        self._recompute_diff()
        yield rx.toast.success("HF model card re-analyzed")

    def close_generate(self):
        self.gen_open = False
        self.gen_error = ""
        self.gen_applied_at = ""
        self.gen_diff = ""
        self.gen_last_commit_sha = ""
        self.gen_last_commit_subject = ""
        self.push_message = ""
        self.push_kind = ""

    def push_branch(self):
        """Push the auto-add-cases branch to the fork. Requires GITHUB_TOKEN
        (or ambient git credential helper) to be configured.
        """
        self.push_running = True
        self.push_message = "Pushing to fork…"
        self.push_kind = ""
        yield

        res = git_ops.push()
        self.push_running = False
        if res.ok:
            self._refresh_git_status()
            self.push_message = (
                f"Pushed {self.git_current_branch} to origin · "
                f"open the branch on GitHub to create a PR."
            )
            self.push_kind = "success"
            yield rx.toast.success(self.push_message)
        else:
            self.push_message = f"Push failed: {res.out.strip() or 'unknown error'}"
            self.push_kind = "error"
            yield rx.toast.error(self.push_message)

    def set_gen_tp_size(self, v: str):
        try:
            self.gen_tp_size = max(1, int(v))
        except (TypeError, ValueError):
            return
        self._recompute_diff()

    def set_gen_mini_sm_value(self, v: str):
        try:
            self.gen_mini_sm_value = max(0, int(v))
        except (TypeError, ValueError):
            return
        self._recompute_diff()

    def toggle_gen_omit_mini_sm(self):
        self.gen_omit_mini_sm = not self.gen_omit_mini_sm
        self._recompute_diff()

    def toggle_gen_backend(self, backend: str):
        if backend == "trtllm":
            self.gen_backend_trtllm = not self.gen_backend_trtllm
        elif backend == "vllm":
            self.gen_backend_vllm = not self.gen_backend_vllm
        elif backend == "sglang":
            self.gen_backend_sglang = not self.gen_backend_sglang
        self._recompute_diff()

    def _current_spec(self) -> "case_writer.CaseSpec":
        backends: list[str] = []
        if self.gen_backend_trtllm:
            backends.append("trtllm")
        if self.gen_backend_vllm:
            backends.append("vllm")
        if self.gen_backend_sglang:
            backends.append("sglang")
        return case_writer.CaseSpec(
            model_id=self.gen_model_name,
            backend=tuple(backends) if backends else ("trtllm",),
            tensor_parallel_size=self.gen_tp_size,
            mini_sm=None if self.gen_omit_mini_sm else self.gen_mini_sm_value,
            family=case_writer.detect_family(self.gen_model_name),
        )

    def _recompute_diff(self):
        """Re-run case_writer with the current editable fields to refresh diff."""
        self.gen_error = ""
        self.gen_already_exists_in = ""
        path, err = working_copy.ensure_sandbox()
        if err:
            self.gen_error = err
            self.gen_diff = ""
            self.gen_target_function = ""
            return
        spec = self._current_spec()
        try:
            result = case_writer.insert_case(path, spec, allow_new_family=True)
        except Exception as e:
            self.gen_error = f"{type(e).__name__}: {e}"
            self.gen_diff = ""
            self.gen_target_function = ""
            return
        self.gen_already_exists_in = result.already_exists_in or ""
        self.gen_diff = result.diff or "(no changes)"
        self.gen_target_function = result.target_function or ""
        self.gen_notes = " · ".join(result.notes) if result.notes else ""

    def apply_generate(self):
        """Write the generated content to the sandbox file."""
        from datetime import datetime

        if self.gen_already_exists_in:
            yield rx.toast.error(
                f"Already exists in {self.gen_already_exists_in} — nothing to apply."
            )
            return
        if not self.gen_diff or self.gen_diff == "(no changes)":
            self.gen_error = "Nothing to apply."
            yield rx.toast.error(self.gen_error)
            return

        path, err = working_copy.ensure_sandbox()
        if err:
            self.gen_error = err
            yield rx.toast.error(err)
            return

        spec = self._current_spec()
        try:
            result = case_writer.insert_case(path, spec, allow_new_family=True)
        except Exception as e:
            self.gen_error = f"{type(e).__name__}: {e}"
            yield rx.toast.error(self.gen_error)
            return

        if result.already_exists_in:
            yield rx.toast.error(
                f"Already exists in {result.already_exists_in} — nothing to apply."
            )
            self._recompute_diff()
            return

        _, write_err = working_copy.write_test_deploy(result.new_content)
        if write_err:
            self.gen_error = write_err
            yield rx.toast.error(write_err)
            return

        self.gen_applied_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Auto-commit on the auto-add-cases branch with DCO sign-off.
        # No push here — that's a separate explicit button.
        commit_msg = f"Add deploy test case for {spec.model_id}"
        commit_res = git_ops.add_and_commit(
            [working_copy.test_deploy_path()],
            message=commit_msg,
            signoff=True,
        )
        if commit_res.ok:
            # Pull fresh status to populate sha/subject.
            self._refresh_git_status()
            self.gen_last_commit_sha = self.git_last_commit_sha
            self.gen_last_commit_subject = self.git_last_commit_subject
            yield rx.toast.success(
                f"Applied + committed: {self.git_last_commit_sha} {commit_msg}"
            )
        else:
            self.gen_error = (
                f"File written, but git commit failed: {commit_res.out}"
            )
            yield rx.toast.error(self.gen_error)

        # Recompute diff so user can see "(no changes)" indicating idempotent apply.
        self._recompute_diff()

    # --- Computed vars ----------------------------------------------------

    @rx.var
    def items_count(self) -> int:
        return len(self.items)

    @rx.var
    def has_items(self) -> bool:
        return len(self.items) > 0

    @rx.var
    def selected_count(self) -> int:
        return sum(1 for it in self.items if it.selected_for_trigger)

    @rx.var
    def trigger_pattern(self) -> str:
        """Build a pytest `-k` filter from selected models.

        Uses the basename (`org/repo` -> `repo`) as a substring match. The
        resulting filter looks like:

            "Kimi-K2.6-NVFP4 or Qwen3.6-35B-A3B-NVFP4"

        pytest will keep any parametrized case whose id contains any of those
        substrings, which is the right grain for "test only the newly-added
        models in this batch".
        """
        names = [
            it.model_name.split("/")[-1]
            for it in self.items
            if it.selected_for_trigger
        ]
        return " or ".join(names)

    @rx.var
    def trigger_url(self) -> str:
        """Pre-filled URL to /trigger.

        Passes the pytest pattern (from selected model basenames) and the
        current dashboard branch as `modelopt_branch` — Jenkins uses
        modelopt_branch to pick which branch of <owner>/Model-Optimizer to
        check out for the test code. `test_branch` (qa-scripts) stays at
        its default.
        """
        from urllib.parse import quote
        pattern = self.trigger_pattern
        branch = self.git_current_branch or "auto/add-cases"
        parts = [f"modelopt_branch={quote(branch)}"]
        if pattern:
            parts.append(f"pattern={quote(pattern)}")
        return "/trigger?" + "&".join(parts)
