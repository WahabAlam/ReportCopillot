from pypdf import PdfReader

def pdf_to_text(pdf_path: str, max_pages: int | None = None) -> str:
    reader = PdfReader(pdf_path)
    texts = []

    n_pages = len(reader.pages)
    limit = n_pages if max_pages is None else min(n_pages, max_pages)

    for i in range(limit):
        page = reader.pages[i]
        page_text = page.extract_text() or ""
        # keep spacing reasonable
        texts.append(page_text.strip())

    return "\n\n".join([t for t in texts if t])