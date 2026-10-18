"""Test helpers for generating synthetic PDFs."""

import io
from pathlib import Path


def generate_pdf_bytes(pages_text: list[str]) -> bytes:
    """Generate minimal valid PDF binary with text content on each page."""
    objects: list[bytes] = []

    def add_obj(content: bytes) -> int:
        objects.append(content)
        return len(objects)

    # Obj 1: Catalog
    add_obj(b"<< /Type /Catalog /Pages 2 0 R >>")
    # Obj 2: Placeholder for Pages
    objects.append(b"")

    # Obj 3: Standard Helvetica Font
    font_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    content_ids: list[int] = []
    for text in pages_text:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 712 Td ({escaped}) Tj ET".encode("latin-1")
        cid = add_obj(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        content_ids.append(cid)

    # Page objects
    page_ids: list[int] = []
    for cid in content_ids:
        pid = add_obj(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {cid} 0 R >>".encode("latin-1")
        )
        page_ids.append(pid)

    # Update Obj 2 with Kids
    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >>".encode("latin-1")

    # Build PDF
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    xref = [0]
    for i, obj in enumerate(objects):
        xref.append(out.tell())
        out.write(f"{i+1} 0 obj\n".encode("latin-1"))
        out.write(obj)
        out.write(b"\nendobj\n")

    xref_offset = out.tell()
    out.write(b"xref\n")
    out.write(f"0 {len(objects)+1}\n".encode("latin-1"))
    out.write(b"0000000000 65535 f \n")
    for pos in xref[1:]:
        out.write(f"{pos:010d} 00000 n \n".encode("latin-1"))

    out.write(b"trailer\n")
    out.write(f"<< /Size {len(objects)+1} /Root 1 0 R >>\n".encode("latin-1"))
    out.write(b"startxref\n")
    out.write(f"{xref_offset}\n%%EOF\n".encode("latin-1"))
    return out.getvalue()


def write_test_pdf(file_path: Path | str, pages_text: list[str]) -> Path:
    """Write synthetic PDF to disk."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = generate_pdf_bytes(pages_text)
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    return path
