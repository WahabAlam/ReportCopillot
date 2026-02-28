TEMPLATES = {
    "lab_report": {
        "display_name": "Lab / Technical Report",
        "pdf_title_default": "Technical Lab Report",
        "needs_csv": True,
        "include_plots": True,
        "include_review": True,   # ✅ default ON for labs
        "form_schema": {
            "allow_csv": True,
            "require_csv": True,
            "allow_review": True,
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
        },
    },

    "data_insights": {
        "display_name": "Data Insights Report",
        "pdf_title_default": "Data Insights Report",
        "needs_csv": True,
        "include_plots": True,
        "include_review": False,  # ✅ default OFF
        "form_schema": {
            "allow_csv": True,
            "require_csv": True,
            "allow_review": False,
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
        },
    },

    "study_guide": {
        "display_name": "Study Guide",
        "pdf_title_default": "Study Guide",
        "needs_csv": False,
        "include_plots": False,
        "include_review": False,  # ✅ default OFF
        "form_schema": {
            "allow_csv": False,
            "require_csv": False,
            "allow_review": False,
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
        },
    },
}

DEFAULT_TEMPLATE = "lab_report"


def get_template(template_key: str) -> dict:
    if template_key not in TEMPLATES:
        raise KeyError(f"Unknown template: {template_key}")
    return TEMPLATES[template_key]
