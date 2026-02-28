from __future__ import annotations

import re
from typing import List


def find_missing_headers(report_text: str, required_headers: List[str]) -> List[str]:
    """
    Returns headers from required_headers that are not found in the report_text.

    We consider a header "present" if there's a line like:
      Header:
    (case-insensitive, allows extra spaces)

    Example: "Objective:" or "Objective:   "
    """
    text = report_text or ""
    missing: List[str] = []

    for h in required_headers:
        # Match header at start of a line, allow spaces, require colon
        # Example: ^Objective\s*:\s*$
        pattern = rf"(?im)^\s*{re.escape(h)}\s*:\s*$"
        if re.search(pattern, text) is None:
            missing.append(h)

    return missing