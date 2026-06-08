"""Jenkins REST API integration.

Looks up a build by (job_name, build_number) and returns the parameters
that triggered it + the human-facing URL.

Configuration via env (set in ~/.hf_dashboard/env):

    JENKINS_BASE_URL    e.g. http://dlswqa-nas:18880
    JENKINS_JOB_NAME    e.g. sirui_test_hf       (the Jenkins job that produces
                                                  these slurm logs)
    JENKINS_USER        Jenkins username
    JENKINS_TOKEN       Jenkins API token
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx


@dataclass
class JenkinsBuild:
    url: str = ""                       # human URL to the build page
    job_url: str = ""                   # human URL to the job page
    job_name: str = ""
    build_number: str = ""
    display_name: str = ""              # e.g. "#191"
    result: str = ""                    # SUCCESS / FAILURE / null
    building: bool = False
    timestamp_ms: int = 0               # epoch millis from Jenkins
    duration_ms: int = 0
    description: str = ""
    triggered_by: str = ""              # user who triggered the build
    parameters: list[dict] = field(default_factory=list)  # [{"name": ..., "value": ...}, ...]


def base_url() -> str:
    return (os.environ.get("JENKINS_BASE_URL") or "").rstrip("/")


def default_job_name() -> str:
    return os.environ.get("JENKINS_JOB_NAME", "sirui_test_hf")


def is_configured() -> bool:
    """We can hit Jenkins iff base URL + creds are set."""
    return bool(
        os.environ.get("JENKINS_BASE_URL")
        and os.environ.get("JENKINS_USER")
        and os.environ.get("JENKINS_TOKEN")
    )


def build_url(job_name: str, build_number: str | int) -> str:
    """Human URL to a build page."""
    bu = base_url()
    if not bu:
        return ""
    return f"{bu}/job/{job_name}/{build_number}/"


def job_url(job_name: str) -> str:
    bu = base_url()
    if not bu:
        return ""
    return f"{bu}/job/{job_name}/"


def get_build_info(
    build_number: str | int,
    job_name: str | None = None,
    timeout: float = 10.0,
) -> tuple[JenkinsBuild | None, str | None]:
    """Fetch one build's metadata + parameters from Jenkins.

    Returns (JenkinsBuild, None) on success, or (None, error_message) on failure.
    """
    if not is_configured():
        return None, "Jenkins is not configured (set JENKINS_BASE_URL/USER/TOKEN)."

    job_name = (job_name or default_job_name()).strip()
    bnum = str(build_number).strip()
    if not bnum:
        return None, "Empty build number."

    url = f"{base_url()}/job/{job_name}/{bnum}/api/json"
    user = os.environ.get("JENKINS_USER") or ""
    token = os.environ.get("JENKINS_TOKEN") or ""

    try:
        resp = httpx.get(url, auth=(user, token), timeout=timeout)
    except httpx.RequestError as e:
        return None, f"Jenkins request failed: {type(e).__name__}: {e}"

    if resp.status_code == 404:
        return None, f"Build #{bnum} not found on Jenkins job '{job_name}'."
    if resp.status_code in (401, 403):
        return None, f"Jenkins auth failed (HTTP {resp.status_code}). Check JENKINS_USER / JENKINS_TOKEN."
    if resp.status_code >= 400:
        return None, f"Jenkins returned HTTP {resp.status_code}."

    try:
        data = resp.json()
    except ValueError:
        return None, "Jenkins response was not valid JSON."

    # Parameters live inside actions[*]._class == "hudson.model.ParametersAction"
    params: list[dict] = []
    triggered_by = ""
    for a in data.get("actions") or []:
        if not isinstance(a, dict):
            continue
        cls = a.get("_class") or ""
        if cls.endswith("ParametersAction") and a.get("parameters"):
            for p in a["parameters"]:
                name = str(p.get("name") or "")
                value = p.get("value")
                if value is None:
                    value = ""
                params.append({"name": name, "value": str(value)})
        if cls.endswith("CauseAction"):
            for c in a.get("causes") or []:
                if not isinstance(c, dict):
                    continue
                # UserIdCause.userName, or shortDescription as fallback
                triggered_by = (
                    c.get("userName")
                    or c.get("shortDescription")
                    or triggered_by
                )

    build = JenkinsBuild(
        url=build_url(job_name, bnum),
        job_url=job_url(job_name),
        job_name=job_name,
        build_number=bnum,
        display_name=str(data.get("displayName") or f"#{bnum}"),
        result=str(data.get("result") or ""),
        building=bool(data.get("building") or False),
        timestamp_ms=int(data.get("timestamp") or 0),
        duration_ms=int(data.get("duration") or 0),
        description=str(data.get("description") or ""),
        triggered_by=triggered_by,
        parameters=params,
    )
    return build, None
