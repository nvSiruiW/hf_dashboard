# HF Test Dashboard

A Reflex dashboard for tracking HuggingFace model deployment tests across **TensorRT-LLM**, **vLLM**, and **SGLang**. Modeled after `modelopt-dashboard` but with **SQLite** (no PostgreSQL setup needed) and **Claude API** integration for AI-powered `.out` log analysis.

## What it does

Two pages, both wired to a single SQLite table:

1. **AI Analyzer** — paste a slurm `.out` path; Claude reads the log tail and classifies pass / fail / inconclusive, citing the log signal it used. One-click save to the matrix.
2. **Test Matrix** — model × backend grid showing latest test status with hover-for-reason tooltips and NVBug badges.

## Setup

```bash
cd /localhome/local-siruiw/myshare/workspace/hf_dashboard
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...   # required for the AI Analyzer

# Seed sample rows so the matrix has something to show
python scripts/seed_data.py

# Run (dev mode — auto-reloads on file change)
reflex run
# or production:
bash start.sh    # http://localhost:18183
```

## File layout

```
hf_dashboard/
├── hf_dashboard.py           # app entry, route registration
├── components/navbar.py      # sidebar + page_shell wrapper
├── data/
│   ├── common.py             # BACKENDS, STATUS_ICONS, color scheme
│   ├── matrix_state.py       # Test Matrix state
│   └── analyzer_state.py     # AI Analyzer state
├── page/
│   ├── home.py               # landing page
│   ├── matrix.py             # model × backend status grid
│   └── analyzer.py           # AI .out log analyzer
└── services/
    ├── db.py                 # SQLite schema + upsert/query helpers
    └── log_analyzer.py       # Claude API integration (claude-opus-4-7 + structured outputs)
scripts/seed_data.py          # sample data loader
```

DB lives at `./hf_dashboard.db` by default. Override with `HF_DASHBOARD_DB=/path/to/file.db`.

## Workflow this supports today

1. Slack alert fires for a new HF model release (existing `modelopt_qa_tools` script).
2. You add the test case to your deploy harness and trigger the Jenkins job.
3. Test finishes; `.out` lands in `/localhome/local-siruiw/data/workspace/slurm_logs/sirui_test_hf/<run>/`.
4. Open **AI Analyzer**, paste the path, click *Run AI analysis* → Claude returns a verdict + reason.
5. Click *Save to DB* → row appears in the Test Matrix; file an NVBug if failed.

## Borrowed from `modelopt-dashboard`

- Reflex 0.8.18 + same status icon system (passed/failed/running/pending/broken/unsupported)
- Sidebar navigation pattern with active-state highlighting
- Color scheme: TRTLLM `#667eea`, vLLM `#F97316`, SGLang `#10B981`
- NVIDIA green accent (`#76B900`) for active nav

## Next steps (not in this MVP)

- Auto-trigger analyzer when a Jenkins job posts a webhook
- HuggingFace model card scraping to auto-fill backend support
- NVBugs API integration (status fetch, like `modelopt-dashboard/data/allshare/nvbugs.py`)
- Google Sheets sync (replace manual filling of the release tracking doc)
- Jenkins job trigger UI (copy from `modelopt-dashboard/page/alljenkins/`)
