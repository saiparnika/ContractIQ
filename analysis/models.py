"""ContractIQ Analysis and Risk Models."""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from schemas.contract_schema import SourceEvidence


class RiskSeverity(str, Enum):
    CRITICAL = "CRITICAL"   # High legal or financial hazard (e.g., uncapped liability, non-standard indemnity)
    HIGH = "HIGH"           # Significant operational or compliance risk
    MEDIUM = "MEDIUM"       # Moderate exposure requiring business review
    LOW = "LOW"             # Minor advisory or informational note


class RiskCategory(str, Enum):
    LIABILITY = "liability"
    TERMINATION = "termination"
    PAYMENT = "payment"
    CONFIDENTIALITY = "confidentiality"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    COMPLIANCE = "compliance"
    GOVERNANCE = "governance"


class ContractRisk(BaseModel):
    """Identified contractual risk with source grounding."""
    risk_id: str = Field(..., description="Unique risk identifier (e.g. RISK-LIAB-01)")
    category: RiskCategory
    severity: RiskSeverity
    title: str = Field(..., description="Short summary of the risk")
    description: str = Field(..., description="Detailed explanation of the legal or commercial exposure")
    mitigation_recommendation: str = Field(..., description="Recommended negotiating position or contract amendment")
    evidence: Optional[SourceEvidence] = Field(None, description="Grounded excerpt triggering the risk")


class RiskAssessmentReport(BaseModel):
    """Comprehensive risk assessment report for an analyzed contract."""
    contract_id: str
    overall_risk_score: float = Field(..., ge=0.0, le=100.0, description="Composite score (0=clean, 100=extreme risk)")
    total_risks_identified: int = Field(0, ge=0)
    critical_count: int = Field(0, ge=0)
    high_count: int = Field(0, ge=0)
    medium_count: int = Field(0, ge=0)
    low_count: int = Field(0, ge=0)
    risks: List[ContractRisk] = Field(default_factory=list)
    summary: str = Field(..., description="Executive risk summary")
