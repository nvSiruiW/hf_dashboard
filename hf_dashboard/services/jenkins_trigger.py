"""POST /buildWithParameters + status queries against the same Jenkins URL
that the read-only Jenkins integration (services/jenkins.py) already talks to.

This module owns the WRITE side: triggering a build, resolving the queue
entry to a build number, and polling for completion. The watcher uses it to
drive the auto-test pipeline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from hf_dashboard.services import jenkins as jenkins_read


# Re-export config helpers so callers don't have to know about two modules.
base_url = jenkins_read.base_url
default_job_name = jenkins_read.default_job_name
is_configured = jenkins_read.is_configured
build_url = jenkins_read.build_url
job_url = jenkins_read.job_url


@dataclass
class TriggerResult:
    ok: bool
    queue_id: int | None = None
    queue_url: str = ""
    error: str = ""


def _auth() -> tuple[str, str]:
    return (
        os.environ.get("JENKINS_USER") or "",
        os.environ.get("JENKINS_TOKEN") or "",
    )


def trigger_build(
    params: dict[str, str],
    job_name: str | None = None,
    timeout: float = 20.0,
) -> TriggerResult:
    """POST /job/<name>/buildWithParameters with the given params.

    Returns the Jenkins queue id (extracted from the Location response header).
    Resolving the queue id to a build number is a follow-up step — see
    `queue_to_build_number`.
    """
    if not is_configured():
        return TriggerResult(ok=False, error="Jenkins is not configured.")

    job_name = (job_name or default_job_name()).strip()
    url = f"{base_url()}/job/{job_name}/buildWithParameters"
    try:
        resp = httpx.post(
            url, data=params, auth=_auth(), timeout=timeout, follow_redirects=False,
        )
    except httpx.RequestError as e:
        return TriggerResult(ok=False, error=f"{type(e).__name__}: {e}")

    if resp.status_code in (401, 403):
        return TriggerResult(
            ok=False,
            error=f"Jenkins auth failed (HTTP {resp.status_code}). "
                  "Check JENKINS_USER / JENKINS_TOKEN.",
        )
    if resp.status_code not in (200, 201):
        body = (resp.text or "").strip()
        if len(body) > 400:
            body = body[:400] + "…"
        return TriggerResult(
            ok=False,
            error=f"Jenkins returned HTTP {resp.status_code}. {body}",
        )

    queue_url = (resp.headers.get("Location") or "").rstrip("/")
    queue_id = None
    if queue_url:
        # Location looks like http://jenkins/queue/item/123/
        tail = queue_url.rstrip("/").rsplit("/", 1)[-1]
        try:
            queue_id = int(tail)
        except ValueError:
            queue_id = None

    return TriggerResult(ok=True, queue_id=queue_id, queue_url=queue_url)


def queue_to_build_number(
    queue_id: int, timeout: float = 10.0
) -> tuple[int | None, str | None, str | None]:
    """Resolve a queue id to its build number once Jenkins has scheduled it.

    Returns (build_number, error, queue_state). queue_state is one of:
      - "pending"  → not yet picked up by an executor
      - "running"  → executable exists, return the build_number
      - "cancelled"
      - "blocked"  / "stuck" → check error
    """
    if not is_configured():
        return None, "Jenkins is not configured.", None

    url = f"{base_url()}/queue/item/{queue_id}/api/json"
    try:
        resp = httpx.get(url, auth=_auth(), timeout=timeout)
    except httpx.RequestError as e:
        return None, f"{type(e).__name__}: {e}", None

    if resp.status_code == 404:
        # Jenkins eventually evicts old queue entries (~5 min after start).
        return None, "Queue entry expired (Jenkins evicted it).", "expired"
    if resp.status_code >= 400:
        return None, f"HTTP {resp.status_code}", None

    try:
        data = resp.json() or {}
    except ValueError:
        return None, "Non-JSON response", None

    if data.get("cancelled"):
        return None, "Build was cancelled in the queue.", "cancelled"

    executable = data.get("executable") or {}
    if executable:
        bn = executable.get("number")
        if isinstance(bn, int):
            return bn, None, "running"

    return None, None, "pending"


def get_build_status(
    job_name: str, build_number: int, timeout: float = 10.0
) -> tuple[dict | None, str | None]:
    """Fetch a build's status JSON. Returns (data, error)."""
    if not is_configured():
        return None, "Jenkins is not configured."
    url = f"{base_url()}/job/{job_name}/{build_number}/api/json"
    try:
        resp = httpx.get(url, auth=_auth(), timeout=timeout)
    except httpx.RequestError as e:
        return None, f"{type(e).__name__}: {e}"
    if resp.status_code == 404:
        return None, f"Build #{build_number} not found yet."
    if resp.status_code >= 400:
        return None, f"HTTP {resp.status_code}"
    try:
        return resp.json(), None
    except ValueError:
        return None, "Non-JSON response"
