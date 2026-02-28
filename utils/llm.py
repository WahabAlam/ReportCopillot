# utils/llm.py
import os
import hashlib
import re
import time
from openai import OpenAI


class LLMError(RuntimeError):
    pass


def get_client_and_model():
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        raise RuntimeError("Missing LLM_API_KEY in .env")

    client = OpenAI(api_key=api_key)
    return client, model

def _extract_headers_from_system(system: str) -> list[str]:
    """
    Extract only the actual required headers from the STRICT FORMAT block.
    Avoid picking up instructional lines like "Rules:" or "STRICT FORMAT ...:"
    """
    lines = [ln.strip() for ln in system.splitlines()]

    start_idx = None
    for i, ln in enumerate(lines):
        if ln.upper().startswith("STRICT FORMAT"):
            start_idx = i + 1
            break

    candidates: list[str] = []
    if start_idx is not None:
        for ln in lines[start_idx:]:
            if not ln:
                continue
            low = ln.lower()
            if low.startswith("rules:") or low.startswith("general rules:"):
                break
            candidates.append(ln)
    else:
        candidates = lines

    headers: list[str] = []
    for ln in candidates:
        # Only accept simple header lines like "Objective:" "Apparatus & Procedure:"
        if re.fullmatch(r"[A-Za-z0-9 &/\-]{2,40}:", ln):
            low = ln.lower()
            if "strict format" in low or low in ("rules:", "general rules:"):
                continue
            headers.append(ln)

    return headers

def _mock_response(system: str, user: str) -> str:
    """
    Deterministic mock output for fast testing without OpenAI calls.
    Controlled by env var MOCK_LLM=1
    """
    h = hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest()[:8]
    sys_low = system.lower()

    if "extract and summarize theory" in sys_low or "return format:" in sys_low:
        return (
            "Key Concepts:\n"
            f"- Mock concept ({h})\n\n"
            "Variables & Units:\n"
            "- V (volts), I (amps)\n\n"
            "Equations/Models:\n"
            "- V = I R\n\n"
            "Procedure Requirements:\n"
            "- Follow the manual steps provided.\n\n"
            "Assumptions (explicitly stated in manual):\n"
            "- None stated.\n\n"
            "Missing Info / Clarifications Needed:\n"
            "- Apparatus details\n"
        )

    if "suggest helpful figures/plots/diagrams" in sys_low:
        return (
            f"Figure 1: Time-series plot ({h})\n"
            "Shows change over time.\n\n"
            "Figure 2: Histogram\n"
            "Shows distribution.\n\n"
            "Figure 3: Box plot\n"
            "Shows spread and outliers.\n"
        )

    if "careful reviewer" in sys_low:
        return user.replace("REPORT TO REVIEW:", "REVISED REPORT:").strip() + f"\n\n(Reviewed {h})"

    # writer / default
    headers = _extract_headers_from_system(system)
    if not headers:
        headers = ["Introduction:", "Methods:", "Results:", "Conclusion:"]

    body: list[str] = []
    for hd in headers:
        body.append(hd)
        body.append(f"Mock content for {hd[:-1]} ({h}).")
        body.append("")

    return "\n".join(body).strip()

def chat(system: str, user: str) -> str:
    # Toggle mock mode for tests/dev
    if os.getenv("MOCK_LLM", "0") == "1":
        return _mock_response(system, user)

    client, model = get_client_and_model()
    timeout_s = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
    retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
    backoff_s = float(os.getenv("LLM_RETRY_BACKOFF_SECONDS", "1.0"))

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                timeout=timeout_s,
            )
            content = resp.choices[0].message.content
            if not content:
                raise LLMError("Empty model response")
            return content
        except Exception as e:
            last_error = e
            if attempt >= retries:
                break
            time.sleep(backoff_s * (2**attempt))

    raise LLMError(f"LLM request failed after {retries + 1} attempts: {type(last_error).__name__}: {last_error}")
