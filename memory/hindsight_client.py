"""ContractIQ Hindsight Cloud Client.

Client integration for Hindsight Cloud (hindsight.vectorize.io) supporting:
- Persistent memory bank management
- retain(): Ingesting structured facts and observations with provenance
- recall(): Search across retained memories
- reflect(): High-level reasoning across multi-contract memory graphs
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any


class HindsightAPIError(Exception):
    """Exception raised for Hindsight Cloud API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        detail: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail


class RecallResult(list):
    """List of memory records retrieved from Hindsight with status and error metadata."""

    def __init__(
        self,
        items: Optional[List[Dict[str, Any]]] = None,
        status: str = "success",
        error: Optional[str] = None,
        status_code: Optional[int] = None,
        detail: Optional[str] = None,
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(items or [])
        self.status = status
        self.error = error
        self.status_code = status_code
        self.detail = detail
        self.raw_response = raw_response or {}

    @property
    def is_error(self) -> bool:
        return self.status == "error"

    def get(self, key: str, default: Any = None) -> Any:
        if key == "results":
            return list(self)
        if key == "status":
            return self.status
        if key == "error":
            return self.error
        if key == "status_code":
            return self.status_code
        if key == "detail":
            return self.detail
        return default


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
        self.api_key = api_key if api_key is not None else os.getenv("HINDSIGHT_API_KEY")
        self.api_url = (api_url or os.getenv("HINDSIGHT_API_URL") or self.DEFAULT_API_URL).rstrip("/")
        self.bank_id = bank_id or os.getenv("HINDSIGHT_BANK_ID", "contractiq-dev")
        self.timeout = timeout
        self.last_error: Optional[Dict[str, Any]] = None

    @property
    def is_configured(self) -> bool:
        """Returns True if Hindsight Cloud credentials are configured."""
        return bool(self.api_key and self.api_key.strip())

    def _build_url(self, endpoint_path: str, bank_id: Optional[str] = None) -> str:
        """Constructs full URL avoiding duplicate /v1 prefixes.
        
        Official endpoints:
          Retain:  POST /v1/default/banks/{bank_id}/memories
          Recall:  POST /v1/default/banks/{bank_id}/memories/recall
          Reflect: POST /v1/default/banks/{bank_id}/reflect
        """
        base = self.api_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        target_bank = bank_id or self.bank_id
        clean_path = endpoint_path.lstrip("/")
        return f"{base}/default/banks/{target_bank}/{clean_path}"

    def _headers(self) -> Dict[str, str]:
        """Builds HTTP headers for Hindsight Cloud requests."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ContractIQ-Agent/0.1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        return headers

    def retain(
        self,
        document_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        bank_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ingests verified contract facts and observations into Hindsight Cloud.
        
        Endpoint: POST /v1/default/banks/{bank_id}/memories
        Payload: {"items": [{"content": "...", "document_id": "..."}]}
        """
        if not self.is_configured:
            return {
                "status": "local_only",
                "message": "HINDSIGHT_API_KEY not configured; retained in local memory bank.",
                "document_id": document_id,
            }

        url = self._build_url("memories", bank_id=bank_id)

        # Preserve structured metadata within content
        enriched_content = content
        if metadata:
            meta_parts = []
            if metadata.get("category"):
                meta_parts.append(f"Category: {metadata['category']}")
            if metadata.get("clause_reference"):
                meta_parts.append(f"Clause: {metadata['clause_reference']}")
            if metadata.get("parties"):
                parties = metadata["parties"]
                parties_str = ", ".join(parties) if isinstance(parties, list) else str(parties)
                meta_parts.append(f"Parties: {parties_str}")
            if metadata.get("effective_date"):
                meta_parts.append(f"Effective: {metadata['effective_date']}")
            if metadata.get("quote"):
                meta_parts.append(f"Quote: \"{metadata['quote']}\"")
            if meta_parts:
                enriched_content = f"{content} | " + " | ".join(meta_parts)

        payload = {
            "items": [
                {
                    "content": enriched_content,
                    "document_id": str(document_id),
                }
            ]
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                res_body = response.read().decode("utf-8")
                res_data = json.loads(res_body) if res_body else {"status": "ok"}
                return res_data
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            err_dict = {
                "status": "error",
                "status_code": e.code,
                "error": f"Hindsight API HTTP error: {e.code} {e.reason}",
                "detail": error_body,
            }
            self.last_error = err_dict
            return err_dict
        except urllib.error.URLError as e:
            err_dict = {
                "status": "error",
                "error": f"Hindsight API connection failed: {e.reason}",
            }
            self.last_error = err_dict
            return err_dict
        except Exception as e:
            err_dict = {
                "status": "error",
                "error": f"Hindsight API request failed: {str(e)}",
            }
            self.last_error = err_dict
            return err_dict

    def recall(
        self,
        query: str,
        bank_id: Optional[str] = None,
        raise_for_status: bool = False,
    ) -> RecallResult:
        """Executes search on Hindsight Cloud.
        
        Endpoint: POST /v1/default/banks/{bank_id}/memories/recall
        Payload: {"query": "..."}
        
        Returns:
            RecallResult list containing memory items with error/status metadata.
        """
        if not self.is_configured:
            return RecallResult([], status="local_only")

        url = self._build_url("memories/recall", bank_id=bank_id)
        payload = {"query": str(query)}

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                res_body = response.read().decode("utf-8")
                res_data = json.loads(res_body) if res_body else {}
                results = res_data.get("results", [])
                return RecallResult(results, status="success", raw_response=res_data)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            err_msg = f"Hindsight API HTTP error: {e.code} {e.reason}"
            err_dict = {
                "status": "error",
                "status_code": e.code,
                "error": err_msg,
                "detail": error_body,
            }
            self.last_error = err_dict
            if raise_for_status:
                raise HindsightAPIError(err_msg, status_code=e.code, detail=error_body)
            return RecallResult([], status="error", error=err_msg, status_code=e.code, detail=error_body)
        except urllib.error.URLError as e:
            err_msg = f"Hindsight API connection failed: {e.reason}"
            err_dict = {"status": "error", "error": err_msg}
            self.last_error = err_dict
            if raise_for_status:
                raise HindsightAPIError(err_msg)
            return RecallResult([], status="error", error=err_msg)
        except Exception as e:
            err_msg = f"Hindsight API recall failed: {str(e)}"
            err_dict = {"status": "error", "error": err_msg}
            self.last_error = err_dict
            if raise_for_status:
                raise HindsightAPIError(err_msg)
            return RecallResult([], status="error", error=err_msg)

    def reflect(
        self,
        query: str,
        bank_id: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synthesizes high-level reasoning and cross-contract conclusions.
        
        Endpoint: POST /v1/default/banks/{bank_id}/reflect
        Payload: {"query": "..."}
        """
        if not self.is_configured:
            return {
                "status": "local_only",
                "summary": "Hindsight Cloud reflection requires HINDSIGHT_API_KEY. Using local delta engine.",
            }

        url = self._build_url("reflect", bank_id=bank_id)
        effective_query = str(query or prompt or "")
        payload = {"query": effective_query}

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                res_body = response.read().decode("utf-8")
                return json.loads(res_body) if res_body else {"status": "ok"}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            err_dict = {
                "status": "error",
                "status_code": e.code,
                "error": f"Hindsight API HTTP error: {e.code} {e.reason}",
                "detail": error_body,
            }
            self.last_error = err_dict
            return err_dict
        except urllib.error.URLError as e:
            err_dict = {
                "status": "error",
                "error": f"Hindsight API connection failed: {e.reason}",
            }
            self.last_error = err_dict
            return err_dict
        except Exception as e:
            err_dict = {
                "status": "error",
                "error": f"Hindsight reflect failed: {str(e)}",
            }
            self.last_error = err_dict
            return err_dict
