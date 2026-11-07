"""Unit tests for Hindsight Cloud client integration, REST endpoints, and fallback handling."""

import os
import json
import io
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

from memory.hindsight_client import HindsightClient, HindsightAPIError, RecallResult
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
    """Tests Hindsight Cloud REST client, URL builder, auth headers, and local fallback."""

    @patch.dict(os.environ, {"HINDSIGHT_API_KEY": ""}, clear=False)
    def test_unconfigured_client_graceful_fallback(self):
        """When HINDSIGHT_API_KEY is not set, client should fall back gracefully without exceptions."""
        client = HindsightClient(api_key=None)
        self.assertFalse(client.is_configured)

        # retain should return local_only status
        retain_res = client.retain("DOC-001", "Summary text", {"contract_id": "CNT-001"})
        self.assertEqual(retain_res["status"], "local_only")

        # recall should return empty RecallResult with local_only status
        recall_res = client.recall("liability")
        self.assertEqual(recall_res, [])
        self.assertEqual(recall_res.status, "local_only")
        self.assertFalse(recall_res.is_error)

        # reflect should return local_only status
        reflect_res = client.reflect("What are the liabilities?")
        self.assertEqual(reflect_res["status"], "local_only")

    def test_url_construction_avoids_duplicate_v1(self):
        """Tests that URL construction handles base URLs with and without trailing /v1 cleanly."""
        # Configured URL already has /v1
        c1 = HindsightClient(api_key="mock", api_url="https://api.hindsight.vectorize.io/v1", bank_id="dev-bank")
        self.assertEqual(
            c1._build_url("memories"),
            "https://api.hindsight.vectorize.io/v1/default/banks/dev-bank/memories",
        )
        self.assertEqual(
            c1._build_url("memories/recall"),
            "https://api.hindsight.vectorize.io/v1/default/banks/dev-bank/memories/recall",
        )
        self.assertEqual(
            c1._build_url("reflect"),
            "https://api.hindsight.vectorize.io/v1/default/banks/dev-bank/reflect",
        )

        # Configured URL has trailing slash after /v1/
        c2 = HindsightClient(api_key="mock", api_url="https://api.hindsight.vectorize.io/v1/", bank_id="dev-bank")
        self.assertEqual(
            c2._build_url("memories"),
            "https://api.hindsight.vectorize.io/v1/default/banks/dev-bank/memories",
        )

        # Configured URL lacks /v1
        c3 = HindsightClient(api_key="mock", api_url="https://api.hindsight.vectorize.io", bank_id="dev-bank")
        self.assertEqual(
            c3._build_url("memories"),
            "https://api.hindsight.vectorize.io/v1/default/banks/dev-bank/memories",
        )

    @patch("urllib.request.urlopen")
    def test_retain_documented_payload_endpoint_and_auth(self, mock_urlopen):
        """Tests retain() sends the documented payload and correct Authorization header."""
        client = HindsightClient(
            api_key="test_secret_token_123",
            api_url="https://api.hindsight.test/v1",
            bank_id="contractiq-dev",
        )
        self.assertTrue(client.is_configured)

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"items": [{"id": "item-101", "document_id": "OBS-001"}]}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        res = client.retain(
            document_id="OBS-001",
            content="Payment terms Net 30",
            metadata={"category": "commercial", "quote": "Within 30 days", "parties": ["A", "B"]},
        )

        self.assertIn("items", res)
        self.assertEqual(res["items"][0]["document_id"], "OBS-001")

        # Verify urllib.request call details
        req_arg = mock_urlopen.call_args[0][0]
        self.assertEqual(
            req_arg.full_url,
            "https://api.hindsight.test/v1/default/banks/contractiq-dev/memories",
        )
        self.assertEqual(req_arg.get_method(), "POST")
        self.assertEqual(req_arg.headers["Authorization"], "Bearer test_secret_token_123")
        self.assertEqual(req_arg.headers["Content-type"], "application/json")

        # Verify payload matches documented schema {"items": [{"content": ..., "document_id": ...}]}
        body_sent = json.loads(req_arg.data.decode("utf-8"))
        self.assertIn("items", body_sent)
        self.assertEqual(len(body_sent["items"]), 1)
        item = body_sent["items"][0]
        self.assertEqual(item["document_id"], "OBS-001")
        self.assertIn("Payment terms Net 30", item["content"])
        self.assertIn("Category: commercial", item["content"])
        self.assertIn("Within 30 days", item["content"])
        # Ensure unsupported top-level fields are NOT present
        self.assertNotIn("metadata", body_sent)
        self.assertNotIn("content", body_sent)

    @patch("urllib.request.urlopen")
    def test_retain_http_error_reporting(self, mock_urlopen):
        """Tests retain() accurately captures and reports HTTP errors."""
        client = HindsightClient(
            api_key="invalid_token",
            api_url="https://api.hindsight.test/v1",
            bank_id="contractiq-dev",
        )

        fp = io.BytesIO(b'{"error": "Unauthorized", "message": "Invalid API key"}')
        http_error = urllib.error.HTTPError(
            url="https://api.hindsight.test/v1/default/banks/contractiq-dev/memories",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=fp,
        )
        mock_urlopen.side_effect = http_error

        res = client.retain("OBS-001", "Summary content")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["status_code"], 401)
        self.assertIn("401", res["error"])
        self.assertIn("Invalid API key", res["detail"])
        self.assertIsNotNone(client.last_error)

    @patch("urllib.request.urlopen")
    def test_recall_documented_payload_endpoint_and_auth(self, mock_urlopen):
        """Tests recall() sends {"query": "..."} to /memories/recall and parses results."""
        client = HindsightClient(
            api_key="test_secret_token_123",
            api_url="https://api.hindsight.test/v1",
            bank_id="contractiq-dev",
        )

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "results": [
                {
                    "document_id": "OBS-CLOUD-1",
                    "content": "Liability cap $1,000,000",
                    "score": 0.96,
                }
            ]
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        memories = client.recall("liability limitation")

        # Verify parsed results
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["document_id"], "OBS-CLOUD-1")
        self.assertEqual(memories[0]["content"], "Liability cap $1,000,000")
        self.assertEqual(memories.status, "success")
        self.assertFalse(memories.is_error)

        # Verify request details
        req_arg = mock_urlopen.call_args[0][0]
        self.assertEqual(
            req_arg.full_url,
            "https://api.hindsight.test/v1/default/banks/contractiq-dev/memories/recall",
        )
        self.assertEqual(req_arg.headers["Authorization"], "Bearer test_secret_token_123")
        body_sent = json.loads(req_arg.data.decode("utf-8"))
        self.assertEqual(body_sent, {"query": "liability limitation"})

    @patch("urllib.request.urlopen")
    def test_recall_http_error_exposed_not_hidden(self, mock_urlopen):
        """Tests recall() exposes HTTP error details and does NOT silently hide errors with []."""
        client = HindsightClient(
            api_key="bad_token",
            api_url="https://api.hindsight.test/v1",
            bank_id="contractiq-dev",
        )

        def make_http_error(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="https://api.hindsight.test/v1/default/banks/contractiq-dev/memories/recall",
                code=404,
                msg="Not Found",
                hdrs={},
                fp=io.BytesIO(b'{"detail": "Bank not found"}'),
            )

        mock_urlopen.side_effect = make_http_error

        # Default behavior: returns RecallResult with is_error=True and error attributes
        memories = client.recall("liability")
        self.assertTrue(memories.is_error)
        self.assertEqual(memories.status, "error")
        self.assertEqual(memories.status_code, 404)
        self.assertIn("404", memories.error)
        self.assertIn("Bank not found", memories.detail)

        # Client last_error is also populated
        self.assertIsNotNone(client.last_error)
        self.assertEqual(client.last_error["status_code"], 404)

        # raise_for_status=True raises HindsightAPIError
        with self.assertRaises(HindsightAPIError) as ctx:
            client.recall("liability", raise_for_status=True)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("Bank not found", ctx.exception.detail)

    @patch("urllib.request.urlopen")
    def test_reflect_documented_payload_endpoint_and_auth(self, mock_urlopen):
        """Tests reflect() sends {"query": "..."} to /reflect and parses response."""
        client = HindsightClient(
            api_key="test_secret_token_123",
            api_url="https://api.hindsight.test/v1",
            bank_id="contractiq-dev",
        )

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "summary": "Both agreements use Delaware law and Net 30 payment terms.",
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        res = client.reflect(query="Compare governing laws")

        self.assertIn("summary", res)
        req_arg = mock_urlopen.call_args[0][0]
        self.assertEqual(
            req_arg.full_url,
            "https://api.hindsight.test/v1/default/banks/contractiq-dev/reflect",
        )
        self.assertEqual(req_arg.headers["Authorization"], "Bearer test_secret_token_123")
        body_sent = json.loads(req_arg.data.decode("utf-8"))
        self.assertEqual(body_sent, {"query": "Compare governing laws"})

    @patch("urllib.request.urlopen")
    def test_memory_manager_gated_cloud_sync_counts(self, mock_urlopen):
        """Verifies MemoryManager syncs only verified observations and counts successful cloud retains."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"items": [{"id": "item-1"}]}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        client = HindsightClient(
            api_key="valid_key",
            api_url="https://api.hindsight.test/v1",
            bank_id="dev-bank",
        )
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
        obs_verified = HindsightObservation(
            observation_id="OBS-VERIFIED-1",
            contract_id="CNT-001",
            category="liability",
            quote="Liability capped at $1M.",
            normalized_summary="Liability cap $1M.",
            provenance=evidence,
        )
        obs_unverified = HindsightObservation(
            observation_id="OBS-UNVERIFIED-2",
            contract_id="CNT-001",
            category="termination",
            quote="Immediate termination.",
            normalized_summary="Immediate termination.",
            provenance=evidence,
        )
        report = ContractVerificationReport(
            contract_id="CNT-001",
            document_hash="hash",
            total_findings_audited=2,
            verified_count=1,
            contradicted_count=0,
            unsupported_count=1,
            ambiguous_count=0,
            findings_audit=[
                FindingAudit(
                    finding_id="OBS-VERIFIED-1",
                    category="Liability",
                    original_claim="Liability cap $1M",
                    submitted_evidence=evidence,
                    status=VerificationStatus.VERIFIED,
                    buffer_match_exact=True,
                    normalized_token_match_score=1.0,
                    surrounding_context_consistent=True,
                ),
                FindingAudit(
                    finding_id="OBS-UNVERIFIED-2",
                    category="Termination",
                    original_claim="Immediate termination",
                    submitted_evidence=evidence,
                    status=VerificationStatus.UNSUPPORTED,
                    buffer_match_exact=False,
                    normalized_token_match_score=0.0,
                    surrounding_context_consistent=False,
                ),
            ],
        )

        res = manager.retain_contract(
            HindsightIngestionPayload(
                contract_id="CNT-001",
                agreement_record=agreement,
                observations=[obs_verified, obs_unverified],
                graph_edges=[],
                verification_report=report,
            )
        )

        # Strict gating: only OBS-VERIFIED-1 was retained and synced
        self.assertEqual(res["retained_verified_observations"], 1)
        self.assertEqual(res["rejected_unverified_observations"], 1)
        self.assertEqual(res["hindsight_cloud_synced"], 1)
        self.assertEqual(res["hindsight_cloud_sync_status"], "synced")
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_memory_manager_reports_cloud_retain_failure_not_misleading_success(self, mock_urlopen):
        """Verifies that if Hindsight Cloud returns an error, the manager reports failure accurately."""
        fp = io.BytesIO(b'{"message": "Rate limit exceeded"}')
        http_error = urllib.error.HTTPError(
            url="https://api.hindsight.test/v1/default/banks/dev-bank/memories",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=fp,
        )
        mock_urlopen.side_effect = http_error

        client = HindsightClient(
            api_key="valid_key",
            api_url="https://api.hindsight.test/v1",
            bank_id="dev-bank",
        )
        manager = MemoryManager(hindsight_client=client)

        evidence = SourceEvidence(
            verbatim_quote="Payment due Net 30.",
            page_number=1,
            start_char_offset=0,
            end_char_offset=19,
            confidence_score=1.0,
        )
        agreement = HindsightAgreementRecord(
            memory_id="MEM-002",
            contract_id="CNT-002",
            document_hash="hash2",
            title="MSA",
            contract_type="MSA",
            status="active",
            parties=["Party A"],
        )
        obs = HindsightObservation(
            observation_id="OBS-COMM-001",
            contract_id="CNT-002",
            category="commercial",
            quote="Payment due Net 30.",
            normalized_summary="Net 30 terms.",
            provenance=evidence,
        )
        report = ContractVerificationReport(
            contract_id="CNT-002",
            document_hash="hash2",
            total_findings_audited=1,
            verified_count=1,
            contradicted_count=0,
            unsupported_count=0,
            ambiguous_count=0,
            findings_audit=[
                FindingAudit(
                    finding_id="OBS-COMM-001",
                    category="Commercial",
                    original_claim="Payment due Net 30",
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
                contract_id="CNT-002",
                agreement_record=agreement,
                observations=[obs],
                graph_edges=[],
                verification_report=report,
            )
        )

        # Local retention succeeded, but Cloud sync FAILED
        self.assertEqual(res["retained_verified_observations"], 1)
        self.assertEqual(res["hindsight_cloud_synced"], 0)  # Must NOT count as cloud synced!
        self.assertEqual(res["hindsight_cloud_sync_status"], "failed")
        self.assertEqual(len(res["hindsight_cloud_errors"]), 1)
        self.assertEqual(res["hindsight_cloud_errors"][0]["status_code"], 429)


if __name__ == "__main__":
    unittest.main()
