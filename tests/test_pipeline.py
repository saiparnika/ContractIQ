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
    """Verifies memory retention counts are consistent in local mode."""
    from memory.hindsight_client import HindsightClient
    results = analyze_text(SAMPLE_TEXT, retain_in_memory=True, hindsight_client=HindsightClient(api_key=""))
    mem = results["memory_result"]

    assert mem["retained_verified_observations"] > 0
    assert mem["total_submitted_observations"] >= mem["retained_verified_observations"]
    assert mem["graph_edges_stored"] >= 2  # At least one edge per party
    assert mem["hindsight_cloud_configured"] is False  # No API key in test


def test_analyze_text_pipeline_with_mocked_cloud_sync():
    """Verifies pipeline correctly synchronizes verified observations to Hindsight Cloud."""
    from unittest.mock import patch, MagicMock
    from memory.hindsight_client import HindsightClient

    mock_response = MagicMock()
    mock_response.read.return_value = b'{"items": [{"id": "item-pipe-1"}]}'
    mock_response.__enter__.return_value = mock_response

    mock_client = HindsightClient(api_key="mock_key", api_url="https://api.hindsight.test/v1")
    with patch("urllib.request.urlopen", return_value=mock_response):
        results = analyze_text(SAMPLE_TEXT, retain_in_memory=True, hindsight_client=mock_client)

    mem = results["memory_result"]
    assert mem["hindsight_cloud_configured"] is True
    assert mem["hindsight_cloud_synced"] > 0
    assert mem["hindsight_cloud_sync_status"] == "synced"
    assert len(mem["hindsight_cloud_errors"]) == 0


def test_unverified_observations_excluded_from_authoritative_memory():
    """Regression test: unverified/ambiguous/contradicted observations must be excluded from memory."""
    from memory.memory_manager import MemoryManager
    from schemas.contract_schema import SourceEvidence
    from schemas.verification_schema import (
        FindingAudit,
        VerificationStatus,
        ContractVerificationReport,
    )
    from schemas.memory_schema import (
        HindsightAgreementRecord,
        HindsightObservation,
        HindsightIngestionPayload,
        HindsightRecallQuery,
    )

    manager = MemoryManager()

    valid_ev = SourceEvidence(
        verbatim_quote="Client shall pay all undisputed invoices within thirty (30) days.",
        page_number=1,
        section_reference="Section 2.1",
        start_char_offset=0,
        end_char_offset=65,
        confidence_score=0.95,
    )

    unverified_ev = SourceEvidence(
        verbatim_quote="[No grounded source evidence attached to this claim.]",
        page_number=1,
        section_reference=None,
        start_char_offset=0,
        end_char_offset=0,
        confidence_score=0.0,
    )

    agreement = HindsightAgreementRecord(
        memory_id="MEM-TEST-001",
        contract_id="CNT-TEST-001",
        document_hash="a" * 64,
        title="Test Agreement",
        contract_type="MSA",
        parties=["Party Alpha", "Party Beta"],
        evidence=valid_ev,
    )

    obs_verified = HindsightObservation(
        observation_id="OBS-COMM-001",
        contract_id="CNT-TEST-001",
        category="payment_terms",
        clause_reference="Section 2.1",
        quote=valid_ev.verbatim_quote,
        normalized_summary="Payment terms: Net 30",
        provenance=valid_ev,
    )

    obs_unverified = HindsightObservation(
        observation_id="OBS-LIAB-001",
        contract_id="CNT-TEST-001",
        category="limitation_of_liability",
        clause_reference=None,
        quote="Unverified liability claim",
        normalized_summary="Liability cap: Unverified",
        provenance=unverified_ev,
    )

    audit_verified = FindingAudit(
        finding_id="OBS-COMM-001",
        category="Commercial",
        original_claim="Payment terms: Net 30",
        submitted_evidence=valid_ev,
        status=VerificationStatus.VERIFIED,
        buffer_match_exact=True,
        normalized_token_match_score=1.0,
        surrounding_context_consistent=True,
    )

    audit_unsupported = FindingAudit(
        finding_id="OBS-LIAB-001",
        category="Liability",
        original_claim="Liability cap: Unverified",
        submitted_evidence=unverified_ev,
        status=VerificationStatus.UNSUPPORTED,
        buffer_match_exact=False,
        normalized_token_match_score=0.0,
        surrounding_context_consistent=False,
        discrepancy_explanation="Evidence not grounded in text",
    )

    report = ContractVerificationReport(
        contract_id="CNT-TEST-001",
        document_hash="a" * 64,
        total_findings_audited=2,
        verified_count=1,
        contradicted_count=0,
        unsupported_count=1,
        ambiguous_count=0,
        findings_audit=[audit_verified, audit_unsupported],
        human_review_required=True,
    )

    payload = HindsightIngestionPayload(
        contract_id="CNT-TEST-001",
        agreement_record=agreement,
        observations=[obs_verified, obs_unverified],
        graph_edges=[],
        verification_report=report,
        allow_unverified_draft=False,
    )

    # get_verified_observations() must filter out obs_unverified
    verified_obs = payload.get_verified_observations()
    assert len(verified_obs) == 1
    assert verified_obs[0].observation_id == "OBS-COMM-001"

    # Retain in memory manager
    res = manager.retain_contract(payload)
    assert res["total_submitted_observations"] == 2
    assert res["retained_verified_observations"] == 1
    assert res["rejected_unverified_observations"] == 1

    # Verified observation must be stored in memory
    assert "OBS-COMM-001" in manager._observations
    # Unverified observation must NOT be stored in memory
    assert "OBS-LIAB-001" not in manager._observations

    # Recall for unverified observation must return empty
    recall_res = manager.recall(HindsightRecallQuery(query_text="liability unverified"))
    assert not any(r.memory_id == "OBS-LIAB-001" for r in recall_res)

