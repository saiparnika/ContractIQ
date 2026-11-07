"""ContractIQ - Memory Specialist Schema Definitions.

Defines Hindsight long-term memory schemas for storing, recalling,
and cross-referencing contract knowledge across multi-contract lifecycles.
Aligns directly with schemas.contract_schema.ExtractedContract.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from schemas.contract_schema import SourceEvidence
from schemas.verification_schema import VerificationStatus, ContractVerificationReport


class MemoryCategory(str, Enum):
    """Hindsight memory organization categories."""
    WORLD_FACT = "world_fact"
    CONSOLIDATED_OBSERVATION = "consolidated_observation"
    RELATIONSHIP_EDGE = "relationship_edge"
    MENTAL_MODEL = "mental_model"


class EdgeType(str, Enum):
    """Graph edge types connecting contracts and entities."""
    GOVERNED_BY = "GOVERNED_BY"            # SOW -> MSA
    SUPERSEDES = "SUPERSEDES"              # Amendment Clause -> Prior Clause
    AMENDS = "AMENDS"                      # Amendment Contract -> Prior Contract
    PARTY_INVOLVED = "PARTY_INVOLVED"      # Contract -> Counterparty
    PARENT_COMPANY = "PARENT_COMPANY"      # Subsidiary -> Parent Entity
    RENEWS = "RENEWS"                      # Renewal Agreement -> Base Agreement


class HindsightPartyEntity(BaseModel):
    """Canonical counterparty entity stored in long-term memory."""
    canonical_name: str = Field(..., description="Standardized entity legal name")
    known_aliases: List[str] = Field(default_factory=list, description="Trade names, acronyms, or DBAs")
    jurisdiction: Optional[str] = Field(None, description="State/Country of incorporation")
    entity_type: Optional[str] = Field(None, description="LLC, Corporation, Partnership, etc.")
    historical_contract_count: int = Field(0, description="Total contracts retained involving this party")


class HindsightAgreementRecord(BaseModel):
    """Retained contract level metadata and state."""
    memory_id: str = Field(..., description="Unique Hindsight memory identifier")
    contract_id: str = Field(..., description="Unique contract identifier (e.g., CNT-2026-ACME-MSA)")
    document_hash: str = Field(..., description="SHA-256 hash of source document")
    title: str = Field(..., description="Contract title")
    contract_type: str = Field(..., description="MSA, SOW, NDA, DPA, Amendment, etc.")
    status: str = Field("active", description="active, superseded, expired, terminated")
    parties: List[str] = Field(..., description="Canonical names of contracting parties")
    effective_date: Optional[str] = Field(None, description="ISO-8601 YYYY-MM-DD")
    expiration_date: Optional[str] = Field(None, description="ISO-8601 YYYY-MM-DD")
    governing_law: Optional[str] = Field(None, description="Agreed governing jurisdiction")
    parent_contract_id: Optional[str] = Field(None, description="ID of governing MSA or master agreement")
    evidence: Optional[SourceEvidence] = Field(None, description="Grounding evidence for metadata")


class HindsightObservation(BaseModel):
    """Retained clause-level observation with exact quote and provenance."""
    observation_id: str = Field(..., description="Unique observation ID (e.g., OBS-ACME-LIAB-01)")
    contract_id: str = Field(..., description="Associated contract ID")
    category: str = Field(..., description="limitation_of_liability, indemnity, payment_terms, termination, etc.")
    clause_reference: Optional[str] = Field(None, description="e.g. 'Section 11.2'")
    quote: str = Field(..., description="Verbatim text quote from contract")
    normalized_summary: str = Field(..., description="Normalized semantic representation for comparison")
    is_active: bool = Field(True, description="False if superseded or amended by later agreement")
    superseded_by: Optional[str] = Field(None, description="Observation ID or Amendment ID that modified this")
    financial_value: Optional[float] = Field(None, description="Normalized dollar amount or liability cap if applicable")
    provenance: SourceEvidence = Field(..., description="Exact character offsets, page number, and source file")


class HindsightGraphEdge(BaseModel):
    """Relational edge linking contracts, clauses, and entities."""
    source_id: str = Field(..., description="Source node ID (contract_id, party_name, or observation_id)")
    target_id: str = Field(..., description="Target node ID")
    edge_type: EdgeType = Field(..., description="Relationship type")
    effective_date: Optional[str] = Field(None, description="Date relationship took effect")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context or amendment notes")


class HindsightRecallQuery(BaseModel):
    """Multi-strategy retrieval request to Hindsight."""
    query_text: str = Field(..., description="Semantic or keyword query text")
    party_names: List[str] = Field(default_factory=list, description="Filter or bias towards specific entities")
    contract_types: List[str] = Field(default_factory=list, description="Filter by contract category (e.g. ['MSA'])")
    categories: List[str] = Field(default_factory=list, description="Filter by clause category (e.g. ['limitation_of_liability'])")
    as_of_date: Optional[str] = Field(None, description="Point-in-time state query (YYYY-MM-DD)")
    include_superseded: bool = Field(False, description="Whether to include superseded/historical versions")
    search_modes: List[str] = Field(
        default=["bm25", "semantic", "graph", "temporal"],
        description="Parallel search arms to activate"
    )
    max_results: int = Field(5, description="Token budget cap for returned memories")


class HindsightRecallResult(BaseModel):
    """Ranked memory recall output with provenance."""
    memory_id: str
    category: MemoryCategory
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    contract_id: str
    content_summary: str
    verbatim_quote: Optional[str] = None
    source_file: Optional[str] = None
    section_reference: Optional[str] = None
    effective_date: Optional[str] = None
    is_superseded: bool = False


class CrossContractDelta(BaseModel):
    """Comparison result between two contracts or an amendment and base agreement."""
    counterparty: str
    base_contract_id: str
    target_contract_id: str
    delta_type: str = Field(..., description="AMENDMENT_CHANGE, SOW_MSA_DISCREPANCY, PRECEDENT_DEVIATION")
    clause_category: str
    base_clause_text: Optional[str] = None
    target_clause_text: str
    conflict_detected: bool = False
    conflict_explanation: Optional[str] = None
    precedence_override_found: bool = False


class HindsightIngestionPayload(BaseModel):
    """Gated payload ensuring only audited, verified findings enter Hindsight long-term memory."""
    contract_id: str
    agreement_record: HindsightAgreementRecord
    observations: List[HindsightObservation]
    graph_edges: List[HindsightGraphEdge]
    verification_report: ContractVerificationReport
    allow_unverified_draft: bool = Field(
        False, description="Strict safety gate: must be True only in explicit non-production sandbox mode"
    )

    def get_verified_observations(self) -> List[HindsightObservation]:
        """Filters observations to include only those confirmed as VERIFIED by Contract Verifier."""
        if self.allow_unverified_draft:
            return self.observations
        
        verified_finding_ids = {
            finding.finding_id
            for finding in self.verification_report.findings_audit
            if finding.status == VerificationStatus.VERIFIED
        }
        return [
            obs for obs in self.observations
            if obs.observation_id in verified_finding_ids
        ]


MemoryIngestionPayload = HindsightIngestionPayload

