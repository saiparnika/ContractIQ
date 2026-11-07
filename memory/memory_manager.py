"""ContractIQ Memory Manager.

Implements long-term memory operations using Hindsight persistent memory concepts:
1. Retaining verified contract facts and observations with provenance.
2. Multi-strategy recall across counterparties, clause categories, and timeline states.
3. Cross-contract term comparison and non-destructive amendment tracking.
"""

from typing import Dict, List, Optional, Any, Set
from datetime import datetime
import difflib

from schemas.contract_schema import SourceEvidence
from schemas.verification_schema import VerificationStatus, ContractVerificationReport
from schemas.memory_schema import (
    MemoryCategory,
    EdgeType,
    HindsightPartyEntity,
    HindsightAgreementRecord,
    HindsightObservation,
    HindsightGraphEdge,
    HindsightRecallQuery,
    HindsightRecallResult,
    CrossContractDelta,
    HindsightIngestionPayload,
)


from .hindsight_client import HindsightClient


class MemoryManager:
    """Manages long-term contract intelligence, provenance tracking, and cross-contract recall."""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        hindsight_client: Optional[HindsightClient] = None,
    ):
        """Initializes memory stores.
        
        Args:
            storage_path: Optional path for persistent storage or cloud backend config.
            hindsight_client: Optional configured HindsightClient for Hindsight Cloud.
        """
        self.storage_path = storage_path
        self.hindsight_client = hindsight_client or HindsightClient()
        self._agreements: Dict[str, HindsightAgreementRecord] = {}
        self._observations: Dict[str, HindsightObservation] = {}
        self._parties: Dict[str, HindsightPartyEntity] = {}
        self._graph_edges: List[HindsightGraphEdge] = []

    def retain_contract(self, payload: HindsightIngestionPayload) -> Dict[str, Any]:
        """Ingests and retains a contract after verification gating.
        
        Enforces that only observations verified by the Contract Verifier
        (status == VERIFIED) are retained in long-term memory.
        
        Args:
            payload: HindsightIngestionPayload containing agreement, findings, and verification audit.
            
        Returns:
            Dictionary summarizing retained facts and filtered rejections.
        """
        contract_id = payload.contract_id
        agreement = payload.agreement_record

        # 1. Retain Agreement Record
        self._agreements[contract_id] = agreement

        # 2. Update Party Profiles & Entities
        for party_name in agreement.parties:
            canonical = party_name.strip()
            if canonical not in self._parties:
                self._parties[canonical] = HindsightPartyEntity(
                    canonical_name=canonical,
                    historical_contract_count=1
                )
            else:
                self._parties[canonical].historical_contract_count += 1

        # 3. Filter and Retain Verified Observations
        verified_observations = payload.get_verified_observations()
        retained_obs_ids = []
        superseded_count = 0

        for obs in verified_observations:
            # Handle supersession links if an amendment modifies an older observation
            if obs.superseded_by and obs.superseded_by in self._observations:
                prior_obs = self._observations[obs.superseded_by]
                prior_obs.is_active = False
                prior_obs.superseded_by = obs.observation_id
                superseded_count += 1

            self._observations[obs.observation_id] = obs
            retained_obs_ids.append(obs.observation_id)

        # 4. Retain Graph & Hierarchy Edges
        retained_edges = 0
        for edge in payload.graph_edges:
            self._graph_edges.append(edge)
            retained_edges += 1

        # 5. Sync to Hindsight Cloud if configured
        cloud_retained_count = 0
        if self.hindsight_client.is_configured:
            for obs in verified_observations:
                cloud_res = self.hindsight_client.retain(
                    document_id=obs.observation_id,
                    content=obs.normalized_summary,
                    metadata={
                        "contract_id": contract_id,
                        "category": obs.category,
                        "clause_reference": obs.clause_reference,
                        "parties": agreement.parties,
                        "effective_date": agreement.effective_date,
                        "quote": obs.quote,
                    },
                )
                if cloud_res.get("status") != "error":
                    cloud_retained_count += 1

        total_submitted = len(payload.observations)
        rejected_count = total_submitted - len(verified_observations)

        return {
            "status": "success",
            "contract_id": contract_id,
            "retained_agreement": agreement.title,
            "total_submitted_observations": total_submitted,
            "retained_verified_observations": len(retained_obs_ids),
            "rejected_unverified_observations": rejected_count,
            "superseded_observations_updated": superseded_count,
            "graph_edges_stored": retained_edges,
            "hindsight_cloud_synced": cloud_retained_count,
            "hindsight_cloud_configured": self.hindsight_client.is_configured,
        }

    def recall(self, query: HindsightRecallQuery) -> List[HindsightRecallResult]:
        """Executes multi-strategy search over retained contract memory.
        
        Leverages keyword, semantic/category, and temporal filtering to return
        relevance-ranked memories within the requested token budget.
        
        Args:
            query: HindsightRecallQuery containing search criteria.
            
        Returns:
            List of HindsightRecallResult ranked by relevance.
        """
        results: List[HindsightRecallResult] = []
        query_text_lower = query.query_text.lower().strip()
        target_parties_lower = [p.lower() for p in query.party_names]

        for obs_id, obs in self._observations.items():
            # Filter superseded unless explicitly requested
            if not query.include_superseded and not obs.is_active:
                continue

            # Filter by clause category if specified
            if query.categories and obs.category not in query.categories:
                continue

            # Check associated agreement
            agreement = self._agreements.get(obs.contract_id)
            if not agreement:
                continue

            # Filter by contract type if specified
            if query.contract_types and agreement.contract_type not in query.contract_types:
                continue

            # Filter by party names if specified
            if target_parties_lower:
                agr_parties_lower = [p.lower() for p in agreement.parties]
                party_match = any(tp in ap or ap in tp for tp in target_parties_lower for ap in agr_parties_lower)
                if not party_match:
                    continue

            # Compute relevance score based on keyword & semantic overlap
            obs_text = f"{obs.category} {obs.normalized_summary} {obs.quote} {obs.clause_reference or ''}".lower()
            
            # Simple lexical overlap scoring for local engine
            words = [w for w in query_text_lower.split() if len(w) > 2]
            match_score = 0.0
            if words:
                matches = sum(1 for w in words if w in obs_text)
                match_score = matches / len(words)
            else:
                match_score = 0.5  # Baseline if query was purely category/party filtered

            # Exact phrase boost
            if query_text_lower in obs_text:
                match_score = max(match_score, 0.95)

            if match_score > 0.1 or not words:
                source_file = obs.provenance.verbatim_quote if obs.provenance else None
                results.append(
                    HindsightRecallResult(
                        memory_id=obs.observation_id,
                        category=MemoryCategory.CONSOLIDATED_OBSERVATION,
                        relevance_score=round(match_score, 3),
                        contract_id=obs.contract_id,
                        content_summary=obs.normalized_summary,
                        verbatim_quote=obs.quote,
                        source_file=obs.provenance.section_reference if obs.provenance else None,
                        section_reference=obs.clause_reference,
                        effective_date=agreement.effective_date,
                        is_superseded=not obs.is_active,
                    )
                )

        # Merge Hindsight Cloud memories if configured
        if self.hindsight_client.is_configured:
            cloud_memories = self.hindsight_client.recall(
                query=query.query_text,
                top_k=query.max_results,
                filters={"categories": query.categories, "parties": query.party_names},
            )
            existing_ids = {r.memory_id for r in results}
            for cm in cloud_memories:
                m_id = cm.get("document_id") or cm.get("id") or cm.get("memory_id")
                if m_id and m_id not in existing_ids:
                    results.append(
                        HindsightRecallResult(
                            memory_id=m_id,
                            category=MemoryCategory.CONSOLIDATED_OBSERVATION,
                            relevance_score=float(cm.get("score", 0.9)),
                            contract_id=cm.get("metadata", {}).get("contract_id", "HINDSIGHT-CLOUD"),
                            content_summary=cm.get("content", ""),
                            verbatim_quote=cm.get("metadata", {}).get("quote"),
                            section_reference=cm.get("metadata", {}).get("clause_reference"),
                            effective_date=cm.get("metadata", {}).get("effective_date"),
                            is_superseded=False,
                        )
                    )
                    existing_ids.add(m_id)

        # Sort descending by relevance score
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[: query.max_results]

    def compare_contract_terms(
        self, base_contract_id: str, target_contract_id: str, category: Optional[str] = None
    ) -> List[CrossContractDelta]:
        """Compares terms across two contracts (e.g. MSA vs SOW, or original vs amendment).
        
        Args:
            base_contract_id: Identifier of the primary or earlier agreement.
            target_contract_id: Identifier of the subsequent or modifying agreement.
            category: Optional clause category filter.
            
        Returns:
            List of CrossContractDelta describing differences, modifications, and potential conflicts.
        """
        deltas: List[CrossContractDelta] = []
        base_agr = self._agreements.get(base_contract_id)
        target_agr = self._agreements.get(target_contract_id)

        if not base_agr or not target_agr:
            return deltas

        # Identify shared counterparties
        shared_parties = list(set(base_agr.parties).intersection(set(target_agr.parties)))
        counterparty = shared_parties[0] if shared_parties else "Unknown"

        # Group observations by category
        base_obs_by_cat: Dict[str, List[HindsightObservation]] = {}
        for obs in self._observations.values():
            if obs.contract_id == base_contract_id and obs.is_active:
                if category is None or obs.category == category:
                    base_obs_by_cat.setdefault(obs.category, []).append(obs)

        target_obs_by_cat: Dict[str, List[HindsightObservation]] = {}
        for obs in self._observations.values():
            if obs.contract_id == target_contract_id and obs.is_active:
                if category is None or obs.category == category:
                    target_obs_by_cat.setdefault(obs.category, []).append(obs)

        # Compare matching categories
        all_categories = set(base_obs_by_cat.keys()).union(set(target_obs_by_cat.keys()))

        for cat in all_categories:
            base_list = base_obs_by_cat.get(cat, [])
            target_list = target_obs_by_cat.get(cat, [])

            if base_list and target_list:
                for b_obs in base_list:
                    for t_obs in target_list:
                        # Check text similarity
                        similarity = difflib.SequenceMatcher(None, b_obs.quote, t_obs.quote).ratio()
                        if similarity < 0.90:
                            # Significant variation detected
                            conflict = False
                            explanation = None

                            # Check for financial cap or term drift
                            if b_obs.financial_value is not None and t_obs.financial_value is not None:
                                if b_obs.financial_value != t_obs.financial_value:
                                    conflict = True
                                    explanation = (
                                        f"Value changed from {b_obs.financial_value} in {base_contract_id} "
                                        f"to {t_obs.financial_value} in {target_contract_id}."
                                    )

                            delta_type = "AMENDMENT_CHANGE" if target_agr.contract_type == "Amendment" else "SOW_MSA_DISCREPANCY"
                            deltas.append(
                                CrossContractDelta(
                                    counterparty=counterparty,
                                    base_contract_id=base_contract_id,
                                    target_contract_id=target_contract_id,
                                    delta_type=delta_type,
                                    clause_category=cat,
                                    base_clause_text=b_obs.quote,
                                    target_clause_text=t_obs.quote,
                                    conflict_detected=conflict,
                                    conflict_explanation=explanation,
                                    precedence_override_found=False,
                                )
                            )
            elif target_list and not base_list:
                for t_obs in target_list:
                    deltas.append(
                        CrossContractDelta(
                            counterparty=counterparty,
                            base_contract_id=base_contract_id,
                            target_contract_id=target_contract_id,
                            delta_type="NEW_CLAUSE_INTRODUCED",
                            clause_category=cat,
                            base_clause_text=None,
                            target_clause_text=t_obs.quote,
                            conflict_detected=False,
                            conflict_explanation=f"Clause category '{cat}' newly introduced in {target_contract_id}.",
                            precedence_override_found=False,
                        )
                    )

        return deltas

    def get_party_profile(self, party_name: str) -> Optional[Dict[str, Any]]:
        """Returns the complete intelligence profile for a contracting party."""
        canonical = party_name.strip()
        party = self._parties.get(canonical)
        if not party:
            return None

        party_contracts = [
            agr for agr in self._agreements.values()
            if canonical in agr.parties
        ]

        active_observations = [
            obs for obs in self._observations.values()
            if obs.contract_id in [c.contract_id for c in party_contracts] and obs.is_active
        ]

        return {
            "entity": party.model_dump(),
            "total_contracts": len(party_contracts),
            "contracts": [c.model_dump() for c in party_contracts],
            "active_obligations_count": len(active_observations),
            "active_clauses_by_category": {
                obs.category: obs.normalized_summary for obs in active_observations
            },
        }
