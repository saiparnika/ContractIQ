"""ContractIQ - Contract Extraction Schema Definitions.

Defines the exact structured output schema for the Contract Analyst,
including strict source provenance evidence for every extracted item.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SourceEvidence(BaseModel):
    """Source grounding for an extracted entity or clause."""
    verbatim_quote: str = Field(..., description="Exact textual excerpt from the contract document")
    page_number: int = Field(..., description="1-indexed page number where the excerpt appears")
    section_reference: Optional[str] = Field(None, description="Clause/section identifier, e.g., 'Section 8.2(b)'")
    start_char_offset: int = Field(..., description="Exact start character index in the parsed document buffer")
    end_char_offset: int = Field(..., description="Exact end character index in the parsed document buffer")
    bounding_box: Optional[Dict[str, float]] = Field(
        None, description="Bounding box coordinates for PDF rendering (x0, y0, x1, y1)"
    )
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Model extraction confidence score")


class ContractParty(BaseModel):
    """Contracting party entity."""
    name: str = Field(..., description="Legal name of the entity or individual")
    role: str = Field(..., description="Role in contract (e.g., Client, Vendor, Disclosing Party, Licensor)")
    entity_type: Optional[str] = Field(None, description="Entity structure (e.g., Corporation, LLC, Delaware C-Corp)")
    jurisdiction: Optional[str] = Field(None, description="State/Country of incorporation")
    signatory_name: Optional[str] = Field(None, description="Name of the authorized signatory")
    signatory_title: Optional[str] = Field(None, description="Title of the authorized signatory")
    evidence: SourceEvidence


class ContractMetadata(BaseModel):
    """Core contract metadata."""
    title: str = Field(..., description="Title of the agreement")
    contract_type: str = Field(..., description="Category (NDA, MSA, SOW, SLA, DPA, Employment, License)")
    effective_date: Optional[str] = Field(None, description="Effective date (ISO-8601 YYYY-MM-DD)")
    execution_date: Optional[str] = Field(None, description="Signature date (ISO-8601 YYYY-MM-DD)")
    expiration_date: Optional[str] = Field(None, description="Fixed expiration date if applicable")
    governing_law: Optional[str] = Field(None, description="Governing state/country law")
    jurisdiction_venue: Optional[str] = Field(None, description="Agreed jurisdiction / dispute forum")
    evidence: SourceEvidence


class CommercialTerms(BaseModel):
    """Financial and commercial obligations."""
    total_value: Optional[float] = Field(None, description="Total contract monetary value if fixed")
    currency: Optional[str] = Field(None, description="Currency code (USD, EUR, GBP, etc.)")
    payment_terms: Optional[str] = Field(None, description="Payment schedule (e.g., Net 30, upfront, milestone)")
    billing_frequency: Optional[str] = Field(None, description="Monthly, quarterly, annually, per-deliverable")
    late_payment_penalty: Optional[str] = Field(None, description="Late payment interest or penalties")
    price_escalation: Optional[str] = Field(None, description="Price increase / CPI adjustment clauses")
    evidence: List[SourceEvidence] = Field(default_factory=list)


class ContractObligation(BaseModel):
    """Specific operational or legal obligation."""
    obligation_id: str = Field(..., description="Unique obligation ID (e.g., OBL-001)")
    obligor: str = Field(..., description="Party bound by the obligation")
    category: str = Field(..., description="Deliverable, SLA, Reporting, Audit, Compliance, Security")
    description: str = Field(..., description="Detailed description of the duty or deliverable")
    deadline_or_frequency: Optional[str] = Field(None, description="Due date, SLA response time, or recurring interval")
    evidence: SourceEvidence


class RiskAndLiability(BaseModel):
    """Risk allocation, liability caps, and indemnification."""
    liability_cap_type: Optional[str] = Field(None, description="Aggregate cap, 12-month fees, fixed amount, uncapped")
    liability_cap_amount: Optional[str] = Field(None, description="Specified dollar amount or formula")
    carve_outs: List[str] = Field(default_factory=list, description="Exceptions to cap (e.g., gross negligence, IP, NDA)")
    indemnification_scope: Optional[str] = Field(None, description="Summary of indemnified claims")
    warranties: List[str] = Field(default_factory=list, description="Express warranties provided")
    disclaimers: List[str] = Field(default_factory=list, description="Warranty disclaimers (e.g., AS-IS, fitness for purpose)")
    evidence: List[SourceEvidence] = Field(default_factory=list)


class TerminationAndRenewal(BaseModel):
    """Termination rights and renewal conditions."""
    term_length: Optional[str] = Field(None, description="Initial term duration (e.g., 1 year, 36 months)")
    auto_renewal: bool = Field(False, description="Whether contract automatically renews")
    renewal_notice_window_days: Optional[int] = Field(None, description="Days prior to renewal notice must be given")
    termination_for_convenience: bool = Field(False, description="Whether unilateral termination without cause is permitted")
    notice_for_convenience_days: Optional[int] = Field(None, description="Notice period in days for convenience termination")
    termination_for_cause_cure_days: Optional[int] = Field(None, description="Cure period for material breach")
    post_termination_obligations: List[str] = Field(default_factory=list, description="Data return, IP destruction, transition duties")
    evidence: List[SourceEvidence] = Field(default_factory=list)


class ExtractedContract(BaseModel):
    """Complete structured extraction payload produced by Contract Analyst."""
    document_id: str = Field(..., description="Unique identifier or hash of the source document")
    metadata: ContractMetadata
    parties: List[ContractParty]
    commercial_terms: CommercialTerms
    obligations: List[ContractObligation]
    risk_and_liability: RiskAndLiability
    termination_and_renewal: TerminationAndRenewal
    raw_document_length_chars: int = Field(..., description="Total length of text buffer for span validation")
