# HF Test Dashboard

End-to-end Reflex app that automates the HuggingFace model QA workflow for **TensorRT-LLM**, **vLLM**, and **SGLang** backends. Replaces the manual loop of: spot new HF model → read model card → write pytest case → push branch → trigger Jenkins → grep `.out` log → update result spreadsheet.

Backed by SQLite (no Postgres setup) and Claude (via the NVIDIA Inference gateway) for AI-powered HF-card parsing and `.out` log analysis.

## Pages

| Page | Route | What it does |
|---|---|---|
| **Home** | `/` | Landing page + quick links. |
| **Inbox** | `/inbox` | Auto-polls HF for new NVIDIA models from `inference-optimized-checkpoints-with-model-optimizer` and Eagle3 models from `speculative-decoding-modules`. Claude reads each model card and classifies backend support (TRT-LLM / vLLM / SGLang) as `yes` / `unclear`. One-click "Generate case" inserts a pytest entry into `tests/examples/llm_ptq/test_deploy.py` on the unified `auto/add-cases` branch in the `noeyy-mino/Model-Optimizer` fork; multi-select lets you batch-trigger a Jenkins build for several models at once. |
| **Trigger Build** | `/trigger` | Full parameter form for the `sirui_test_hf` Jenkins job. Dropdowns for `modelopt_repo_owner`, `test_branch`, `modelopt_branch`, plus all the slurm / docker / pytest flags. Pre-flight check auto-pushes the local branch if it isn't on origin yet. |
| **Test Runs** | `/runs` | Every Jenkins build triggered from the dashboard, with live status badges (QUEUED / BUILDING / SUCCESS / FAILURE / ANALYZED). A background daemon polls Jenkins every 30s; when a build finishes it pulls the slurm `.out` log, hands it to the AI Analyzer, and writes per-model rows to the Test Matrix. |
| **Test Matrix** | `/matrix` | Model × backend grid filtered by `release_version` (modelopt version). Hover for analysis reasoning, per-row delete. |
| **AI Analyzer** | `/analyzer` | Paste a slurm `.out` path (or just a build ID); Claude classifies pass / fail / inconclusive per model with a cited log snippet. Streaming UI. Anchor-based preprocessing (`Deploying model:`) splits multi-MB logs so all 40+ models in a single build get judged individually. One-click save to the matrix. |
| **History** | `/history` | Past analyses grouped by `.out` file path. |

## Setup

```bash
cd /localhome/local-siruiw/hf_dashboard
python -m venv ~/.hf_dashboard_venv
source ~/.hf_dashboard_venv/bin/activate
pip install -r requirements.txt
```

Create `~/.hf_dashboard/env` with:

```
NVIDIA_API_KEY=sk-...               # NVIDIA Inference gateway (LiteLLM) key
JENKINS_URL=http://dlswqa-nas:18880
JENKINS_USER=<your-jenkins-user>
JENKINS_TOKEN=<your-jenkins-api-token>
HF_TOKEN=hf_...                     # optional, for private HF repos
```

Run (production mode behind an SSH tunnel — recommended):

```bash
bash start.sh    # binds 18083 (frontend) + 18084 (backend)
```

On your Mac, set up a tunnel and open `http://localhost:18083`:

```bash
ssh -N -L 18083:localhost:18083 -L 18084:localhost:18084 <user>@<dev-host>
```

DB lives at `~/.hf_dashboard/hf_dashboard.db` (local disk — CIFS doesn't support SQLite locking).

## Architecture

```
hf_dashboard/
├── hf_dashboard.py              # app entry, route registration, starts runs_watcher
├── components/navbar.py         # sidebar + page_shell wrapper
├── data/                        # one Reflex state class per page
│   ├── common.py
│   ├── home_state? (inline)
│   ├── inbox_state.py
│   ├── trigger_state.py
│   ├── runs_state.py
│   ├── matrix_state.py
│   ├── analyzer_state.py
│   └── history_state.py
├── page/                        # one render fn per route
│   ├── home.py
│   ├── inbox.py
│   ├── trigger.py
│   ├── runs.py
│   ├── matrix.py
│   ├── analyzer.py
│   └── history.py
└── services/
    ├── db.py                    # SQLite schema + migrations + helpers
    ├── hf_card.py               # HF model card → Claude → backend verdict
    ├── case_writer.py           # AST-aware insertion into test_deploy.py
    ├── working_copy.py          # thin façade over git_ops for the fork
    ├── git_ops.py               # clone / branch / commit (DCO) / push (SSH)
    ├── jenkins.py               # config (URL, creds)
    ├── jenkins_trigger.py       # POST buildWithParameters, queue→build resolve
    ├── runs_watcher.py          # background daemon: poll Jenkins, find .out, analyze
    └── log_analyzer.py          # Claude (via NVIDIA Inference) + anchor-based preprocessing
scripts/seed_data.py             # optional sample data loader
start.sh                         # PROD launcher (reflex run --env prod)
```

## End-to-end workflow

1. **Discover** — new NVIDIA model lands on HF → Inbox auto-detects on next poll and Claude classifies which backends the model card claims support for.
2. **Generate case** — click *Generate case* on an Inbox card; dashboard infers `tensor_parallel`, `mini_sm` (FP8→89, NVFP4→100), and family from the model name, then inserts a pytest entry into `tests/examples/llm_ptq/test_deploy.py` on `auto/add-cases` in the mentor's fork (DCO sign-off, SSH push).
3. **Trigger** — multi-select Inbox cards → *Trigger build for selected* opens the Trigger page with `modelopt_branch=auto/add-cases` and a pytest `-k` pattern pre-filled. Fill `modelopt_version` → Build.
4. **Watch** — Runs page shows live status; background watcher polls Jenkins every 30s.
5. **Analyze** — when a build finishes, the watcher finds the slurm `.out` under `~/myshare/workspace/slurm_logs/sirui_test_hf/<build>/`, asks Claude to classify every model in the log, and writes one row per (model, backend) to the matrix tagged with the build's `modelopt_version`.
6. **Triage** — Test Matrix shows the grid; filter by release, drill into per-cell reasoning, delete bad rows, file NVBugs for failures.

## Notes / gotchas

- The `auto/add-cases` branch is a single shared branch for **all** auto-generated cases (not per-model). The Jenkins `modelopt_branch` param routes Jenkins to check out this branch from the modelopt fork (not the qa-scripts repo — that one is `test_branch`).
- If Jenkins build fails with `.git/index.lock`, add a **Clean before checkout** SCM extension on the Jenkins job (Pipeline → SCM → Additional Behaviours).
- Claude calls go through NVIDIA's LiteLLM-backed Inference gateway (`https://inference-api.nvidia.com/v1`), model `aws/anthropic/claude-opus-4-5`. Bedrock's context window is 200K tokens — the log preprocessor caps payload at ~500KB to leave headroom.
- Run dashboard under `tmux` / `screen` so it survives SSH disconnects.
