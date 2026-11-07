"""ContractIQ Risk Identification and Scoring Engine.

Audits extracted contract terms and flags legal, operational, and commercial risks
with grounded SourceEvidence citations and mitigation advice.
"""

from typing import List
from ingestion.models import DocumentBuffer
from schemas.contract_schema import ExtractedContract
from .models import (
    RiskSeverity,
    RiskCategory,
    ContractRisk,
    RiskAssessmentReport,
)


def analyze_contract_risks(
    contract: ExtractedContract,
    buffer: DocumentBuffer,
) -> RiskAssessmentReport:
    """Evaluates an ExtractedContract against standard legal risk heuristics."""
    risks: List[ContractRisk] = []
    risk_counter = 1

    # 1. Liability Cap Audit
    risk_liab = contract.risk_and_liability
    if not risk_liab.liability_cap_amount and not risk_liab.liability_cap_type:
        risks.append(
            ContractRisk(
                risk_id=f"RISK-LIAB-{risk_counter:02d}",
                category=RiskCategory.LIABILITY,
                severity=RiskSeverity.CRITICAL,
                title="Absence of Limitation of Liability",
                description="The contract does not establish an express aggregate liability cap, exposing the parties to unlimited financial damages.",
                mitigation_recommendation="Insert a mutual aggregate liability cap limited to 12 months fees paid under the agreement.",
                evidence=None,
            )
        )
        risk_counter += 1
    else:
        # Check carve-outs
        if any("indemn" in c.lower() for c in risk_liab.carve_outs):
            ev = risk_liab.evidence[0] if risk_liab.evidence else None
            risks.append(
                ContractRisk(
                    risk_id=f"RISK-LIAB-{risk_counter:02d}",
                    category=RiskCategory.LIABILITY,
                    severity=RiskSeverity.HIGH,
                    title="Uncapped Indemnification Exposure",
                    description="Indemnification obligations are carved out from the aggregate liability cap, creating uncapped exposure for third-party claims.",
                    mitigation_recommendation="Negotiate a separate supercap (e.g., 2x annual contract value) for indemnification obligations.",
                    evidence=ev,
                )
            )
            risk_counter += 1

    # 2. Termination & Cure Period Audit
    term_renew = contract.termination_and_renewal
    if term_renew.termination_for_cause_cure_days is not None:
        if term_renew.termination_for_cause_cure_days < 15:
            ev = term_renew.evidence[0] if term_renew.evidence else None
            risks.append(
                ContractRisk(
                    risk_id=f"RISK-TERM-{risk_counter:02d}",
                    category=RiskCategory.TERMINATION,
                    severity=RiskSeverity.HIGH,
                    title="Abnormally Short Material Breach Cure Period",
                    description=f"Breach cure window is set to only {term_renew.termination_for_cause_cure_days} days, increasing the risk of premature termination before operational remedy.",
                    mitigation_recommendation="Request extending the cure period to the commercial standard of thirty (30) business days.",
                    evidence=ev,
                )
            )
            risk_counter += 1

    if not term_renew.termination_for_convenience:
        risks.append(
            ContractRisk(
                risk_id=f"RISK-TERM-{risk_counter:02d}",
                category=RiskCategory.TERMINATION,
                severity=RiskSeverity.MEDIUM,
                title="No Termination for Convenience",
                description="Neither party has the contractual right to terminate without cause, locking both parties into the agreement for the full term.",
                mitigation_recommendation="Propose mutual termination for convenience upon 60 or 90 days written notice.",
                evidence=None,
            )
        )
        risk_counter += 1
    elif term_renew.notice_for_convenience_days and term_renew.notice_for_convenience_days > 60:
        ev = term_renew.evidence[0] if term_renew.evidence else None
        risks.append(
            ContractRisk(
                risk_id=f"RISK-TERM-{risk_counter:02d}",
                category=RiskCategory.TERMINATION,
                severity=RiskSeverity.LOW,
                title="Extended Notice Window for Convenience Termination",
                description=f"Convenience termination requires {term_renew.notice_for_convenience_days} days notice, requiring early planning if unwinding the relationship.",
                mitigation_recommendation="Standardize notice window to thirty (30) days.",
                evidence=ev,
            )
        )
        risk_counter += 1

    # 3. Commercial & Payment Penalties
    comm = contract.commercial_terms
    if comm.late_payment_penalty:
        if "1.5%" in comm.late_payment_penalty or "2%" in comm.late_payment_penalty:
            # Attach evidence specifically matching the late-interest clause, not the first commercial evidence
            late_ev = None
            if comm.evidence:
                for ev_candidate in comm.evidence:
                    quote_lower = ev_candidate.verbatim_quote.lower()
                    if any(term in quote_lower for term in ["interest", "late", "penalty", "%"]):
                        late_ev = ev_candidate
                        break
                if late_ev is None:
                    late_ev = comm.evidence[-1]
            risks.append(
                ContractRisk(
                    risk_id=f"RISK-PAY-{risk_counter:02d}",
                    category=RiskCategory.PAYMENT,
                    severity=RiskSeverity.MEDIUM,
                    title="Elevated Late Payment Interest Rate",
                    description=f"Late fee interest is set at {comm.late_payment_penalty} (equivalent to 18-24% annually), exceeding typical commercial standards.",
                    mitigation_recommendation="Negotiate interest to 1.0% per month or the maximum rate permitted by law, whichever is lower.",
                    evidence=late_ev,
                )
            )
            risk_counter += 1

    # 4. Governing Law Audit
    if not contract.metadata.governing_law:
        risks.append(
            ContractRisk(
                risk_id=f"RISK-GOV-{risk_counter:02d}",
                category=RiskCategory.GOVERNANCE,
                severity=RiskSeverity.MEDIUM,
                title="Unspecified Governing Law / Jurisdiction",
                description="The contract omits an explicit governing law clause, leading to significant legal ambiguity in case of cross-border dispute resolution.",
                mitigation_recommendation="Include an express governing law clause designating Delaware, New York, or California state courts.",
                evidence=None,
            )
        )
        risk_counter += 1

    # Calculate composite risk score
    score = 0.0
    critical_c = 0
    high_c = 0
    med_c = 0
    low_c = 0

    for r in risks:
        if r.severity == RiskSeverity.CRITICAL:
            score += 25.0
            critical_c += 1
        elif r.severity == RiskSeverity.HIGH:
            score += 15.0
            high_c += 1
        elif r.severity == RiskSeverity.MEDIUM:
            score += 8.0
            med_c += 1
        elif r.severity == RiskSeverity.LOW:
            score += 3.0
            low_c += 1

    overall_score = min(100.0, score)

    # Executive Summary Generation
    if overall_score >= 50.0:
        summary = f"HIGH RISK CONTRACT (Score: {overall_score:.1f}/100): Identified {critical_c} critical and {high_c} high severity exposures. Key concerns include {risks[0].title}."
    elif overall_score >= 20.0:
        summary = f"MODERATE RISK CONTRACT (Score: {overall_score:.1f}/100): Identified {len(risks)} exposures ({high_c} high, {med_c} medium). Recommended adjustments before execution."
    else:
        summary = f"LOW RISK CONTRACT (Score: {overall_score:.1f}/100): Standard terms with {len(risks)} minor items noted."

    return RiskAssessmentReport(
        contract_id=contract.document_id,
        overall_risk_score=overall_score,
        total_risks_identified=len(risks),
        critical_count=critical_c,
        high_count=high_c,
        medium_count=med_c,
        low_count=low_c,
        risks=risks,
        summary=summary,
    )
