"""Tests for ContractIQ Analysis, Extraction, and Risk Engine."""

import pytest
from ingestion import ingest_text_buffer
from analysis import (
    extract_contract,
    analyze_contract_risks,
    RiskSeverity,
    RiskCategory,
)

SAMPLE_MSA = """MASTER SERVICES AGREEMENT

This Master Services Agreement ("Agreement") is made effective as of January 15, 2025 ("Effective Date"), by and between Acme Corp ("Client") and TechSolutions LLC ("Vendor").

This Agreement shall be governed by and construed in accordance with the laws of Delaware.

ARTICLE 1: SERVICES AND OBLIGATIONS
1.1 TechSolutions LLC shall deliver IT consulting services in accordance with applicable Statements of Work.
1.2 Acme Corp shall provide necessary access and project information to Vendor.

ARTICLE 2: FEES AND PAYMENT
2.1 Invoices shall be paid within thirty (30) days of receipt (Net 30).
2.2 Late payments shall incur interest at 1.5% per month.

ARTICLE 3: TERM AND TERMINATION
3.1 This Agreement shall remain in effect for three (3) years.
3.2 Either party may terminate this Agreement without cause upon giving ninety (90) days prior written notice.
3.3 Either party may terminate if the other breaches any material term and fails to cure within thirty (30) days.

ARTICLE 4: LIMITATION OF LIABILITY
4.1 Aggregate Cap: Except for indemnification under Article 5, each party's aggregate liability shall be limited to the total fees paid under this Agreement in the twelve (12) months preceding the claim.
"""

SAMPLE_HIGH_RISK_CONTRACT = """VENDOR SERVICES AGREEMENT

This Agreement is made by and between Global Supplies Inc ("Client") and FastLogistics Co ("Vendor").

Client shall pay all fees upon receipt. Late payments bear interest at 2.5% per month.
Vendor may terminate if Client breaches any material term and fails to cure within seven (7) days.
"""


def test_extraction_structure_and_source_evidence_grounding():
    buffer = ingest_text_buffer(SAMPLE_MSA, source_filename="sample_msa.txt")
    contract = extract_contract(buffer)

    # Metadata assertions
    assert contract.metadata.title == 'MASTER SERVICES AGREEMENT'
    assert contract.metadata.contract_type == "MSA"
    assert contract.metadata.effective_date == "January 15, 2025"
    assert contract.metadata.governing_law == "Delaware"

    # Strict source evidence grounding assertion on metadata
    meta_ev = contract.metadata.evidence
    assert meta_ev is not None
    assert buffer.slice(meta_ev.start_char_offset, meta_ev.end_char_offset) == meta_ev.verbatim_quote

    # Parties assertions
    assert len(contract.parties) == 2
    p1 = contract.parties[0]
    p2 = contract.parties[1]
    assert p1.name == "Acme Corp"
    assert p1.role == "Client"
    assert p2.name == "TechSolutions LLC"
    assert p2.role == "Vendor"
    assert buffer.slice(p1.evidence.start_char_offset, p1.evidence.end_char_offset) == p1.evidence.verbatim_quote

    # Commercial terms assertions
    assert contract.commercial_terms.payment_terms is not None
    assert "Net 30" in contract.commercial_terms.payment_terms or "thirty (30) days" in contract.commercial_terms.payment_terms
    assert "1.5% per month" in contract.commercial_terms.late_payment_penalty

    # Obligations assertions
    assert len(contract.obligations) >= 2
    for obl in contract.obligations:
        ev = obl.evidence
        assert buffer.slice(ev.start_char_offset, ev.end_char_offset) == ev.verbatim_quote

    # Risk and liability assertions
    assert contract.risk_and_liability.liability_cap_type == "Aggregate"
    assert len(contract.risk_and_liability.carve_outs) > 0
    assert any("indemn" in c.lower() for c in contract.risk_and_liability.carve_outs)

    # Termination assertions
    assert contract.termination_and_renewal.termination_for_convenience is True
    assert contract.termination_and_renewal.notice_for_convenience_days == 90
    assert contract.termination_and_renewal.termination_for_cause_cure_days == 30


def test_risk_analysis_on_standard_msa():
    buffer = ingest_text_buffer(SAMPLE_MSA, source_filename="sample_msa.txt")
    contract = extract_contract(buffer)
    risk_report = analyze_contract_risks(contract, buffer)

    assert risk_report.total_risks_identified > 0
    # Indemnification is carved out from cap -> High risk
    indem_risk = next((r for r in risk_report.risks if r.category == RiskCategory.LIABILITY), None)
    assert indem_risk is not None
    assert indem_risk.severity == RiskSeverity.HIGH
    assert "Uncapped Indemnification" in indem_risk.title

    # 1.5% interest -> Medium risk
    pay_risk = next((r for r in risk_report.risks if r.category == RiskCategory.PAYMENT), None)
    assert pay_risk is not None
    assert pay_risk.severity == RiskSeverity.MEDIUM


def test_high_risk_contract_flags_critical_and_cure_period():
    buffer = ingest_text_buffer(SAMPLE_HIGH_RISK_CONTRACT, source_filename="high_risk.txt")
    contract = extract_contract(buffer)
    risk_report = analyze_contract_risks(contract, buffer)

    # Uncapped liability must trigger CRITICAL risk
    crit_liab = next((r for r in risk_report.risks if r.severity == RiskSeverity.CRITICAL), None)
    assert crit_liab is not None
    assert "Absence of Limitation of Liability" in crit_liab.title

    # 7 days cure period must trigger HIGH risk
    term_risk = next((r for r in risk_report.risks if "Cure Period" in r.title), None)
    assert term_risk is not None
    assert term_risk.severity == RiskSeverity.HIGH
    assert "7" in term_risk.description

    # Overall score must reflect high risk
    assert risk_report.overall_risk_score >= 50.0
    assert "HIGH RISK" in risk_report.summary


def test_absence_based_risks_do_not_cite_contract_title():
    """Regression test: absence-based risks must have evidence=None, not cite contract title."""
    buffer = ingest_text_buffer(SAMPLE_HIGH_RISK_CONTRACT, source_filename="high_risk.txt")
    contract = extract_contract(buffer)
    risk_report = analyze_contract_risks(contract, buffer)

    title_quote = contract.metadata.title

    absence_risks_found = 0
    for risk in risk_report.risks:
        if any(kw in risk.title for kw in ["Absence", "No Termination", "Unspecified Governing"]):
            absence_risks_found += 1
            assert risk.evidence is None, f"Risk '{risk.title}' should have evidence=None, got {risk.evidence}"

    assert absence_risks_found >= 2, "Expected to find at least 2 absence-based risks in high risk sample"


def test_failed_evidence_matching_does_not_return_first_100_chars():
    """Regression test: failed quotation matching returns None, never the first 100 chars."""
    from analysis.extractor import _build_evidence

    buffer = ingest_text_buffer(SAMPLE_MSA, source_filename="sample_msa.txt")
    first_100_chars = buffer.slice(0, min(100, buffer.total_chars))

    ev = _build_evidence(buffer, "This non-existent clause was never written in the contract.")
    assert ev is None, "Failed evidence match must return None, not fake source evidence"

    # Also verify empty string returns None
    assert _build_evidence(buffer, "") is None
    assert _build_evidence(buffer, "   ") is None


def test_late_payment_risk_uses_correct_clause_evidence():
    """Regression test: late payment risk cites interest clause, not payment terms quote."""
    buffer = ingest_text_buffer(SAMPLE_MSA, source_filename="sample_msa.txt")
    contract = extract_contract(buffer)
    risk_report = analyze_contract_risks(contract, buffer)

    pay_risk = next((r for r in risk_report.risks if r.category == RiskCategory.PAYMENT), None)
    assert pay_risk is not None
    assert pay_risk.evidence is not None, "Late payment risk must have attached source evidence"

    # Must quote the late payment interest sentence
    assert "1.5%" in pay_risk.evidence.verbatim_quote
    assert "interest" in pay_risk.evidence.verbatim_quote.lower()

    # Must NOT quote the payment terms sentence
    assert "Net 30" not in pay_risk.evidence.verbatim_quote
    assert "thirty (30) days of receipt" not in pay_risk.evidence.verbatim_quote
