# Engineering Copilot

FastAPI service that converts notes/manuals/data/images into submission-ready PDFs using a template-constrained multi-agent pipeline.

## What It Solves

Given source material (manual text/PDF), optional tabular data, and optional lab images, the app generates a structured report with:

- consistent section formatting
- source-grounded writing (`[S#]` tags)
- optional reviewer feedback
- plots (when tabular data exists)
- editable post-run drafts and PDF rebuilds

## Key Capabilities

- Multi-agent generation:
  - `research_agent`: extracts structured theory/facts from source text
  - `data_agent`: analyzes tabular data
  - `writer_agent`: generates section-by-section report content
  - `reviewer_agent` (optional): feedback section
  - `diagram_agent` (optional): figure ideas
- Grounded generation with lexical retrieval over source chunks
- Quality gate with targeted rewrite pass
- Per-job artifacts and debug traces under `outputs/<job_id>/`
- UI + API support for job status, draft editing, section regeneration, rebuild, retry, cancel

## Templates And Input Rules

| Template | Tabular Data | Images | Review | Notes |
|---|---|---|---|---|
| `lab_report` | Optional (`data_csv` or `data_table_text`) | Allowed | Allowed | Must provide at least one evidence source: tabular data or images |
| `data_insights` | Required (`data_csv` or `data_table_text`) | Not allowed | Not allowed | Stakeholder-focused data summary |
| `study_guide` | Not allowed | Not allowed | Not allowed | Notes/manual-driven study output |

### Supported tabular inputs

- Upload via `data_csv`: `.csv`, `.tsv`, `.xlsx`, `.xls`, `.json`
- Paste via `data_table_text`: CSV/TSV/markdown table text

### Custom layout precedence

- `layout_preferences` can include an explicit section order/list.
- When a clear section list is detected, it overrides the template default `writer_format` for that run.
- This override is applied consistently for generation, quality-fix, and rebuild flows.

## High-Level Pipeline

1. `POST /run`
2. Input validation + upload persistence
3. Source chunking (`manual_text` -> `[S#]` chunks)
4. Agents run: research -> data -> writer -> optional reviewer/diagram
5. Quality gate evaluates output; targeted repair pass if needed
6. PDF built and saved to `outputs/<job_id>.pdf`
7. User can edit draft, regenerate sections, quality-fix, and rebuild

## Project Layout

- `main.py`: FastAPI entrypoint and endpoint wiring
- `orchestrator.py`: agent orchestration + repair flow
- `templates.py`: template catalog + runtime template resolution
- `agents/`: agent implementations
- `services/`: queueing, worker lifecycle, PDF rebuild/quality-fix services
- `routes/`: request handlers
- `utils/`: validation, retrieval, plotting, PDF rendering, state/jobs helpers
- `templates/`: Jinja UI pages (`/app`, `/job/{id}`)
- `tests/`: unit/integration tests
- `uploads/`: uploaded files
- `outputs/`: per-job artifacts

## Requirements

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/) recommended

## Setup

```bash
uv sync
```

Create `.env` in project root.

Real model mode:

```env
LLM_API_KEY=your_api_key
LLM_MODEL=gpt-4o-mini
```

Local/mock mode:

```env
MOCK_LLM=1
```

Optional runtime knobs:

```env
LLM_TIMEOUT_SECONDS=45
LLM_MAX_RETRIES=2
LLM_RETRY_BACKOFF_SECONDS=1.0
PDF_MAX_PAGES=0
ADMIN_API_KEY=
RUN_RATE_LIMIT_ENABLED=1
RUN_RATE_LIMIT_MAX_REQUESTS=20
RUN_RATE_LIMIT_WINDOW_SECONDS=60
USE_RQ_QUEUE=0
REDIS_URL=redis://localhost:6379/0
RQ_QUEUE_NAME=report_jobs
RQ_JOB_TIMEOUT_SECONDS=1800
RQ_RESULT_TTL_SECONDS=86400
RQ_FALLBACK_TO_BACKGROUND=1
MAX_IMAGE_UPLOADS=24
MAX_PLOT_POINTS=2000
```

`PDF_MAX_PAGES`:

- `0` or unset: extract all pages
- positive integer: cap extraction at that many pages

## Run

```bash
uv run uvicorn main:app --reload
```

Open:

- UI: `http://127.0.0.1:8000/app`
- API docs: `http://127.0.0.1:8000/docs`

## Optional Durable Queue (Redis + RQ)

1. Set:

```env
USE_RQ_QUEUE=1
REDIS_URL=redis://localhost:6379/0
RQ_QUEUE_NAME=report_jobs
```

2. Run API:

```bash
uv run uvicorn main:app --reload
```

3. Run worker:

```bash
uv run rq worker report_jobs
```

If enqueue fails and `RQ_FALLBACK_TO_BACKGROUND=1`, service falls back to FastAPI background tasks.

## API Overview

- `GET /`: health
- `GET /template-configs`: template/form runtime config for UI
- `GET /recent-jobs?limit=10`: dashboard jobs
- `POST /run`: submit generation job
- `GET /status/{job_id}`: status + quality summary + timings
- `GET /job/{job_id}`: job page
- `GET /download/{job_id}`: generated PDF
- `POST /cancel/{job_id}`: request cancellation
- `POST /retry/{job_id}`: retry failed/canceled job
- `GET /draft/{job_id}`: fetch editable draft
- `POST /draft/{job_id}`: save draft
- `POST /regenerate-section/{job_id}`: regenerate one section
- `POST /quality-fix/{job_id}`: run targeted quality-fix rewrite
- `POST /rebuild/{job_id}`: rebuild PDF from current artifacts
- `POST /cleanup?max_age_hours=168&dry_run=true`: cleanup old artifacts

### `/run` form fields

Core:

- `template`
- `manual_text` or `manual_pdf`
- `goal`
- `extra_instructions`
- `print_profile` (`standard|dense|presentation|print_safe`)

Data/evidence:

- `data_csv` (tabular file upload)
- `data_table_text` (pasted table text)
- `lab_images` (multiple files, template-dependent)
- `lab_image_titles[]`
- `lab_image_captions[]`
- `lab_image_sections[]`

Output guidance:

- `lab_format_description`
- `layout_preferences`

Metadata:

- `report_title`, `student_name`, `course`, `group`, `date`
- `include_review` (`0|1`, template-dependent)

## cURL Examples

### Study guide

```bash
curl -X POST http://127.0.0.1:8000/run \
  -F "template=study_guide" \
  -F "manual_text=Paste your notes here..." \
  -F "goal=Generate a concise study guide" \
  -F "extra_instructions=Use simple language" \
  -F "include_review=0"
```

### Lab report (images only + custom layout override)

```bash
curl -X POST http://127.0.0.1:8000/run \
  -F "template=lab_report" \
  -F "manual_text=Computer simulation context..." \
  -F "goal=Generate submission-ready report." \
  -F "lab_format_description=Computer-simulated lab with screenshot evidence." \
  -F $'layout_preferences=Section order:\n- Context Snapshot\n- Setup Notes\n- Findings\n- Limitations\n- Final Verdict' \
  -F "lab_images=@./setup.png;type=image/png" \
  -F "lab_images=@./result.png;type=image/png" \
  -F "include_review=0"
```

### Lab report (pasted table text, no file upload)

```bash
curl -X POST http://127.0.0.1:8000/run \
  -F "template=lab_report" \
  -F "manual_text=Experiment context..." \
  -F "goal=Generate a submission-ready lab report." \
  -F $'data_table_text=time,temp\n0,20\n1,22\n2,25\n' \
  -F "include_review=0"
```

### Data insights (TSV file)

```bash
curl -X POST http://127.0.0.1:8000/run \
  -F "template=data_insights" \
  -F "manual_text=Business KPI context..." \
  -F "goal=Summarize trends and recommendations" \
  -F "data_csv=@./kpi.tsv;type=text/tab-separated-values"
```

## Quality Model

Quality is enforced in layers:

1. Required section contract (`writer_format`)
2. Header/section parsing validation
3. Quality checks (`min_words`, required terms, global terms)
4. Citation checks (`min_source_tags_per_section`)
5. Targeted quality-fix rewrite for flagged sections
6. Final quality summary persisted in `debug.json` and exposed by `/status/{job_id}`

## Artifacts And Debugging

Each job writes:

- `outputs/<job_id>/state.json`
- `outputs/<job_id>/debug.json`
- `outputs/<job_id>/theory.txt`
- `outputs/<job_id>/report.txt`
- `outputs/<job_id>/review.txt`
- `outputs/<job_id>/figures.txt`
- `outputs/<job_id>.pdf`

Useful debug keys in `debug.json`:

- `agent_status.timings_ms`
- `quality`
- `report_sections`
- `section_sources`
- `request_payload`

## Testing

Run all tests:

```bash
uv run pytest -q
```

## Troubleshooting

- `Missing LLM_API_KEY in .env`:
  - Set `LLM_API_KEY`, or use `MOCK_LLM=1`.
- Job stays in `running`:
  - Check server logs.
  - Inspect `outputs/<job_id>/state.json` and `debug.json`.
- PDF not found:
  - Verify `/status/{job_id}` is `done`.
- Cleanup old artifacts:
  - Dry run: `POST /cleanup?dry_run=true&max_age_hours=168`
  - Execute: `POST /cleanup?dry_run=false&max_age_hours=168`

## Limitations

- PDF extraction is non-OCR (scanned/image-only PDFs may extract little text)
- File-backed state (no DB) limits multi-instance scalability
- Retrieval is lexical, not embedding-based
- Single quality-fix pass may still require manual edits
- `[S#]` tags are grounding hints, not formal citation metadata
- Output quality depends on source quality and model behavior

