"""ContractIQ End-to-End Analysis Pipeline.

Orchestrates the full contract analysis flow:
  1. Document ingestion (PDF or text)
  2. Structured entity/clause extraction
  3. Risk identification and scoring
  4. Memory retention via Hindsight Cloud (with local fallback)

Returns a unified result dictionary with all extracted data,
risk assessment, and source citations.
"""

import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from ingestion import ingest_pdf_file, ingest_text_buffer, DocumentBuffer
from analysis import extract_contract, analyze_contract_risks
from memory import MemoryManager, HindsightClient
from schemas import (
    ExtractedContract,
    HindsightAgreementRecord,
    HindsightObservation,
    HindsightGraphEdge,
    HindsightIngestionPayload,
    ContractVerificationReport,
    FindingAudit,
    VerificationStatus,
)

# Load environment variables from .env file if present
load_dotenv()


def _create_auto_verification_report(
    contract: ExtractedContract,
    buffer: DocumentBuffer,
) -> ContractVerificationReport:
    """Creates an automated verification report by validating source evidence against the buffer.

    Performs deterministic quote-matching and offset validation against the source document.
    """
    findings: list[FindingAudit] = []
    verified_count = 0
    contradicted_count = 0
    unsupported_count = 0
    ambiguous_count = 0

    # Collect all evidence items to verify
    evidence_items = []

    # Metadata evidence
    evidence_items.append(("META-001", "Metadata", contract.metadata.title, contract.metadata.evidence))

    # Party evidence
    for i, party in enumerate(contract.parties):
        evidence_items.append((f"PARTY-{i+1:03d}", "Metadata", f"{party.name} ({party.role})", party.evidence))

    # Commercial terms evidence (OBS-COMM-001 matches memory observation)
    for i, ev in enumerate(contract.commercial_terms.evidence):
        evidence_items.append((f"OBS-COMM-{i+1:03d}", "Commercial", contract.commercial_terms.payment_terms or "Commercial terms", ev))

    # Risk/liability evidence (OBS-LIAB-001 matches memory observation)
    for i, ev in enumerate(contract.risk_and_liability.evidence):
        evidence_items.append((f"OBS-LIAB-{i+1:03d}", "Liability", contract.risk_and_liability.liability_cap_type or "Liability terms", ev))

    # Termination evidence (OBS-TERM-001 matches memory observation)
    for i, ev in enumerate(contract.termination_and_renewal.evidence):
        evidence_items.append((f"OBS-TERM-{i+1:03d}", "Termination", "Termination and renewal terms", ev))

    # Obligation evidence (OBS-OBL-001 matches memory observation)
    for obl in contract.obligations:
        evidence_items.append((f"OBS-{obl.obligation_id}", "Obligation", obl.description, obl.evidence))

    for finding_id, category, claim, evidence in evidence_items:
        buffer_match = False
        match_score = 0.0
        discrepancy = None

        if evidence is None or evidence.confidence_score == 0.0 or evidence.verbatim_quote.startswith("["):
            status = VerificationStatus.UNSUPPORTED
            discrepancy = "No grounded source evidence attached to this claim."
        else:
            try:
                actual_slice = buffer.slice(evidence.start_char_offset, evidence.end_char_offset)
                buffer_match = (actual_slice == evidence.verbatim_quote)
                if buffer_match:
                    match_score = 1.0
                else:
                    norm_result = buffer.find_normalized_quote(evidence.verbatim_quote)
                    match_score = norm_result[2] if norm_result else 0.0
            except (ValueError, IndexError):
                match_score = 0.0

            if buffer_match or match_score >= 0.95:
                status = VerificationStatus.VERIFIED
            elif match_score > 0.0:
                status = VerificationStatus.AMBIGUOUS
                discrepancy = f"Quotation matched with low token similarity ({match_score:.2%})."
            else:
                status = VerificationStatus.UNVERIFIED_CITATION
                discrepancy = "Quotation was not found in the source document buffer at stated offsets."

        if status == VerificationStatus.VERIFIED:
            verified_count += 1
        elif status == VerificationStatus.CONTRADICTED:
            contradicted_count += 1
        elif status == VerificationStatus.UNSUPPORTED:
            unsupported_count += 1
        else:
            ambiguous_count += 1

        submitted_ev = evidence if evidence else SourceEvidence(
            verbatim_quote="[No evidence provided]",
            page_number=1,
            start_char_offset=0,
            end_char_offset=0,
            confidence_score=0.0,
        )

        findings.append(FindingAudit(
            finding_id=finding_id,
            category=category,
            original_claim=claim,
            submitted_evidence=submitted_ev,
            status=status,
            buffer_match_exact=buffer_match,
            normalized_token_match_score=match_score,
            surrounding_context_consistent=buffer_match,
            discrepancy_explanation=discrepancy,
        ))

    return ContractVerificationReport(
        contract_id=contract.document_id,
        document_hash=buffer.document_hash,
        total_findings_audited=len(findings),
        verified_count=verified_count,
        contradicted_count=contradicted_count,
        unsupported_count=unsupported_count,
        ambiguous_count=ambiguous_count,
        findings_audit=findings,
        human_review_required=(contradicted_count > 0 or unsupported_count > 0 or ambiguous_count > 0),
    )


def _build_memory_payload(
    contract: ExtractedContract,
    buffer: DocumentBuffer,
    verification_report: ContractVerificationReport,
) -> HindsightIngestionPayload:
    """Converts extraction results into a Hindsight ingestion payload."""
    agreement = HindsightAgreementRecord(
        memory_id=f"MEM-{contract.document_id}",
        contract_id=contract.document_id,
        document_hash=buffer.document_hash,
        title=contract.metadata.title,
        contract_type=contract.metadata.contract_type,
        status="active",
        parties=[p.name for p in contract.parties],
        effective_date=contract.metadata.effective_date,
        expiration_date=contract.metadata.expiration_date,
        governing_law=contract.metadata.governing_law,
        evidence=contract.metadata.evidence,
    )

    observations: list[HindsightObservation] = []

    # Commercial terms observation (only if clause-specific evidence exists)
    if contract.commercial_terms.payment_terms and contract.commercial_terms.evidence:
        ev = contract.commercial_terms.evidence[0]
        if ev.confidence_score > 0.0 and not ev.verbatim_quote.startswith("["):
            observations.append(HindsightObservation(
                observation_id="OBS-COMM-001",
                contract_id=contract.document_id,
                category="payment_terms",
                clause_reference=ev.section_reference,
                quote=ev.verbatim_quote,
                normalized_summary=f"Payment terms: {contract.commercial_terms.payment_terms}",
                provenance=ev,
            ))

    # Liability observation (only if clause-specific evidence exists)
    if contract.risk_and_liability.liability_cap_type and contract.risk_and_liability.evidence:
        ev = contract.risk_and_liability.evidence[0]
        if ev.confidence_score > 0.0 and not ev.verbatim_quote.startswith("["):
            observations.append(HindsightObservation(
                observation_id="OBS-LIAB-001",
                contract_id=contract.document_id,
                category="limitation_of_liability",
                clause_reference=ev.section_reference,
                quote=ev.verbatim_quote,
                normalized_summary=f"Liability cap: {contract.risk_and_liability.liability_cap_type} - {contract.risk_and_liability.liability_cap_amount or 'unspecified amount'}",
                provenance=ev,
            ))

    # Termination observations (only if clause-specific evidence exists)
    if contract.termination_and_renewal.termination_for_convenience and contract.termination_and_renewal.evidence:
        ev = contract.termination_and_renewal.evidence[0]
        if ev.confidence_score > 0.0 and not ev.verbatim_quote.startswith("["):
            observations.append(HindsightObservation(
                observation_id="OBS-TERM-001",
                contract_id=contract.document_id,
                category="termination",
                clause_reference=ev.section_reference,
                quote=ev.verbatim_quote,
                normalized_summary=f"Termination for convenience with {contract.termination_and_renewal.notice_for_convenience_days or 'unspecified'} days notice",
                provenance=ev,
            ))

    # Obligation observations
    for obl in contract.obligations:
        if obl.evidence and obl.evidence.confidence_score > 0.0 and not obl.evidence.verbatim_quote.startswith("["):
            observations.append(HindsightObservation(
                observation_id=f"OBS-{obl.obligation_id}",
                contract_id=contract.document_id,
                category="obligation",
                clause_reference=obl.evidence.section_reference,
                quote=obl.evidence.verbatim_quote,
                normalized_summary=f"{obl.obligor}: {obl.description}",
                provenance=obl.evidence,
            ))

    # Party graph edges
    edges: list[HindsightGraphEdge] = []
    from schemas.memory_schema import EdgeType
    for party in contract.parties:
        edges.append(HindsightGraphEdge(
            source_id=contract.document_id,
            target_id=party.name,
            edge_type=EdgeType.PARTY_INVOLVED,
            effective_date=contract.metadata.effective_date,
        ))

    return HindsightIngestionPayload(
        contract_id=contract.document_id,
        agreement_record=agreement,
        observations=observations,
        graph_edges=edges,
        verification_report=verification_report,
        allow_unverified_draft=False,  # Strict production mode: only verified observations enter authoritative memory
    )


def analyze_pdf(
    pdf_path: str,
    document_id: Optional[str] = None,
    retain_in_memory: bool = True,
    hindsight_client: Optional[HindsightClient] = None,
) -> Dict[str, Any]:
    """Runs the full ContractIQ pipeline on a PDF file.

    Args:
        pdf_path: Path to the PDF contract file.
        document_id: Optional custom document ID.
        retain_in_memory: Whether to retain results in Hindsight memory.
        hindsight_client: Optional custom or mocked HindsightClient.

    Returns:
        Dictionary with keys: contract, risk_report, verification, memory_result, buffer_stats
    """
    # 1. Ingest
    buffer = ingest_pdf_file(pdf_path, document_id=document_id)

    return _analyze_buffer(buffer, retain_in_memory=retain_in_memory, hindsight_client=hindsight_client)


def analyze_text(
    text: str,
    source_filename: str = "contract.txt",
    document_id: Optional[str] = None,
    retain_in_memory: bool = True,
    hindsight_client: Optional[HindsightClient] = None,
) -> Dict[str, Any]:
    """Runs the full ContractIQ pipeline on raw text.

    Args:
        text: Raw contract text.
        source_filename: Original filename for tracking.
        document_id: Optional custom document ID.
        retain_in_memory: Whether to retain results in Hindsight memory.
        hindsight_client: Optional custom or mocked HindsightClient.

    Returns:
        Dictionary with keys: contract, risk_report, verification, memory_result, buffer_stats
    """
    buffer = ingest_text_buffer(text, source_filename=source_filename, document_id=document_id)

    return _analyze_buffer(buffer, retain_in_memory=retain_in_memory, hindsight_client=hindsight_client)


def _analyze_buffer(
    buffer: DocumentBuffer,
    retain_in_memory: bool = True,
    hindsight_client: Optional[HindsightClient] = None,
) -> Dict[str, Any]:
    """Core analysis pipeline operating on an ingested DocumentBuffer."""
    # 2. Extract
    contract = extract_contract(buffer)

    # 3. Risk Analysis
    risk_report = analyze_contract_risks(contract, buffer)

    # 4. Auto-Verification
    verification = _create_auto_verification_report(contract, buffer)

    # 5. Memory Retention
    memory_result = None
    if retain_in_memory:
        client = hindsight_client or HindsightClient()
        manager = MemoryManager(hindsight_client=client)
        payload = _build_memory_payload(contract, buffer, verification)
        memory_result = manager.retain_contract(payload)

    return {
        "contract": contract,
        "risk_report": risk_report,
        "verification": verification,
        "memory_result": memory_result,
        "buffer_stats": {
            "document_id": buffer.document_id,
            "document_hash": buffer.document_hash,
            "source_filename": buffer.source_filename,
            "total_chars": buffer.total_chars,
            "total_pages": buffer.total_pages,
            "sections_detected": len(buffer.sections),
        },
    }

