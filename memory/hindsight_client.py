"""ContractIQ Hindsight Cloud Client.

Client integration for Hindsight Cloud (hindsight.vectorize.io) supporting:
- Persistent memory bank management
- retain(): Ingesting structured facts and observations with provenance
- recall(): 4-way parallel search (semantic, keyword, graph, temporal)
- reflect(): High-level reasoning across multi-contract memory graphs
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any


class HindsightClient:
    """REST Client for Hindsight Cloud API with local fallback awareness."""

    DEFAULT_API_URL = "https://api.hindsight.vectorize.io/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        bank_id: Optional[str] = None,
        timeout: float = 10.0,
    ):
        """Initializes Hindsight Cloud client.
        
        Args:
            api_key: Hindsight Cloud API key (falls back to HINDSIGHT_API_KEY env var).
            api_url: Hindsight Cloud base URL (falls back to HINDSIGHT_API_URL or default).
            bank_id: Default memory bank ID for ContractIQ (falls back to HINDSIGHT_BANK_ID).
            timeout: HTTP request timeout in seconds.
        """
        self.api_key = api_key or os.getenv("HINDSIGHT_API_KEY")
        self.api_url = (api_url or os.getenv("HINDSIGHT_API_URL") or self.DEFAULT_API_URL).rstrip("/")
        self.bank_id = bank_id or os.getenv("HINDSIGHT_BANK_ID", "contractiq-memory")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Returns True if Hindsight Cloud credentials are configured."""
        return bool(self.api_key and self.api_key.strip())

    def _headers(self) -> Dict[str, str]:
        """Builds HTTP headers for Hindsight Cloud requests."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ContractIQ-Agent/0.1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def retain(
        self,
        document_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        bank_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ingests verified contract facts and observations into Hindsight Cloud.
        
        Args:
            document_id: Unique contract/observation ID.
            content: Textual content or normalized summary to retain.
            metadata: Structured metadata (parties, dates, clause citations, provenance).
            bank_id: Target memory bank.
            
        Returns:
            API response dictionary.
        """
        if not self.is_configured:
            return {
                "status": "local_only",
                "message": "HINDSIGHT_API_KEY not configured; retained in local memory bank.",
                "document_id": document_id,
            }

        target_bank = bank_id or self.bank_id
        url = f"{self.api_url}/banks/{target_bank}/retain"
        payload = {
            "document_id": document_id,
            "content": content,
            "metadata": metadata or {},
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            return {
                "status": "error",
                "status_code": e.code,
                "error": f"Hindsight API HTTP error: {e.reason}",
                "detail": error_body,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Hindsight API connection failed: {str(e)}",
            }

    def recall(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        bank_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Executes multi-strategy search on Hindsight Cloud.
        
        Args:
            query: Search query text.
            top_k: Maximum number of memories to return.
            filters: Optional metadata filters (e.g. party, category).
            bank_id: Target memory bank.
            
        Returns:
            List of memory records retrieved from Hindsight.
        """
        if not self.is_configured:
            return []

        target_bank = bank_id or self.bank_id
        url = f"{self.api_url}/banks/{target_bank}/recall"
        payload = {
            "query": query,
            "top_k": top_k,
            "filters": filters or {},
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                return res_data.get("results", [])
        except Exception as e:
            return []

    def reflect(
        self,
        prompt: str,
        bank_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synthesizes high-level reasoning and cross-contract conclusions.
        
        Args:
            prompt: Question or reasoning prompt across memories.
            bank_id: Target memory bank.
            
        Returns:
            Synthesized reflection response.
        """
        if not self.is_configured:
            return {
                "status": "local_only",
                "summary": "Hindsight Cloud reflection requires HINDSIGHT_API_KEY. Using local delta engine.",
            }

        target_bank = bank_id or self.bank_id
        url = f"{self.api_url}/banks/{target_bank}/reflect"
        payload = {"prompt": prompt}

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            return {
                "status": "error",
                "error": f"Hindsight reflect failed: {str(e)}",
            }
