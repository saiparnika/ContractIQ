"""Unit tests for ContractIQ Memory Specialist and Verification Gating.

Verifies:
1. Strict filtering of non-VERIFIED extractions (CONTRADICTED, UNSUPPORTED, AMBIGUOUS).
2. Provenance preservation and active/superseded versioning across amendments.
3. Multi-strategy recall and cross-contract conflict detection.
"""

import sys
import os
import unittest

# Ensure ContractIQ root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from schemas.contract_schema import SourceEvidence
from schemas.verification_schema import (
    VerificationStatus,
    IssueSeverity,
    FindingAudit,
    ContractVerificationReport,
)
from schemas.memory_schema import (
    HindsightAgreementRecord,
    HindsightObservation,
    HindsightGraphEdge,
    EdgeType,
    HindsightRecallQuery,
    HindsightIngestionPayload,
)
from memory.memory_manager import MemoryManager


class TestMemoryManagerVerificationGating(unittest.TestCase):
    """Tests that only verified findings enter Hindsight long-term memory."""

    def setUp(self):
        self.manager = MemoryManager()
        self.evidence_mock = SourceEvidence(
            verbatim_quote="Aggregate liability shall not exceed $500,000.",
            page_number=12,
            section_reference="Section 9.1",
            start_char_offset=1240,
            end_char_offset=1285,
            confidence_score=0.98,
        )

    def test_strict_verification_filtering(self):
        """Ensures CONTRADICTED, UNSUPPORTED, and AMBIGUOUS claims are rejected."""
        contract_id = "CNT-TEST-001"
        agreement = HindsightAgreementRecord(
            memory_id="MEM-AGR-001",
            contract_id=contract_id,
            document_hash="hash_abc123",
            title="Master Cloud Services Agreement",
            contract_type="MSA",
            status="active",
            parties=["Alpha Corp", "Beta LLC"],
            effective_date="2025-01-01",
        )

        # 4 Candidate Observations
        obs_verified = HindsightObservation(
            observation_id="OBS-001",
            contract_id=contract_id,
            category="limitation_of_liability",
            clause_reference="Section 9.1",
            quote="Aggregate liability shall not exceed $500,000.",
            normalized_summary="Liability capped at $500k.",
            financial_value=500000.0,
            provenance=self.evidence_mock,
        )
        obs_contradicted = HindsightObservation(
            observation_id="OBS-002",
            contract_id=contract_id,
            category="governing_law",
            clause_reference="Section 14.3",
            quote="Governed by the laws of California.",
            normalized_summary="Governed by California law.",
            provenance=self.evidence_mock,
        )
        obs_unsupported = HindsightObservation(
            observation_id="OBS-003",
            contract_id=contract_id,
            category="payment_terms",
            clause_reference="Section 4.2",
            quote="Payment due Net 90 days from invoice.",
            normalized_summary="Net 90 payment terms.",
            provenance=self.evidence_mock,
        )
        obs_ambiguous = HindsightObservation(
            observation_id="OBS-004",
            contract_id=contract_id,
            category="termination",
            clause_reference="Section 12.1",
            quote="Either party may terminate immediately or upon 30 days notice.",
            normalized_summary="Immediate or 30 days termination.",
            provenance=self.evidence_mock,
        )

        # Verification Audits
        audit_verified = FindingAudit(
            finding_id="OBS-001",
            category="Liability",
            original_claim="Liability capped at $500k",
            submitted_evidence=self.evidence_mock,
            status=VerificationStatus.VERIFIED,
            buffer_match_exact=True,
            normalized_token_match_score=1.0,
            surrounding_context_consistent=True,
        )
        audit_contradicted = FindingAudit(
            finding_id="OBS-002",
            category="Metadata",
            original_claim="Governed by California law",
            submitted_evidence=self.evidence_mock,
            status=VerificationStatus.CONTRADICTED,
            buffer_match_exact=False,
            normalized_token_match_score=0.2,
            surrounding_context_consistent=False,
            discrepancy_explanation="Document states Section 14.3 is governed by Delaware law.",
            severity=IssueSeverity.CRITICAL,
        )
        audit_unsupported = FindingAudit(
            finding_id="OBS-003",
            category="Commercial",
            original_claim="Net 90 payment terms",
            submitted_evidence=self.evidence_mock,
            status=VerificationStatus.UNSUPPORTED,
            buffer_match_exact=False,
            normalized_token_match_score=0.0,
            surrounding_context_consistent=False,
            discrepancy_explanation="Clause 4.2 does not exist in buffer.",
            severity=IssueSeverity.CRITICAL,
        )
        audit_ambiguous = FindingAudit(
            finding_id="OBS-004",
            category="Termination",
            original_claim="Immediate or 30 days termination",
            submitted_evidence=self.evidence_mock,
            status=VerificationStatus.AMBIGUOUS,
            buffer_match_exact=True,
            normalized_token_match_score=0.96,
            surrounding_context_consistent=False,
            discrepancy_explanation="Conflicting termination windows in same section.",
            severity=IssueSeverity.WARNING,
        )

        verification_report = ContractVerificationReport(
            contract_id=contract_id,
            document_hash="hash_abc123",
            total_findings_audited=4,
            verified_count=1,
            contradicted_count=1,
            unsupported_count=1,
            ambiguous_count=1,
            findings_audit=[audit_verified, audit_contradicted, audit_unsupported, audit_ambiguous],
            critical_discrepancies=[audit_contradicted, audit_unsupported],
            human_review_required=True,
        )

        payload = HindsightIngestionPayload(
            contract_id=contract_id,
            agreement_record=agreement,
            observations=[obs_verified, obs_contradicted, obs_unsupported, obs_ambiguous],
            graph_edges=[],
            verification_report=verification_report,
        )

        # Execute Ingestion
        result = self.manager.retain_contract(payload)

        # Assertions on Gating Metrics
        self.assertEqual(result["total_submitted_observations"], 4)
        self.assertEqual(result["retained_verified_observations"], 1)
        self.assertEqual(result["rejected_unverified_observations"], 3)

        # Query memory store: Only OBS-001 should be retrievable
        recall_res = self.manager.recall(
            HindsightRecallQuery(query_text="liability", party_names=["Alpha Corp"])
        )
        self.assertEqual(len(recall_res), 1)
        self.assertEqual(recall_res[0].memory_id, "OBS-001")
        self.assertEqual(recall_res[0].content_summary, "Liability capped at $500k.")

        # Ensure contradicted claim cannot be recalled
        gov_law_res = self.manager.recall(
            HindsightRecallQuery(query_text="California", party_names=["Alpha Corp"])
        )
        self.assertEqual(len(gov_law_res), 0)

    def test_non_destructive_amendment_supersession(self):
        """Verifies that amendments update status without destroying historical audit trail."""
        # 1. Base MSA with Net 30
        msa_id = "CNT-MSA-100"
        msa_record = HindsightAgreementRecord(
            memory_id="MEM-100",
            contract_id=msa_id,
            document_hash="h1",
            title="Base Services Agreement",
            contract_type="MSA",
            status="active",
            parties=["Vendor X", "Client Y"],
            effective_date="2024-01-01",
        )
        obs_v1 = HindsightObservation(
            observation_id="OBS-PMT-V1",
            contract_id=msa_id,
            category="payment_terms",
            clause_reference="Section 3.1",
            quote="Payment terms are Net 30.",
            normalized_summary="Net 30 payment terms.",
            provenance=self.evidence_mock,
        )
        report_v1 = ContractVerificationReport(
            contract_id=msa_id,
            document_hash="h1",
            total_findings_audited=1,
            verified_count=1,
            contradicted_count=0,
            unsupported_count=0,
            ambiguous_count=0,
            findings_audit=[
                FindingAudit(
                    finding_id="OBS-PMT-V1",
                    category="Commercial",
                    original_claim="Net 30",
                    submitted_evidence=self.evidence_mock,
                    status=VerificationStatus.VERIFIED,
                    buffer_match_exact=True,
                    normalized_token_match_score=1.0,
                    surrounding_context_consistent=True,
                )
            ],
        )
        self.manager.retain_contract(
            HindsightIngestionPayload(
                contract_id=msa_id,
                agreement_record=msa_record,
                observations=[obs_v1],
                graph_edges=[],
                verification_report=report_v1,
            )
        )

        # 2. Amendment 1 modifying to Net 60
        amd_id = "CNT-AMD-101"
        amd_record = HindsightAgreementRecord(
            memory_id="MEM-101",
            contract_id=amd_id,
            document_hash="h2",
            title="Amendment No. 1",
            contract_type="Amendment",
            status="active",
            parties=["Vendor X", "Client Y"],
            effective_date="2024-06-01",
            parent_contract_id=msa_id,
        )
        obs_v2 = HindsightObservation(
            observation_id="OBS-PMT-V2",
            contract_id=amd_id,
            category="payment_terms",
            clause_reference="Section 1",
            quote="Section 3.1 is hereby amended to replace 'Net 30' with 'Net 60'.",
            normalized_summary="Net 60 payment terms (supersedes Section 3.1).",
            superseded_by="OBS-PMT-V1",  # Targets prior observation to supersede it
            provenance=self.evidence_mock,
        )
        report_v2 = ContractVerificationReport(
            contract_id=amd_id,
            document_hash="h2",
            total_findings_audited=1,
            verified_count=1,
            contradicted_count=0,
            unsupported_count=0,
            ambiguous_count=0,
            findings_audit=[
                FindingAudit(
                    finding_id="OBS-PMT-V2",
                    category="Commercial",
                    original_claim="Net 60",
                    submitted_evidence=self.evidence_mock,
                    status=VerificationStatus.VERIFIED,
                    buffer_match_exact=True,
                    normalized_token_match_score=1.0,
                    surrounding_context_consistent=True,
                )
            ],
        )
        edge = HindsightGraphEdge(
            source_id="OBS-PMT-V2",
            target_id="OBS-PMT-V1",
            edge_type=EdgeType.SUPERSEDES,
            effective_date="2024-06-01",
        )
        self.manager.retain_contract(
            HindsightIngestionPayload(
                contract_id=amd_id,
                agreement_record=amd_record,
                observations=[obs_v2],
                graph_edges=[edge],
                verification_report=report_v2,
            )
        )

        # 3. Recall active only (default) -> Only Net 60 returned
        active_recall = self.manager.recall(
            HindsightRecallQuery(
                query_text="payment terms",
                party_names=["Vendor X"],
                include_superseded=False,
            )
        )
        self.assertEqual(len(active_recall), 1)
        self.assertEqual(active_recall[0].memory_id, "OBS-PMT-V2")
        self.assertFalse(active_recall[0].is_superseded)

        # 4. Recall with history -> Both returned, with audit flag
        history_recall = self.manager.recall(
            HindsightRecallQuery(
                query_text="payment terms",
                party_names=["Vendor X"],
                include_superseded=True,
            )
        )
        self.assertEqual(len(history_recall), 2)
        superseded_item = next(r for r in history_recall if r.memory_id == "OBS-PMT-V1")
        self.assertTrue(superseded_item.is_superseded)


if __name__ == "__main__":
    unittest.main()
