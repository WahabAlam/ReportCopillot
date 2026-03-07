"""Template catalog defining report structure, rules, and UI metadata."""

from __future__ import annotations

from copy import deepcopy

TEMPLATES = {
    "lab_report": {
        "display_name": "Lab / Technical Report",
        "pdf_title_default": "Technical Lab Report",
        "needs_csv": False,
        "include_plots": True,
        "include_source_appendix": True,
        "include_review": True,   # ✅ default ON for labs
        "pdf_theme": {
            "font_name": "Helvetica",
            "heading_color": "#0f172a",
            "caption_color": "#334155",
            "table_header_bg": "#eaf2ff",
            "table_grid": "#94a3b8",
            "table_alt_row_bg": "#f8fafc",
        },
        "form_schema": {
            "allow_csv": True,
            "require_csv": False,
            "allow_review": True,
            "allow_images": True,
            "require_any_of": ["csv", "images"],
            "goal_min_len": 0,
            "goal_placeholder": "e.g., Generate a submission-ready report.",
            "manual_placeholder": "Paste manual / notes here...",
            "extra_placeholder": "Tone, formatting rules, etc.",
        },
        "writer_format": [
            "Objective",
            "Introduction",
            "Theoretical Background",
            "Apparatus & Procedure",
            "Results",
            "Discussion",
            "Conclusion",
            "References",
        ],
        "writer_rules": [
            "Start the Introduction with: 'This lab is intended to...'",
            "Use the CSV as the source of truth for numbers.",
            "Clearly label full-dataset vs preview table.",
            "Include an explicit heating-rate style calculation if slope info is available (Δy/Δx).",
            "Do not invent equipment models/settings not provided.",
            "If uploaded lab images are provided, reference them where relevant using labels like [Image 1].",
            "If image titles/captions are provided, use them as primary context for image mentions.",
        ],
        "reviewer_focus": [
            "Reproducibility (clear method + intervals)",
            "Calculations shown for key values",
            "Correct use of full dataset vs preview subset",
            "Clear limitations / sources of error",
        ],
        "quality": {
            "min_words": {
                "Results": 80,
                "Discussion": 100,
                "Conclusion": 50,
            },
            "required_terms_by_section": {
                "Results": ["mean", "min", "max"],
                "Discussion": ["assumption", "limitation", "error"],
            },
            "required_global_terms": ["dataset"],
            "min_source_tags_per_section": {
                "Objective": 1,
                "Introduction": 1,
                "Theoretical Background": 1,
                "Apparatus & Procedure": 1,
                "Results": 2,
                "Discussion": 2,
                "Conclusion": 1,
            },
        },
        "no_csv_overrides": {
            "writer_rules": [
                "Start the Introduction with: 'This lab is intended to...'",
                "Ground Results/Discussion in provided manual context and uploaded image evidence.",
                "Do not invent measurements or summary statistics when numeric data is unavailable.",
                "Clearly mark assumptions and missing quantitative details.",
                "Do not invent equipment models/settings not provided.",
                "If uploaded lab images are provided, reference them where relevant using labels like [Image 1].",
                "If image titles/captions are provided, use them as primary context for image mentions.",
            ],
            "quality": {
                "min_words": {
                    "Results": 80,
                    "Discussion": 100,
                    "Conclusion": 50,
                },
                "required_terms_by_section": {
                    "Discussion": ["assumption", "limitation", "error"],
                },
                "required_global_terms": [],
                "min_source_tags_per_section": {
                    "Objective": 1,
                    "Introduction": 1,
                    "Theoretical Background": 1,
                    "Apparatus & Procedure": 1,
                    "Results": 2,
                    "Discussion": 2,
                    "Conclusion": 1,
                },
            },
        },
    },

    "data_insights": {
        "display_name": "Data Insights Report",
        "pdf_title_default": "Data Insights Report",
        "needs_csv": True,
        "include_plots": True,
        "include_source_appendix": True,
        "include_review": False,  # ✅ default OFF
        "pdf_theme": {
            "font_name": "Helvetica",
            "heading_color": "#0b3a5e",
            "caption_color": "#334155",
            "table_header_bg": "#e9f6f5",
            "table_grid": "#8ca3b7",
            "table_alt_row_bg": "#f8fcff",
        },
        "form_schema": {
            "allow_csv": True,
            "require_csv": True,
            "allow_review": False,
            "allow_images": False,
            "goal_min_len": 10,
            "goal_placeholder": "e.g., Summarize trends and recommendations for stakeholders.",
            "manual_placeholder": "Paste business context, KPI definitions, and reporting goals...",
            "extra_placeholder": "Audience, tone, decision focus, limitations to mention, etc.",
        },
        "writer_format": [
            "Objective",
            "Dataset Overview",
            "Key Insights",
            "Visualizations",
            "Recommendations",
            "Risks & Limitations",
            "Next Steps",
        ],
        "writer_rules": [
            "Write for a non-technical stakeholder.",
            "Summarize numeric columns and key trends clearly.",
            "Every recommendation must tie to an observed pattern in the CSV.",
            "Avoid lab-specific wording.",
        ],
        "reviewer_focus": [
            "Clarity for non-technical reader",
            "Recommendations grounded in data",
            "No hallucinated facts",
        ],
        "quality": {
            "min_words": {
                "Key Insights": 80,
                "Recommendations": 60,
            },
            "required_terms_by_section": {
                "Recommendations": ["recommend", "because", "data"],
                "Risks & Limitations": ["risk", "limitation"],
            },
            "required_global_terms": ["trend"],
            "min_source_tags_per_section": {
                "Objective": 1,
                "Dataset Overview": 1,
                "Key Insights": 2,
                "Visualizations": 1,
                "Recommendations": 1,
                "Risks & Limitations": 1,
                "Next Steps": 1,
            },
        },
    },

    "study_guide": {
        "display_name": "Study Guide",
        "pdf_title_default": "Study Guide",
        "needs_csv": False,
        "include_plots": False,
        "include_source_appendix": True,
        "include_review": False,  # ✅ default OFF
        "pdf_theme": {
            "font_name": "Helvetica",
            "heading_color": "#1f2937",
            "caption_color": "#475569",
            "table_header_bg": "#f3f4f6",
            "table_grid": "#9ca3af",
            "table_alt_row_bg": "#fafafa",
        },
        "form_schema": {
            "allow_csv": False,
            "require_csv": False,
            "allow_review": False,
            "allow_images": False,
            "goal_min_len": 0,
            "goal_placeholder": "e.g., Build an exam-focused study guide from the notes.",
            "manual_placeholder": "Paste lecture notes, textbook snippets, or review points...",
            "extra_placeholder": "Difficulty, focus chapters, question style, etc.",
        },
        "writer_format": [
            "Overview",
            "Key Concepts",
            "Definitions",
            "Common Mistakes",
            "Practice Questions",
            "Answer Key (brief)",
        ],
        "writer_rules": [
            "Use only the provided manual_text/notes.",
            "Do not require a dataset.",
            "Keep it exam-prep focused with thorough topic coverage and concrete detail.",
            "Do not over-compress; include enough depth for university-level review.",
            "Practice Questions should include at least 12 mixed-difficulty questions when source material is broad.",
        ],
        "reviewer_focus": [
            "Covers main ideas",
            "Questions match content",
            "No made-up topics",
        ],
        "quality": {
            "min_words": {
                "Overview": 120,
                "Key Concepts": 300,
                "Definitions": 180,
                "Common Mistakes": 120,
                "Practice Questions": 220,
                "Answer Key (brief)": 180,
            },
            "required_terms_by_section": {
                "Practice Questions": ["?"],
                "Answer Key (brief)": ["answer"],
            },
            "required_global_terms": [],
            "min_source_tags_per_section": {
                "Overview": 1,
                "Key Concepts": 2,
                "Definitions": 1,
                "Common Mistakes": 1,
                "Practice Questions": 1,
                "Answer Key (brief)": 1,
            },
        },
    },
}

DEFAULT_TEMPLATE = "lab_report"


def get_template(template_key: str) -> dict:
    if template_key not in TEMPLATES:
        raise KeyError(f"Unknown template: {template_key}")
    return TEMPLATES[template_key]


def resolve_template_cfg(template_cfg: dict, *, has_csv: bool) -> dict:
    cfg = deepcopy(template_cfg or {})
    if has_csv:
        return cfg
    overrides = cfg.get("no_csv_overrides") or {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            cfg[key] = deepcopy(value)
    return cfg


def apply_layout_section_headers(template_cfg: dict, layout_section_headers: list[str] | None) -> dict:
    cfg = deepcopy(template_cfg or {})
    raw_headers = layout_section_headers or []
    headers: list[str] = []
    seen: set[str] = set()
    for raw in raw_headers:
        h = str(raw or "").strip().strip(":")
        if not h:
            continue
        key = h.lower()
        if key in seen:
            continue
        seen.add(key)
        headers.append(h)

    if headers:
        cfg["writer_format"] = headers
    return cfg
