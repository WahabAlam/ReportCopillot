from pypdf import PdfReader

def pdf_to_text(pdf_path: str, max_pages: int | None = None) -> str:
    reader = PdfReader(pdf_path)
    parts = []
    pages = reader.pages if not max_pages or max_pages < 1 else reader.pages[:max_pages]
    for p in pages:
        t = (p.extract_text() or "").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts).strip()
