"""Unit tests for Hindsight Cloud client integration and fallback handling."""

import os
import unittest
from unittest.mock import patch, MagicMock

from memory.hindsight_client import HindsightClient
from memory.memory_manager import MemoryManager
from schemas.memory_schema import (
    HindsightAgreementRecord,
    HindsightObservation,
    HindsightIngestionPayload,
    HindsightRecallQuery,
)
from schemas.contract_schema import SourceEvidence
from schemas.verification_schema import (
    VerificationStatus,
    FindingAudit,
    ContractVerificationReport,
)


class TestHindsightClient(unittest.TestCase):
    """Tests Hindsight Cloud REST client and graceful local fallback."""

    def test_unconfigured_client_graceful_fallback(self):
        """When HINDSIGHT_API_KEY is not set, client should fall back gracefully without exceptions."""
        client = HindsightClient(api_key=None)
        self.assertFalse(client.is_configured)

        # retain should return local_only status
        retain_res = client.retain("DOC-001", "Summary text", {"contract_id": "CNT-001"})
        self.assertEqual(retain_res["status"], "local_only")

        # recall should return empty list
        recall_res = client.recall("liability")
        self.assertEqual(recall_res, [])

        # reflect should return local_only status
        reflect_res = client.reflect("What are the liabilities?")
        self.assertEqual(reflect_res["status"], "local_only")

    @patch("urllib.request.urlopen")
    def test_configured_client_retain_and_recall(self, mock_urlopen):
        """When HINDSIGHT_API_KEY is provided, client should invoke REST API."""
        client = HindsightClient(
            api_key="mock_test_key_xyz",
            api_url="https://api.hindsight.test/v1",
            bank_id="test-bank",
        )
        self.assertTrue(client.is_configured)

        # Mock retain response
        mock_retain_response = MagicMock()
        mock_retain_response.read.return_value = b'{"status": "retained", "id": "OBS-MOCK-1"}'
        mock_retain_response.__enter__.return_value = mock_retain_response

        # Mock recall response
        mock_recall_response = MagicMock()
        mock_recall_response.read.return_value = (
            b'{"results": [{"document_id": "OBS-CLOUD-1", "content": "Trailing 12 month fees", "score": 0.95}]}'
        )
        mock_recall_response.__enter__.return_value = mock_recall_response

        # Test retain
        mock_urlopen.return_value = mock_retain_response
        res = client.retain("OBS-001", "Liability cap $1M", {"category": "liability"})
        self.assertEqual(res.get("status"), "retained")

        # Test recall
        mock_urlopen.return_value = mock_recall_response
        memories = client.recall("liability")
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["document_id"], "OBS-CLOUD-1")

    @patch("urllib.request.urlopen")
    def test_memory_manager_with_hindsight_client(self, mock_urlopen):
        """Verifies MemoryManager syncs to HindsightClient when configured."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "retained", "id": "OBS-001"}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = HindsightClient(api_key="valid_key")
        manager = MemoryManager(hindsight_client=client)

        evidence = SourceEvidence(
            verbatim_quote="Liability capped at $1M.",
            page_number=1,
            start_char_offset=0,
            end_char_offset=24,
            confidence_score=1.0,
        )
        agreement = HindsightAgreementRecord(
            memory_id="MEM-001",
            contract_id="CNT-001",
            document_hash="hash",
            title="MSA",
            contract_type="MSA",
            status="active",
            parties=["Company A"],
        )
        obs = HindsightObservation(
            observation_id="OBS-001",
            contract_id="CNT-001",
            category="liability",
            quote="Liability capped at $1M.",
            normalized_summary="Liability cap $1M.",
            provenance=evidence,
        )
        report = ContractVerificationReport(
            contract_id="CNT-001",
            document_hash="hash",
            total_findings_audited=1,
            verified_count=1,
            contradicted_count=0,
            unsupported_count=0,
            ambiguous_count=0,
            findings_audit=[
                FindingAudit(
                    finding_id="OBS-001",
                    category="Liability",
                    original_claim="Liability cap $1M",
                    submitted_evidence=evidence,
                    status=VerificationStatus.VERIFIED,
                    buffer_match_exact=True,
                    normalized_token_match_score=1.0,
                    surrounding_context_consistent=True,
                )
            ],
        )

        res = manager.retain_contract(
            HindsightIngestionPayload(
                contract_id="CNT-001",
                agreement_record=agreement,
                observations=[obs],
                graph_edges=[],
                verification_report=report,
            )
        )

        self.assertEqual(res["hindsight_cloud_synced"], 1)
        self.assertTrue(res["hindsight_cloud_configured"])


if __name__ == "__main__":
    unittest.main()
