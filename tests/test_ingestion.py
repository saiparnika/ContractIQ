"""Tests for ContractIQ Document Ingestion and Buffer Indexing."""

import pytest
from ingestion import (
    compute_sha256,
    DocumentBuffer,
    IndexedPage,
    ingest_text_buffer,
    detect_sections,
)

SAMPLE_CONTRACT = """MASTER SERVICES AGREEMENT

This Master Services Agreement ("Agreement") is made effective as of January 15, 2025 ("Effective Date"), by and between Acme Corp ("Client") and TechSolutions LLC ("Vendor").

ARTICLE 1: DEFINITIONS
1.1 Services means the IT consulting and software development services described in an applicable Statement of Work.

ARTICLE 2: FEES AND PAYMENT
2.1 Payment Terms: Client shall pay all undisputed invoices within thirty (30) days of receipt (Net 30).
2.2 Late Payments: Invoices not paid when due shall bear interest at 1.5% per month.

ARTICLE 3: TERM AND TERMINATION
3.1 Term: This Agreement shall commence on the Effective Date and remain in effect for three (3) years.
3.2 Termination for Convenience: Either party may terminate this Agreement without cause upon giving ninety (90) days prior written notice to the other party.
3.3 Termination for Cause: Either party may terminate immediately if the other party breaches any material term and fails to cure within thirty (30) days.

ARTICLE 4: LIMITATION OF LIABILITY
4.1 Aggregate Cap: Except for breach of confidentiality under Article 5 or indemnification under Article 6, each party's aggregate liability shall be limited to the total fees paid under this Agreement in the twelve (12) months preceding the incident.
"""


def test_sha256_canonical_hash():
    hash1 = compute_sha256(SAMPLE_CONTRACT)
    hash2 = compute_sha256(SAMPLE_CONTRACT.encode("utf-8"))
    assert hash1 == hash2
    assert len(hash1) == 64
    assert hash1.islower()


def test_ingest_text_buffer_and_slicing():
    doc = ingest_text_buffer(SAMPLE_CONTRACT, source_filename="sample_msa.txt")
    assert doc.total_chars == len(SAMPLE_CONTRACT)
    assert doc.total_pages == 1

    # Exact verbatim search
    quote = "Either party may terminate this Agreement without cause upon giving ninety (90) days prior written notice"
    span = doc.find_verbatim_quote(quote)
    assert span is not None
    start, end = span

    # Test deterministic slice assertion
    sliced = doc.slice(start, end)
    assert sliced == quote


def test_section_detection():
    doc = ingest_text_buffer(SAMPLE_CONTRACT, source_filename="sample_msa.txt")
    section_ids = [s.section_id for s in doc.sections]
    assert "Section 1" in section_ids or "Section I" in section_ids or any("1" in s for s in section_ids)
    assert any("4" in s for s in section_ids)

    # Check section resolution for offset
    quote = "aggregate liability shall be limited to the total fees paid"
    span = doc.find_verbatim_quote(quote)
    assert span is not None
    sec = doc.get_section_for_offset(span[0])
    assert sec is not None
    assert "4" in sec.section_id or "LIMITATION" in sec.title.upper()


def test_normalized_quote_search():
    doc = ingest_text_buffer(SAMPLE_CONTRACT, source_filename="sample_msa.txt")
    # Quote with irregular whitespace and newline inserted
    messy_quote = "Either   party may\nterminate this   Agreement without cause"
    res = doc.find_normalized_quote(messy_quote)
    assert res is not None
    start, end, score = res
    assert score >= 0.95
    assert "terminate this Agreement without cause" in doc.slice(start, end)


def test_context_window_extraction():
    doc = ingest_text_buffer(SAMPLE_CONTRACT, source_filename="sample_msa.txt")
    quote = "aggregate liability shall be limited to the total fees paid"
    start, end = doc.find_verbatim_quote(quote)
    ctx = doc.get_context_window(start, end, window_chars=150)

    assert "Except for breach of confidentiality" in ctx["pre_context"]
    assert ctx["quote"] == quote
    assert "twelve (12) months" in ctx["post_context"]


def test_slice_out_of_bounds_raises_error():
    doc = ingest_text_buffer(SAMPLE_CONTRACT)
    with pytest.raises(ValueError):
        doc.slice(-1, 50)
    with pytest.raises(ValueError):
        doc.slice(100, doc.total_chars + 1)
    with pytest.raises(ValueError):
        doc.slice(50, 40)
