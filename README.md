# Engineering Copilot

A FastAPI app that turns source materials into submission-ready PDFs using a template-constrained, multi-agent pipeline.

It supports three output modes:
- `lab_report`
- `data_insights`
- `study_guide`

Inputs can include:
- manual text or a manual PDF
- optional/required CSV data (template dependent)
- optional multi-image uploads for templates that allow image evidence (e.g., lab reports)
- optional metadata (title, name, course, date, group)

## Why This Project Exists

The project is designed for a common gap in student and analyst workflows: users have source material and raw data, but need a structured final document that is:
- correctly formatted
- traceable to provided inputs
- easy to edit and regenerate
- exportable as a polished PDF

## Architecture At A Glance

1. Client submits `/run` with template + inputs.
2. API validates template rules and input constraints.
3. Orchestrator runs agent pipeline:
   `source-chunking -> research -> data -> section-by-section writer -> (optional reviewer/diagram) -> quality gate`.
4. If required sections are missing or quality rules fail, one auto-repair rewrite pass runs.
5. Artifacts are persisted under `outputs/<job_id>/` (`state.json`, `debug.json`, draft text files, PDF).
6. UI polls `/status/{job_id}` and exposes post-run editing (`/draft`, `/regenerate-section`, `/quality-fix`, `/rebuild`).

## Major Design Decisions

1. Template-first generation instead of free-form prompting.
Why: predictable structure, easier grading/review, easier automated validation.
Tradeoff: less stylistic freedom.

2. Multi-agent decomposition rather than one monolithic prompt.
Why: each stage has a narrow responsibility (extract, analyze, write, review/diagram), which improves observability and debugging.
Tradeoff: more orchestration code and inter-agent payload contracts.

3. Section-header contract as an enforcement mechanism.
Why: output must match required headers exactly for reliable downstream parsing and draft editing.
Tradeoff: model creativity is intentionally constrained.

4. Quality gate with a single repair pass.
Why: catches missing/short/required-term issues while capping latency/cost.
Tradeoff: one pass may not fix every edge case.

5. File-based job state and artifacts (no DB).
Why: simple local development, transparent debugging, easy artifact inspection.
Tradeoff: horizontal scalability and concurrency controls are limited compared to database-backed jobs.

6. Queue abstraction with optional Redis/RQ, default local background tasks.
Why: local setup remains easy, while production users can opt into durable queues.
Tradeoff: two execution modes to maintain.

7. Human-in-the-loop post-processing endpoints.
Why: users can edit the draft, regenerate specific sections, or run targeted quality fixes without re-running entire jobs.
Tradeoff: additional endpoint and UI complexity.

8. Conservative factuality policy.
Why: prompts and rules repeatedly prohibit invented facts/equipment/numbers unless present in source inputs.
Tradeoff: if source detail is sparse, output may include explicit assumptions or missing-info notes.

9. Manual PDF extraction defaults to all pages (`PDF_MAX_PAGES=0`).
Why: prevents silent truncation on large lecture decks/manuals.
Tradeoff: longer extraction/prompt payloads on very large PDFs.

10. Grounded section-by-section drafting with source tags (`[S#]`).
Why: significantly improves fidelity for long manuals/slides by retrieving relevant chunks per section.
Tradeoff: more prompt calls and slightly higher latency/cost.

## Features

- Multi-agent pipeline:
  - `research_agent`: extracts structured theory/notes
  - `data_agent`: summarizes CSV and computes auto-analysis metrics
  - `writer_agent`: produces section-by-section grounded report text in required section format
  - `reviewer_agent` (optional): generates reviewer feedback
  - `diagram_agent` (optional): suggests figures
- source chunking + retrieval for long inputs:
  - manual text is chunked into `[S#]` sources
  - writer retrieves top relevant chunks per section
  - section bodies include inline source tags for factual traceability
- quality gate: checks template-level content rules and runs one automatic quality-fix rewrite pass
- citation coverage checks in quality gate (`min_source_tags_per_section`)
- theme-driven PDF renderer with template-level `pdf_theme` tokens
- print-profile switch (`standard`, `dense`, `presentation`, `print_safe`) for output density and print styling
- improved PDF formatter: section-aware rendering + markdown-table conversion to native PDF tables
- section-targeted uploaded images are placed directly under matching report sections
- consistent figure numbering across uploaded images and auto-generated plots
- upgraded figure rendering: higher DPI, clearer axis labels/titles, and insight-style captions
- Plot generation for CSV workflows (time-series, histogram, box plot)
- Optional uploaded-image support (multiple images) with automatic PDF embedding
- Per-image metadata support: optional title, caption, and preferred section placement
- PDF generation with cover page, source summary, report, optional review, and figures
- optional source-traceability appendix in PDF mapping cited `[S#]` tags to source excerpts
- Job-based execution with status polling and downloadable output
- Background processing for `/run`

## Project Structure

- `main.py`: API routes, validation, background job execution
- `services/`: extracted service layer for submission queueing, PDF rebuild/quality-fix logic, and worker execution
- `orchestrator.py`: pipeline orchestration and section repair pass
- `templates.py`: template configs/rules
- `agents/`: LLM/data agents
- `utils/`: file handling, retrieval/chunking, plotting, PDF, state, LLM client
- `templates/`: Jinja pages (`/app`, `/job/{id}`)
- `tests/`: unit + integration tests
- `uploads/`: uploaded source files
- `outputs/`: generated artifacts and per-job debug state

## PDF Formatting Controls

Formatting is now driven by `pdf_theme` in each template config (`templates.py`).
Common tokens:
- `font_name`
- `heading_color`
- `caption_color`
- `table_header_bg`
- `table_grid`
- `table_alt_row_bg`

The renderer also applies:
- automatic list rendering (bulleted + numbered)
- table striping/grid consistency
- page-number footer
- section-anchored image placement when `target_section` or `suggested_sections` match template headers
- optional source appendix section ("Source Traceability") when source tags exist

Print profiles:
- `standard`: default balanced layout
- `dense`: tighter spacing and more rows/figures per page
- `presentation`: larger text and visuals
- `print_safe`: grayscale-friendly high-contrast table/color choices

## Job Artifacts And Debugging

Each run writes artifacts to `outputs/<job_id>/`:
- `state.json`: current lifecycle state (`queued/running/done/failed/canceled`), stage, progress
- `debug.json`: agent payload summaries, timing metrics, quality results, request metadata
- `theory.txt`, `report.txt`, `review.txt`, `figures.txt`: agent outputs
- `<job_id>.pdf` in `outputs/`: final compiled PDF

This design keeps every job inspectable and reproducible from local files.

## Requirements

- Python 3.13+
- `uv` (recommended)

## Setup

```bash
uv sync
```

Create `.env` in project root:

```bash
LLM_API_KEY=your_api_key
LLM_MODEL=gpt-4o-mini
```

Optional runtime knobs:

```bash
MOCK_LLM=1
LLM_TIMEOUT_SECONDS=45
LLM_MAX_RETRIES=2
LLM_RETRY_BACKOFF_SECONDS=1.0
PDF_MAX_PAGES=0
ADMIN_API_KEY=your_admin_key
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

`PDF_MAX_PAGES` behavior:
- `0` or unset: extract all pages from uploaded manual PDFs
- positive number: extract only that many pages

## Run

```bash
uv run uvicorn main:app --reload
```

Open:
- `http://127.0.0.1:8000/app` (UI)
- `http://127.0.0.1:8000/docs` (OpenAPI)

### Optional: Durable Queue (Redis + RQ)

1. Enable queue mode in `.env`:

```bash
USE_RQ_QUEUE=1
REDIS_URL=redis://localhost:6379/0
RQ_QUEUE_NAME=report_jobs
```

2. Run API:

```bash
uv run uvicorn main:app --reload
```

3. Run worker in another terminal:

```bash
uv run rq worker report_jobs
```

If RQ enqueue fails and `RQ_FALLBACK_TO_BACKGROUND=1`, the app falls back to local background tasks.

## API Overview

- `GET /`: health
- `GET /recent-jobs?limit=10`: list recent jobs for app dashboard
- `POST /run`: submit a job (returns `job_id`, `status_url`, `job_url`, `download_url`)
  - Supports `print_profile` form field: `standard` (default), `dense`, `presentation`, `print_safe`.
  - Supports `lab_images` multipart field (multiple files) for templates that allow images.
  - Supports optional repeated metadata fields aligned by upload order:
    - `lab_image_titles`
    - `lab_image_captions`
    - `lab_image_sections`
  - Metadata index `i` applies to uploaded image `i`.
- `GET /status/{job_id}`: job status (`queued`, `running`, `done`, `failed`, `canceled`)
- `GET /job/{job_id}`: job status page
- `GET /download/{job_id}`: final PDF
- `POST /cancel/{job_id}`: request cancellation for queued/running job
- `POST /retry/{job_id}`: requeue a failed/canceled job using persisted request payload
- `GET /draft/{job_id}`: fetch editable report draft + template headers
- `POST /draft/{job_id}`: save edited report draft text
- `POST /regenerate-section/{job_id}`: regenerate one section body via LLM and rebuild PDF
- `POST /rebuild/{job_id}`: rebuild PDF from current draft/report artifacts
- `POST /quality-fix/{job_id}`: run one targeted full-report quality-fix pass and rebuild PDF
- `POST /cleanup?max_age_hours=168&dry_run=true`: cleanup old `uploads/` + `outputs/` artifacts

Security:
- If `ADMIN_API_KEY` is set, `POST /cancel/{job_id}` and `POST /cleanup` require:
  - `X-Admin-Key: <ADMIN_API_KEY>`

Validation and limits:
- Template-specific constraints are enforced server-side:
  - `study_guide`: CSV upload not allowed
  - `data_insights`: reviewer feedback not allowed
  - `lab_report` and `data_insights`: CSV required
- `/run` has per-IP in-memory rate limiting controlled by:
  - `RUN_RATE_LIMIT_ENABLED`
  - `RUN_RATE_LIMIT_MAX_REQUESTS`
  - `RUN_RATE_LIMIT_WINDOW_SECONDS`

Queue mode:
- `/run` response and job state include:
  - `queue_mode`: `rq` or `background`
  - `queue_job_id`: RQ job ID when queued via Redis
- Retry flow:
  - `POST /retry/{job_id}` only supports `failed`/`canceled` source jobs
  - creates a new job id and queues it with current queue mode

Draft editing flow:
- Open `/job/{job_id}` after a job is `done`, `failed`, or `canceled`
- Use Draft Editor to:
  - save manual edits (`POST /draft/{job_id}`)
  - regenerate a single section (`POST /regenerate-section/{job_id}`)
  - apply one quality-fix rewrite pass (`POST /quality-fix/{job_id}`)
  - rebuild PDF from current draft (`POST /rebuild/{job_id}`)

## Quality Model

Quality is enforced in layers:
1. Template-level writer format (`writer_format`) enforces required sections.
2. Section parser checks for missing/empty required headers.
3. Quality gate validates minimum words and required terms per section/global terms.
4. Quality gate can enforce minimum source-tag citations per section (`min_source_tags_per_section`).
5. If checks fail, orchestrator runs one targeted quality-fix rewrite pass.
6. Final quality result is stored in `debug.json` and exposed via `/status/{job_id}`.

This keeps quality deterministic while still allowing user edits after generation.

## Example: Submit Job via cURL

```bash
curl -X POST http://127.0.0.1:8000/run \
  -F "template=study_guide" \
  -F "manual_text=Paste your notes here..." \
  -F "goal=Generate a concise study guide" \
  -F "extra_instructions=Use simple language" \
  -F "include_review=0"
```

Lab report example with CSV + images:

```bash
curl -X POST http://127.0.0.1:8000/run \
  -F "template=lab_report" \
  -F "manual_text=Experiment context..." \
  -F "goal=Generate a submission-ready lab report." \
  -F "data_csv=@./data.csv;type=text/csv" \
  -F "lab_images=@./setup.jpg;type=image/jpeg" \
  -F "lab_images=@./results.png;type=image/png" \
  -F "lab_image_titles=Apparatus setup" \
  -F "lab_image_titles=Final result sample" \
  -F "lab_image_captions=Shows thermocouple and beaker arrangement before heating." \
  -F "lab_image_captions=Shows final state after heating cycle." \
  -F "lab_image_sections=Apparatus & Procedure" \
  -F "lab_image_sections=Results" \
  -F "include_review=1"
```

## Testing

Run all tests:

```bash
uv run pytest -q
```

Tests cover:
- header repair retry behavior
- upload sanitization/validation
- source chunking and retrieval scoring behavior
- source-tag quality checks
- `/run` integration success path
- `/run` integration failure path (background job failure + error propagation)
- cancellation path in worker execution
- cleanup retention behavior

## Observability

- Structured JSON logs keyed by `job_id` from job worker lifecycle events
- Per-agent timing metrics in `outputs/<job_id>/debug.json` under `agent_status.timings_ms`
- `debug.json` includes grounded-generation metadata such as:
  - `section_sources` (which `[S#]` tags appeared in each section)
  - `source_chunk_count` (total chunks generated for the run)

## Troubleshooting

- `Missing LLM_API_KEY in .env`:
  - set `LLM_API_KEY`, or use `MOCK_LLM=1` for local testing.
- Job stuck in `running`:
  - check server logs for worker exceptions.
  - inspect `outputs/<job_id>/state.json` and `outputs/<job_id>/debug.json`.
- Clean old artifacts safely:
  - dry run first: `POST /cleanup?dry_run=true&max_age_hours=168`
  - delete after review: `POST /cleanup?dry_run=false&max_age_hours=168`
- PDF not found:
  - confirm job reached `done` at `/status/{job_id}`.

## Notes

- Current background processing uses FastAPI `BackgroundTasks` (single-process/local reliability).
- For production-grade job durability/retries, move to a real queue (Redis + RQ/Celery/Arq).

## Limitations

- Non-OCR PDF extraction: scanned/image-only PDFs may produce little/no text.
- No persistent database: state is file-backed, so multi-instance deployments need shared storage strategy.
- Single-pass quality repair: complex structural issues can still require manual draft edits.
- Retrieval is lexical (not embedding-based), so edge semantic matches may be missed.
- `[S#]` tags indicate grounding hints, not formal citations with page-level provenance.
- LLM output quality depends on source quality and model choice/configuration.

## Starting A New Chat Efficiently

Best practice for getting a new chat up to date is:
1. Commit current work.
2. Paste a short handoff prompt with branch, status, and exact target files.
3. Ask the new chat to read `README.md` first, then inspect listed files.

Suggested handoff command sequence:

```bash
git status --short
uv run pytest -q
git add -A
git commit -m "grounded retrieval + section citations + source appendix"
```

Suggested handoff prompt for a new chat:

```text
Please read README.md first, then continue from current branch state.

Current status:
- Grounded section-by-section writer with source chunks [S#] is implemented.
- Quality gate now checks min_source_tags_per_section.
- PDF can include Source Traceability appendix.
- Tests currently pass locally (49 passed).

Focus files:
- orchestrator.py
- agents/research_agent.py
- agents/writer_agent.py
- utils/retrieval.py
- utils/quality_gate.py
- utils/pdf_report.py
- services/job_worker.py
- services/job_pdf.py
- templates.py

Goal for this chat:
<paste your exact next task here>
```
