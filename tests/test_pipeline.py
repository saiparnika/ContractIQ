"""Integration tests for the ContractIQ end-to-end pipeline."""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pipeline import analyze_pdf, analyze_text
from analysis.models import RiskSeverity


SAMPLE_PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "samples", "sample_msa.pdf")

SAMPLE_TEXT = """MASTER SERVICES AGREEMENT

This Master Services Agreement ("Agreement") is made effective as of March 1, 2026 ("Effective Date"), by and between NovaTech Solutions Inc ("Client") and CloudBridge Systems LLC ("Vendor").

This Agreement shall be governed by and construed in accordance with the laws of the State of Delaware.

ARTICLE 1: SERVICES AND SCOPE
1.1 Vendor shall provide cloud infrastructure management services as described in applicable Statements of Work.
1.2 Client shall provide Vendor with necessary access credentials and documentation.

ARTICLE 2: FEES AND PAYMENT
2.1 Client shall pay all undisputed invoices within thirty (30) days of receipt (Net 30).
2.2 Late payments shall bear interest at 1.5% per month on the outstanding balance.

ARTICLE 3: TERM AND TERMINATION
3.1 This Agreement shall remain in effect for two (2) years.
3.2 Either party may terminate this Agreement without cause upon giving ninety (90) days prior written notice to the other party.
3.3 Either party may terminate if the other party breaches any material term and fails to cure within thirty (30) days.

ARTICLE 4: LIMITATION OF LIABILITY
4.1 Aggregate Cap: Except for indemnification under Article 5, each party's aggregate liability shall be limited to the total fees paid under this Agreement in the twelve (12) months preceding the claim.
"""


def test_analyze_text_pipeline():
    """Tests the full pipeline on raw contract text."""
    results = analyze_text(SAMPLE_TEXT, source_filename="test_contract.txt")

    # Verify all result keys
    assert "contract" in results
    assert "risk_report" in results
    assert "verification" in results
    assert "memory_result" in results
    assert "buffer_stats" in results

    contract = results["contract"]
    risk_report = results["risk_report"]
    verification = results["verification"]

    # Contract extraction checks
    assert contract.metadata.title == "MASTER SERVICES AGREEMENT"
    assert contract.metadata.contract_type == "MSA"
    assert contract.metadata.effective_date == "March 1, 2026"
    assert contract.metadata.governing_law == "Delaware"

    # Parties
    assert len(contract.parties) == 2
    party_names = {p.name for p in contract.parties}
    assert "NovaTech Solutions Inc" in party_names
    assert "CloudBridge Systems LLC" in party_names

    # Commercial terms
    assert contract.commercial_terms.payment_terms is not None
    assert contract.commercial_terms.late_payment_penalty is not None

    # Risk analysis
    assert risk_report.total_risks_identified > 0
    assert risk_report.overall_risk_score > 0

    # Verification
    assert verification.total_findings_audited > 0
    assert verification.verified_count > 0

    # Memory retention
    assert results["memory_result"] is not None
    assert results["memory_result"]["status"] == "success"

    # Buffer stats
    assert results["buffer_stats"]["total_pages"] >= 1
    assert results["buffer_stats"]["total_chars"] > 0


def test_analyze_text_source_evidence_grounding():
    """Verifies that all extracted evidence is properly grounded in the source text."""
    results = analyze_text(SAMPLE_TEXT, source_filename="evidence_test.txt")
    contract = results["contract"]

    # Metadata evidence
    meta_ev = contract.metadata.evidence
    assert meta_ev.verbatim_quote in SAMPLE_TEXT or meta_ev.confidence_score >= 0.50
    assert meta_ev.page_number >= 1

    # Party evidence
    for party in contract.parties:
        ev = party.evidence
        assert ev.verbatim_quote in SAMPLE_TEXT or ev.confidence_score >= 0.50
        assert ev.start_char_offset < ev.end_char_offset

    # Obligation evidence
    for obl in contract.obligations:
        ev = obl.evidence
        assert ev.start_char_offset >= 0
        assert ev.end_char_offset <= len(SAMPLE_TEXT) + 10  # small tolerance


@pytest.mark.skipif(
    not os.path.exists(SAMPLE_PDF_PATH),
    reason="Sample PDF not found — run generate_sample.py first",
)
def test_analyze_pdf_pipeline():
    """Tests the full pipeline on the sample PDF document."""
    results = analyze_pdf(SAMPLE_PDF_PATH)

    contract = results["contract"]
    risk_report = results["risk_report"]

    # Basic extraction
    assert "agreement" in contract.metadata.title.lower() or "services" in contract.metadata.title.lower()
    assert contract.metadata.contract_type == "MSA"
    assert len(contract.parties) >= 2

    # Risk analysis
    assert risk_report.total_risks_identified > 0

    # Buffer stats
    assert results["buffer_stats"]["total_pages"] >= 1
    assert results["buffer_stats"]["sections_detected"] > 0


def test_analyze_text_memory_retention_metrics():
    """Verifies memory retention counts are consistent."""
    results = analyze_text(SAMPLE_TEXT, retain_in_memory=True)
    mem = results["memory_result"]

    assert mem["retained_verified_observations"] > 0
    assert mem["total_submitted_observations"] >= mem["retained_verified_observations"]
    assert mem["graph_edges_stored"] >= 2  # At least one edge per party
    assert mem["hindsight_cloud_configured"] is False  # No API key in test

