"""ContractIQ Contract Information Extractor.

Extracts structured contract entities, obligations, commercial terms,
and risk parameters from a DocumentBuffer with exact SourceEvidence grounding.
"""

import re
from typing import List, Optional, Tuple
from ingestion.models import DocumentBuffer
from schemas.contract_schema import (
    SourceEvidence,
    ContractParty,
    ContractMetadata,
    CommercialTerms,
    ContractObligation,
    RiskAndLiability,
    TerminationAndRenewal,
    ExtractedContract,
)


def _build_evidence(
    buffer: DocumentBuffer,
    quote: str,
    default_section: Optional[str] = None,
    confidence: float = 0.95,
) -> Optional[SourceEvidence]:
    """Helper to locate a quote in the buffer and build grounded SourceEvidence.

    Returns None if the quotation cannot be found in the document buffer.
    Never creates fake source evidence or falls back to unrelated document text.
    """
    if not quote or not quote.strip():
        return None

    span = buffer.find_verbatim_quote(quote)
    if span:
        start, end = span
        score = confidence
    else:
        norm = buffer.find_normalized_quote(quote)
        if norm:
            start, end, score = norm
            quote = buffer.slice(start, end)
        else:
            return None

    page_num = buffer.get_page_for_offset(start)
    sec_obj = buffer.get_section_for_offset(start)
    sec_ref = sec_obj.section_id if sec_obj else default_section

    return SourceEvidence(
        verbatim_quote=quote,
        page_number=page_num,
        section_reference=sec_ref,
        start_char_offset=start,
        end_char_offset=end,
        confidence_score=score,
    )


def extract_metadata(buffer: DocumentBuffer) -> ContractMetadata:
    """Extracts title, contract type, dates, and governing law with evidence."""
    text = buffer.raw_text

    # Title detection
    title = "Contract Agreement"
    title_quote = ""
    first_lines = [line.strip() for line in text.split("\n") if line.strip()][:5]
    for line in first_lines:
        if any(term in line.upper() for term in ["AGREEMENT", "CONTRACT", "STATEMENT OF WORK", "SOW", "NDA"]):
            title = line
            title_quote = line
            break

    if not title_quote and first_lines:
        title_quote = first_lines[0]
        title = first_lines[0]

    # Contract Type
    contract_type = "Agreement"
    upper_title = title.upper()
    if "NON-DISCLOSURE" in upper_title or "NDA" in upper_title:
        contract_type = "NDA"
    elif "MASTER SERVICES" in upper_title or "MSA" in upper_title:
        contract_type = "MSA"
    elif "STATEMENT OF WORK" in upper_title or "SOW" in upper_title:
        contract_type = "SOW"
    elif "SERVICE LEVEL" in upper_title or "SLA" in upper_title:
        contract_type = "SLA"
    elif "DATA PROCESSING" in upper_title or "DPA" in upper_title:
        contract_type = "DPA"
    elif "LICENSE" in upper_title:
        contract_type = "License"

    # Effective Date
    effective_date = None
    eff_match = re.search(
        r"(?:effective as of\s+|Effective Date[:\s]+)([A-Za-z]+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if eff_match:
        effective_date = eff_match.group(1).strip()

    # Governing law
    governing_law = None
    jurisdiction_venue = None
    gov_match = re.search(
        r"(?:governed by(?: and construed in accordance with)? the laws of (?:the State of )?([A-Za-z\s]+?)(?:\.|,|;|\sand))",
        text,
        re.IGNORECASE,
    )
    if gov_match:
        governing_law = gov_match.group(1).strip()
        jurisdiction_venue = governing_law

    evidence = _build_evidence(buffer, title_quote, default_section="Preamble") if title_quote else None
    if evidence is None:
        evidence = SourceEvidence(
            verbatim_quote="[Title evidence unavailable]",
            page_number=1,
            section_reference="Preamble",
            start_char_offset=0,
            end_char_offset=0,
            confidence_score=0.0,
        )

    return ContractMetadata(
        title=title,
        contract_type=contract_type,
        effective_date=effective_date,
        governing_law=governing_law,
        jurisdiction_venue=jurisdiction_venue,
        evidence=evidence,
    )


def extract_parties(buffer: DocumentBuffer) -> List[ContractParty]:
    """Extracts contracting parties, roles, and entity structures."""
    parties: List[ContractParty] = []
    text = buffer.raw_text

    # Pattern: by and between [Party A] ("Role A") and [Party B] ("Role B")
    preamble_match = re.search(
        r"by and between\s+([A-Za-z0-9\s,\.]+?)\s*\(\"([^\"]+)\"\)\s+and\s+([A-Za-z0-9\s,\.]+?)\s*\(\"([^\"]+)\"\)",
        text,
        re.IGNORECASE,
    )
    if preamble_match:
        p1_name = preamble_match.group(1).strip()
        p1_role = preamble_match.group(2).strip()
        p2_name = preamble_match.group(3).strip()
        p2_role = preamble_match.group(4).strip()

        quote = preamble_match.group(0)
        ev = _build_evidence(buffer, quote, default_section="Preamble")
        if ev is None:
            ev = SourceEvidence(
                verbatim_quote=quote,
                page_number=1,
                section_reference="Preamble",
                start_char_offset=0,
                end_char_offset=0,
                confidence_score=0.0,
            )

        parties.append(
            ContractParty(
                name=p1_name,
                role=p1_role,
                entity_type="Corporation" if "Corp" in p1_name or "Inc" in p1_name else "LLC",
                evidence=ev,
            )
        )
        parties.append(
            ContractParty(
                name=p2_name,
                role=p2_role,
                entity_type="LLC" if "LLC" in p2_name else "Corporation",
                evidence=ev,
            )
        )
    else:
        # Fallback to party markers with explicit unverified evidence
        fallback_ev = SourceEvidence(
            verbatim_quote="[Party names inferred; no explicit party clause identified]",
            page_number=1,
            section_reference="Preamble",
            start_char_offset=0,
            end_char_offset=0,
            confidence_score=0.0,
        )
        parties.append(
            ContractParty(name="Party A", role="Client", evidence=fallback_ev)
        )
        parties.append(
            ContractParty(name="Party B", role="Vendor", evidence=fallback_ev)
        )

    return parties


def extract_commercial_terms(buffer: DocumentBuffer) -> CommercialTerms:
    """Extracts fee structure, payment terms, currency, and late penalties."""
    text = buffer.raw_text
    evidence_list: List[SourceEvidence] = []

    # Payment terms (e.g., Net 30, within thirty (30) days)
    payment_terms = None
    pt_match = re.search(
        r"((?:within\s+(?:thirty|sixty|forty-five|\d+)\s*\(\d+\)\s*days\s*of\s*receipt|Net\s*\d+)[^\.\n\r]*)",
        text,
        re.IGNORECASE,
    )
    if pt_match:
        payment_terms = pt_match.group(1).strip()
        ev = _build_evidence(buffer, pt_match.group(0))
        if ev:
            evidence_list.append(ev)

    # Late payment penalty
    late_payment_penalty = None
    late_match = re.search(
        r"(interest at\s*\d+(?:\.\d+)?%\s*per\s*(?:month|annum|year)[^\.\n\r]*)",
        text,
        re.IGNORECASE,
    )
    if late_match:
        late_payment_penalty = late_match.group(1).strip()
        ev = _build_evidence(buffer, late_match.group(0))
        if ev:
            evidence_list.append(ev)

    # Total value and currency
    total_val = None
    currency = "USD" if "$" in text or "USD" in text else None
    val_match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
    if val_match:
        try:
            total_val = float(val_match.group(1).replace(",", ""))
        except ValueError:
            pass

    return CommercialTerms(
        total_value=total_val,
        currency=currency,
        payment_terms=payment_terms,
        billing_frequency="Monthly" if "monthly" in text.lower() else None,
        late_payment_penalty=late_payment_penalty,
        evidence=evidence_list,
    )


def extract_obligations(buffer: DocumentBuffer) -> List[ContractObligation]:
    """Extracts contractual obligations and operational covenants."""
    text = buffer.raw_text
    obligations: List[ContractObligation] = []

    # Pattern for obligations: [Party] shall [do something]
    obl_matches = list(re.finditer(r"([A-Z][A-Za-z0-9\s]+?)\s+shall\s+([^\.\n\r]+?)(?:\.|\n)", text))
    count = 1
    for match in obl_matches[:5]:  # Capture up to 5 core obligations
        obligor = match.group(1).strip()
        duty = match.group(2).strip()
        quote = match.group(0).strip()
        ev = _build_evidence(buffer, quote)
        if ev is None:
            ev = SourceEvidence(
                verbatim_quote="[Obligation evidence unavailable]",
                page_number=1,
                section_reference=None,
                start_char_offset=0,
                end_char_offset=0,
                confidence_score=0.0,
            )

        category = "Operational"
        if any(w in duty.lower() for w in ["pay", "invoice", "fee"]):
            category = "Payment"
        elif any(w in duty.lower() for w in ["deliver", "service", "work"]):
            category = "Deliverable"
        elif any(w in duty.lower() for w in ["report", "audit"]):
            category = "Reporting"
        elif any(w in duty.lower() for w in ["confidential", "disclose", "protect"]):
            category = "Security"

        obligations.append(
            ContractObligation(
                obligation_id=f"OBL-{count:03d}",
                obligor=obligor,
                category=category,
                description=duty,
                evidence=ev,
            )
        )
        count += 1

    return obligations


def extract_risk_and_liability(buffer: DocumentBuffer) -> RiskAndLiability:
    """Extracts liability caps, carve-outs, and indemnification provisions."""
    text = buffer.raw_text
    evidence_list: List[SourceEvidence] = []

    # Aggregate liability cap
    cap_type = None
    cap_amount = None
    cap_match = re.search(
        r"(aggregate liability shall be limited to[^\.\n\r]+)",
        text,
        re.IGNORECASE,
    )
    if cap_match:
        cap_type = "Aggregate"
        cap_amount = cap_match.group(1).strip()
        ev = _build_evidence(buffer, cap_match.group(0))
        if ev:
            evidence_list.append(ev)

    # Carve-outs (exceptions to liability cap)
    carve_outs: List[str] = []
    carve_match = re.search(
        r"Except for ([^\.\n\r]+?), each party's aggregate liability",
        text,
        re.IGNORECASE,
    )
    if carve_match:
        carve_text = carve_match.group(1).strip()
        carve_outs = [c.strip() for c in re.split(r",|\sand\s|or\s", carve_text) if c.strip()]
        ev = _build_evidence(buffer, carve_match.group(0))
        if ev:
            evidence_list.append(ev)

    # Indemnification
    indem_scope = None
    indem_match = re.search(
        r"(indemnif[a-z\s]+against[^\.\n\r]+)",
        text,
        re.IGNORECASE,
    )
    if indem_match:
        indem_scope = indem_match.group(1).strip()
        ev = _build_evidence(buffer, indem_match.group(0))
        if ev:
            evidence_list.append(ev)

    return RiskAndLiability(
        liability_cap_type=cap_type,
        liability_cap_amount=cap_amount,
        carve_outs=carve_outs,
        indemnification_scope=indem_scope,
        evidence=evidence_list,
    )


def extract_termination_and_renewal(buffer: DocumentBuffer) -> TerminationAndRenewal:
    """Extracts term length, termination for convenience, and cure periods."""
    text = buffer.raw_text
    evidence_list: List[SourceEvidence] = []

    # Term length
    term_length = None
    term_match = re.search(
        r"(remain in effect for\s+[^\.\n\r]+)",
        text,
        re.IGNORECASE,
    )
    if term_match:
        term_length = term_match.group(1).strip()
        ev = _build_evidence(buffer, term_match.group(0))
        if ev:
            evidence_list.append(ev)

    # Termination for convenience
    term_conv = False
    notice_conv_days = None
    conv_match = re.search(
        r"(terminate\s+this\s+Agreement\s+without\s+cause\s+upon\s+giving\s+(\d+|[a-z]+)\s*(?:\(\d+\))?\s*days\s+prior\s+written\s+notice)",
        text,
        re.IGNORECASE,
    )
    if conv_match:
        term_conv = True
        ev = _build_evidence(buffer, conv_match.group(0))
        if ev:
            evidence_list.append(ev)
        digits = re.search(r"\d+", conv_match.group(0))
        if digits:
            notice_conv_days = int(digits.group(0))

    # Termination for cause / cure period
    cure_days = None
    cure_match = re.search(
        r"(breaches\s+any\s+material\s+term\s+and\s+fails\s+to\s+cure\s+within\s+(\d+|[a-z]+)\s*(?:\(\d+\))?\s*days)",
        text,
        re.IGNORECASE,
    )
    if cure_match:
        ev = _build_evidence(buffer, cure_match.group(0))
        if ev:
            evidence_list.append(ev)
        digits = re.search(r"\d+", cure_match.group(0))
        if digits:
            cure_days = int(digits.group(0))

    auto_renewal = bool(re.search(r'auto(?:matic(?:ally)?)?[\s-]*(?:annual\s+)?renew', text, re.IGNORECASE))

    return TerminationAndRenewal(
        term_length=term_length,
        auto_renewal=auto_renewal,
        termination_for_convenience=term_conv,
        notice_for_convenience_days=notice_conv_days,
        termination_for_cause_cure_days=cure_days,
        evidence=evidence_list,
    )


def extract_contract(buffer: DocumentBuffer) -> ExtractedContract:
    """Top-level pipeline extracting complete ExtractedContract from DocumentBuffer."""
    metadata = extract_metadata(buffer)
    parties = extract_parties(buffer)
    commercial = extract_commercial_terms(buffer)
    obligations = extract_obligations(buffer)
    risk_liab = extract_risk_and_liability(buffer)
    term_renew = extract_termination_and_renewal(buffer)

    return ExtractedContract(
        document_id=buffer.document_id,
        raw_document_length_chars=buffer.total_chars,
        metadata=metadata,
        parties=parties,
        commercial_terms=commercial,
        obligations=obligations,
        risk_and_liability=risk_liab,
        termination_and_renewal=term_renew,
    )
