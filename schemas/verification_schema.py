"""
ContractIQ Verification Schema
Formal verification interface defining audit findings, discrepancy reporting,
and source grounding validation against raw contract buffers.
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from .contract_schema import SourceEvidence


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"                      # Factually supported by exact source text
    CONTRADICTED = "CONTRADICTED"              # Directly contradicts source document
    UNSUPPORTED = "UNSUPPORTED"                # Claim cannot be found or grounded in text
    AMBIGUOUS = "AMBIGUOUS"                    # Text is vague, conflicting, or legally uncertain
    UNVERIFIED_CITATION = "UNVERIFIED_CITATION"  # Character offsets or quotes do not match buffer


class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"   # Financial risk, liability cap mismatch, governing law contradiction
    WARNING = "WARNING"     # Unclear notice window, missing non-vital deadline
    INFO = "INFO"           # Minor typographical or formatting discrepancy


class FindingAudit(BaseModel):
    finding_id: str = Field(description="Unique identifier of the audited claim/finding")
    category: str = Field(description="Metadata, Commercial, Obligation, Liability, or Termination")
    original_claim: str = Field(description="Summary of the finding extracted by Contract Analyst")
    submitted_evidence: SourceEvidence = Field(description="SourceEvidence submitted by Contract Analyst")
    
    status: VerificationStatus = Field(description="Outcome of verification audit")
    buffer_match_exact: bool = Field(description="True if verbatim_quote matches exact slice at character offsets")
    normalized_token_match_score: float = Field(ge=0.0, le=1.0, description="Token similarity score against document buffer")
    
    surrounding_context_consistent: bool = Field(
        description="True if surrounding clause does not introduce unstated exceptions or conditions"
    )
    discrepancy_explanation: Optional[str] = Field(
        default=None, description="Detailed explanation if claim is contradicted, unsupported, or ambiguous"
    )
    severity: Optional[IssueSeverity] = Field(default=None, description="Severity if discrepancy is identified")
    suggested_correction: Optional[str] = Field(
        default=None, description="Recommended correction grounded in source text"
    )


class ContractVerificationReport(BaseModel):
    contract_id: str = Field(description="ID of the contract document being verified")
    document_hash: str = Field(description="SHA-256 hash of raw contract text buffer")
    total_findings_audited: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    contradicted_count: int = Field(ge=0)
    unsupported_count: int = Field(ge=0)
    ambiguous_count: int = Field(ge=0)
    
    findings_audit: List[FindingAudit] = Field(default_factory=list)
    critical_discrepancies: List[FindingAudit] = Field(default_factory=list)
    unresolved_questions_for_human: List[str] = Field(
        default_factory=list, description="Contractual ambiguities requiring human legal counsel"
    )
    human_review_required: bool = Field(default=False)
