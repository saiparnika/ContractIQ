"""ContractIQ Ingestion Parser.

Extracts text buffers from contract documents (PDF, plain text, markdown),
computing page offsets, section hierarchies, and canonical SHA-256 hashes.
"""

import os
import re
from typing import List, Optional
import uuid

from .hasher import compute_sha256
from .models import DocumentBuffer, IndexedPage, IndexedSection

# Regular expressions for detecting standard legal section headers
SECTION_PATTERNS = [
    # Article I / ARTICLE 1: Title
    (re.compile(r"^(?:ARTICLE|Article)\s+([IVXLCDM\d]+)[:\.\s\-]+([^\n\r]+)", re.MULTILINE), 1),
    # Section 1.2 / SECTION 1.2(a): Title
    (re.compile(r"^(?:SECTION|Section)\s+(\d+(?:\.\d+)*(?:\([a-z\d]+\))*)[:\.\s\-]+([^\n\r]+)", re.MULTILINE), 2),
    # 1.1 Heading or 1. Heading
    (re.compile(r"^(\d+\.\d+(?:\.\d+)*)\s+([A-Z][^\n\r]+)", re.MULTILINE), 2),
]


def detect_sections(text: str) -> List[IndexedSection]:
    """Detects legal section boundaries and computes exact character offsets."""
    found_sections: List[IndexedSection] = []

    for pattern, level in SECTION_PATTERNS:
        for match in pattern.finditer(text):
            sec_num = match.group(1).strip()
            sec_title = match.group(2).strip()
            start_offset = match.start()
            found_sections.append(
                IndexedSection(
                    section_id=f"Section {sec_num}" if not sec_num.lower().startswith("section") else sec_num,
                    title=sec_title,
                    start_char_offset=start_offset,
                    end_char_offset=len(text),  # Initial end; adjusted below
                    level=level,
                )
            )

    # Sort by start offset
    found_sections.sort(key=lambda s: s.start_char_offset)

    # Refine end offsets based on next section start
    for i in range(len(found_sections) - 1):
        found_sections[i].end_char_offset = found_sections[i + 1].start_char_offset

    return found_sections


def ingest_text_buffer(
    text: str,
    source_filename: str = "document.txt",
    document_id: Optional[str] = None,
    page_break_delimiter: Optional[str] = "\f",  # Form feed is standard page break
) -> DocumentBuffer:
    """Ingests a text string into a canonical DocumentBuffer with page and section offsets."""
    doc_id = document_id or str(uuid.uuid4())
    doc_hash = compute_sha256(text)

    # Handle page breaks
    pages: List[IndexedPage] = []
    if page_break_delimiter and page_break_delimiter in text:
        page_chunks = text.split(page_break_delimiter)
        current_offset = 0
        for idx, chunk in enumerate(page_chunks):
            chunk_len = len(chunk)
            start = current_offset
            end = start + chunk_len
            pages.append(
                IndexedPage(
                    page_number=idx + 1,
                    start_char_offset=start,
                    end_char_offset=end,
                    page_text_length=chunk_len,
                )
            )
            # Add delimiter length if not the last page
            current_offset = end + len(page_break_delimiter)
    else:
        # Single page document
        pages.append(
            IndexedPage(
                page_number=1,
                start_char_offset=0,
                end_char_offset=len(text),
                page_text_length=len(text),
            )
        )

    sections = detect_sections(text)

    return DocumentBuffer(
        document_id=doc_id,
        document_hash=doc_hash,
        source_filename=source_filename,
        raw_text=text,
        total_chars=len(text),
        total_pages=len(pages),
        pages=pages,
        sections=sections,
    )


def ingest_pdf_file(
    pdf_path: str,
    document_id: Optional[str] = None,
) -> DocumentBuffer:
    """Ingests a PDF document using pdfplumber, extracting text while tracking exact page offsets and dimensions."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    doc_id = document_id or str(uuid.uuid4())
    doc_hash = compute_sha256(file_bytes)
    filename = os.path.basename(pdf_path)

    import pdfplumber

    raw_text_parts: List[str] = []
    pages: List[IndexedPage] = []
    current_offset = 0

    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            # Ensure newline separation between pages for continuity
            if idx > 0:
                raw_text_parts.append("\n\n")
                current_offset += 2

            start = current_offset
            raw_text_parts.append(page_text)
            current_offset += len(page_text)
            end = current_offset

            dims = {"width": float(page.width), "height": float(page.height)} if page.width and page.height else None
            pages.append(
                IndexedPage(
                    page_number=idx + 1,
                    start_char_offset=start,
                    end_char_offset=end,
                    page_text_length=len(page_text),
                    dimensions=dims,
                )
            )

    full_text = "".join(raw_text_parts)
    sections = detect_sections(full_text)

    return DocumentBuffer(
        document_id=doc_id,
        document_hash=doc_hash,
        source_filename=filename,
        raw_text=full_text,
        total_chars=len(full_text),
        total_pages=len(pages) if pages else 1,
        pages=pages,
        sections=sections,
    )
