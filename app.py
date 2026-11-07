"""ContractIQ — AI-Powered Contract Analysis Dashboard.

Streamlit web application for uploading PDF contracts and displaying
structured extraction results, risk assessments, and source citations.
"""

import os
import sys
import tempfile

import streamlit as st

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import analyze_pdf, analyze_text
from analysis.models import RiskSeverity


# ── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ContractIQ",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .risk-critical { background-color: #fee2e2; border-left: 4px solid #dc2626; padding: 12px; border-radius: 6px; margin-bottom: 8px; }
    .risk-high     { background-color: #fff7ed; border-left: 4px solid #ea580c; padding: 12px; border-radius: 6px; margin-bottom: 8px; }
    .risk-medium   { background-color: #fefce8; border-left: 4px solid #ca8a04; padding: 12px; border-radius: 6px; margin-bottom: 8px; }
    .risk-low      { background-color: #f0fdf4; border-left: 4px solid #16a34a; padding: 12px; border-radius: 6px; margin-bottom: 8px; }
    .quote-box     { background-color: #f8fafc; border-left: 3px solid #6366f1; padding: 10px 14px; margin: 6px 0; border-radius: 4px; font-style: italic; color: #334155; }
    .metric-card   { background-color: #f1f5f9; padding: 16px; border-radius: 8px; text-align: center; }
    .section-divider { border-top: 2px solid #e2e8f0; margin: 24px 0; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("# 📄")
    st.title("ContractIQ")
    st.caption("AI-Powered Contract Intelligence")
    st.divider()
    st.markdown("**How it works:**")
    st.markdown("""
    1. 📤 Upload a PDF contract
    2. 🔍 AI extracts key entities & clauses
    3. ⚠️ Risk engine identifies exposures
    4. 📋 Review results with source citations
    5. 🧠 Results stored in Hindsight memory
    """)
    st.divider()

    hindsight_status = "🟢 Connected" if os.getenv("HINDSIGHT_API_KEY") else "🟡 Local Mode"
    st.markdown(f"**Hindsight Cloud:** {hindsight_status}")
    if not os.getenv("HINDSIGHT_API_KEY"):
        st.caption("Set `HINDSIGHT_API_KEY` in `.env` for cloud memory.")


# ── Helper Functions ─────────────────────────────────────────────────────────

def render_risk_card(risk):
    """Renders a styled risk finding card."""
    severity_class = {
        RiskSeverity.CRITICAL: "risk-critical",
        RiskSeverity.HIGH: "risk-high",
        RiskSeverity.MEDIUM: "risk-medium",
        RiskSeverity.LOW: "risk-low",
    }
    severity_emoji = {
        RiskSeverity.CRITICAL: "🔴",
        RiskSeverity.HIGH: "🟠",
        RiskSeverity.MEDIUM: "🟡",
        RiskSeverity.LOW: "🟢",
    }
    css_class = severity_class.get(risk.severity, "risk-medium")
    emoji = severity_emoji.get(risk.severity, "⚪")

    st.markdown(f"""
    <div class="{css_class}">
        <strong>{emoji} {risk.severity.value}: {risk.title}</strong><br/>
        <span style="color: #475569;">{risk.description}</span><br/>
        <span style="color: #059669; font-size: 0.9em;">💡 <strong>Recommendation:</strong> {risk.mitigation_recommendation}</span>
    </div>
    """, unsafe_allow_html=True)

    if risk.evidence:
        with st.expander(f"📖 Source Evidence — Page {risk.evidence.page_number}"):
            st.markdown(f'<div class="quote-box">"{risk.evidence.verbatim_quote}"</div>', unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3)
            col1.metric("Page", risk.evidence.page_number)
            col2.metric("Section", risk.evidence.section_reference or "—")
            col3.metric("Confidence", f"{risk.evidence.confidence_score:.0%}")


def render_source_evidence(evidence, label="Source"):
    """Renders a source evidence block with quote and page reference."""
    st.markdown(f'<div class="quote-box">"{evidence.verbatim_quote}"</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.caption(f"📄 Page {evidence.page_number}")
    c2.caption(f"§ {evidence.section_reference or '—'}")
    c3.caption(f"🎯 {evidence.confidence_score:.0%} confidence")


# ── Main Content ─────────────────────────────────────────────────────────────

st.title("📄 ContractIQ")
st.subheader("Upload a contract for AI-powered analysis")

uploaded_file = st.file_uploader(
    "Drop a PDF contract here",
    type=["pdf"],
    help="Upload a PDF contract document for analysis. Max file size: 200MB.",
)

if uploaded_file is not None:
    with st.spinner("🔍 Analyzing contract... This may take a moment."):
        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            results = analyze_pdf(tmp_path)
        except Exception as e:
            st.error(f"❌ Analysis failed: {e}")
            st.stop()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    contract = results["contract"]
    risk_report = results["risk_report"]
    verification = results["verification"]
    memory_result = results["memory_result"]
    stats = results["buffer_stats"]

    st.success("✅ Analysis complete!")

    # ── Top-Level Metrics ────────────────────────────────────────────────

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("📄 Pages", stats["total_pages"])
    m2.metric("📐 Sections", stats["sections_detected"])
    m3.metric("👥 Parties", len(contract.parties))
    m4.metric("⚠️ Risks Found", risk_report.total_risks_identified)

    score_color = "🔴" if risk_report.overall_risk_score >= 50 else "🟡" if risk_report.overall_risk_score >= 20 else "🟢"
    m5.metric(f"{score_color} Risk Score", f"{risk_report.overall_risk_score:.0f}/100")

    # ── Tabs ─────────────────────────────────────────────────────────────

    tab_overview, tab_risks, tab_obligations, tab_terms, tab_verification, tab_memory = st.tabs([
        "📋 Overview", "⚠️ Risk Analysis", "📌 Obligations", "💰 Commercial Terms", "✅ Verification", "🧠 Memory"
    ])

    # ── Tab: Overview ────────────────────────────────────────────────────

    with tab_overview:
        st.subheader("Contract Metadata")
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown(f"**Title:** {contract.metadata.title}")
            st.markdown(f"**Type:** `{contract.metadata.contract_type}`")
            st.markdown(f"**Effective Date:** {contract.metadata.effective_date or '—'}")
            st.markdown(f"**Expiration Date:** {contract.metadata.expiration_date or '—'}")

        with col_right:
            st.markdown(f"**Governing Law:** {contract.metadata.governing_law or '—'}")
            st.markdown(f"**Jurisdiction:** {contract.metadata.jurisdiction_venue or '—'}")
            st.markdown(f"**Document ID:** `{contract.document_id[:12]}...`")
            st.markdown(f"**Document Hash:** `{stats['document_hash'][:16]}...`")

        with st.expander("📖 Source Evidence"):
            render_source_evidence(contract.metadata.evidence, "Metadata")

        st.divider()
        st.subheader("Contracting Parties")
        for party in contract.parties:
            with st.container():
                pc1, pc2, pc3 = st.columns([2, 1, 1])
                pc1.markdown(f"**{party.name}**")
                pc2.markdown(f"Role: `{party.role}`")
                pc3.markdown(f"Entity: `{party.entity_type or '—'}`")
                with st.expander(f"📖 Evidence for {party.name}"):
                    render_source_evidence(party.evidence, party.name)

        st.divider()
        st.subheader("Termination & Renewal")
        tr = contract.termination_and_renewal
        tc1, tc2, tc3 = st.columns(3)
        tc1.markdown(f"**Term Length:** {tr.term_length or '—'}")
        tc2.markdown(f"**Auto-Renewal:** {'Yes' if tr.auto_renewal else 'No'}")
        tc3.markdown(f"**Convenience Termination:** {'Yes' if tr.termination_for_convenience else 'No'}")

        tc4, tc5, tc6 = st.columns(3)
        tc4.markdown(f"**Convenience Notice:** {f'{tr.notice_for_convenience_days} days' if tr.notice_for_convenience_days else '—'}")
        tc5.markdown(f"**Cure Period:** {f'{tr.termination_for_cause_cure_days} days' if tr.termination_for_cause_cure_days else '—'}")
        tc6.markdown(f"**Post-Termination Duties:** {len(tr.post_termination_obligations)}")

        if tr.evidence:
            with st.expander("📖 Termination Source Evidence"):
                for ev in tr.evidence:
                    render_source_evidence(ev)
                    st.markdown("---")

    # ── Tab: Risk Analysis ───────────────────────────────────────────────

    with tab_risks:
        st.subheader("Risk Assessment Report")
        st.markdown(f"**{risk_report.summary}**")
        st.divider()

        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("🔴 Critical", risk_report.critical_count)
        rc2.metric("🟠 High", risk_report.high_count)
        rc3.metric("🟡 Medium", risk_report.medium_count)
        rc4.metric("🟢 Low", risk_report.low_count)

        st.divider()

        if risk_report.risks:
            for risk in risk_report.risks:
                render_risk_card(risk)
        else:
            st.info("No significant risks identified. This contract appears to follow standard terms.")

    # ── Tab: Obligations ─────────────────────────────────────────────────

    with tab_obligations:
        st.subheader("Contractual Obligations")
        if contract.obligations:
            for obl in contract.obligations:
                with st.container():
                    oc1, oc2, oc3 = st.columns([1, 2, 1])
                    oc1.markdown(f"**`{obl.obligation_id}`**")
                    oc2.markdown(f"**{obl.obligor}** — {obl.description}")
                    oc3.markdown(f"Category: `{obl.category}`")
                    with st.expander(f"📖 Evidence for {obl.obligation_id}"):
                        render_source_evidence(obl.evidence)
                    st.markdown("---")
        else:
            st.info("No explicit obligations detected in the contract text.")

    # ── Tab: Commercial Terms ────────────────────────────────────────────

    with tab_terms:
        st.subheader("Commercial & Payment Terms")
        ct = contract.commercial_terms

        ct1, ct2 = st.columns(2)
        with ct1:
            st.markdown(f"**Total Value:** {f'${ct.total_value:,.2f}' if ct.total_value else '—'}")
            st.markdown(f"**Currency:** {ct.currency or '—'}")
            st.markdown(f"**Payment Terms:** {ct.payment_terms or '—'}")
        with ct2:
            st.markdown(f"**Billing Frequency:** {ct.billing_frequency or '—'}")
            st.markdown(f"**Late Payment Penalty:** {ct.late_payment_penalty or '—'}")
            st.markdown(f"**Price Escalation:** {ct.price_escalation or '—'}")

        if ct.evidence:
            st.divider()
            st.subheader("Source Evidence")
            for ev in ct.evidence:
                render_source_evidence(ev)
                st.markdown("---")

        st.divider()
        st.subheader("Liability & Indemnification")
        rl = contract.risk_and_liability
        rl1, rl2 = st.columns(2)
        with rl1:
            st.markdown(f"**Liability Cap Type:** {rl.liability_cap_type or '—'}")
            st.markdown(f"**Cap Amount/Formula:** {rl.liability_cap_amount or '—'}")
            st.markdown(f"**Indemnification:** {rl.indemnification_scope or '—'}")
        with rl2:
            if rl.carve_outs:
                st.markdown("**Carve-Outs (Exceptions to Cap):**")
                for co in rl.carve_outs:
                    st.markdown(f"  - {co}")
            if rl.warranties:
                st.markdown("**Warranties:**")
                for w in rl.warranties:
                    st.markdown(f"  - {w}")
            if rl.disclaimers:
                st.markdown("**Disclaimers:**")
                for d in rl.disclaimers:
                    st.markdown(f"  - {d}")

        if rl.evidence:
            with st.expander("📖 Liability Source Evidence"):
                for ev in rl.evidence:
                    render_source_evidence(ev)
                    st.markdown("---")

    # ── Tab: Verification ────────────────────────────────────────────────

    with tab_verification:
        st.subheader("Extraction Verification Report")

        vc1, vc2, vc3, vc4 = st.columns(4)
        vc1.metric("✅ Verified", verification.verified_count)
        vc2.metric("❌ Contradicted", verification.contradicted_count)
        vc3.metric("❓ Unsupported", verification.unsupported_count)
        vc4.metric("⚠️ Ambiguous", verification.ambiguous_count)

        if verification.human_review_required:
            st.warning("⚠️ Human review recommended — some extractions could not be fully verified against the source document.")

        st.divider()

        for finding in verification.findings_audit:
            status_emoji = {"VERIFIED": "✅", "CONTRADICTED": "❌", "UNSUPPORTED": "❓", "AMBIGUOUS": "⚠️", "UNVERIFIED_CITATION": "📎"}.get(finding.status.value, "⚪")
            with st.expander(f"{status_emoji} {finding.finding_id} — {finding.category}: {finding.original_claim[:80]}"):
                st.markdown(f"**Status:** `{finding.status.value}`")
                st.markdown(f"**Buffer Match:** {'✅ Exact' if finding.buffer_match_exact else '❌ Mismatch'}")
                st.markdown(f"**Token Match Score:** {finding.normalized_token_match_score:.2%}")
                st.markdown(f"**Context Consistent:** {'✅' if finding.surrounding_context_consistent else '⚠️'}")
                if finding.discrepancy_explanation:
                    st.error(f"**Discrepancy:** {finding.discrepancy_explanation}")
                render_source_evidence(finding.submitted_evidence, "Submitted Evidence")

    # ── Tab: Memory ──────────────────────────────────────────────────────

    with tab_memory:
        st.subheader("🧠 Hindsight Memory Retention")

        if memory_result:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("📥 Submitted", memory_result.get("total_submitted_observations", 0))
            mc2.metric("✅ Retained", memory_result.get("retained_verified_observations", 0))
            mc3.metric("❌ Rejected", memory_result.get("rejected_unverified_observations", 0))

            st.divider()
            st.markdown(f"**Contract:** {memory_result.get('retained_agreement', '—')}")
            st.markdown(f"**Graph Edges Stored:** {memory_result.get('graph_edges_stored', 0)}")

            cloud_configured = memory_result.get("hindsight_cloud_configured", False)
            cloud_synced = memory_result.get("hindsight_cloud_synced", 0)
            if cloud_configured:
                st.success(f"☁️ Synced {cloud_synced} observations to Hindsight Cloud")
            else:
                st.info("🖥️ Results retained in local memory. Set `HINDSIGHT_API_KEY` to enable cloud sync.")
        else:
            st.info("Memory retention was skipped for this analysis.")

else:
    # Landing page
    st.markdown("""
    ### Getting Started

    Upload a PDF contract using the file uploader above to begin analysis.

    **ContractIQ will extract:**
    - 👥 **Parties** — names, roles, entity types
    - 📅 **Key Dates** — effective, expiration, execution dates
    - 💰 **Payment Terms** — fees, penalties, billing schedules
    - 📌 **Obligations** — duties, deliverables, SLAs
    - ⚖️ **Liability & Risk** — caps, carve-outs, indemnification
    - 🔄 **Termination** — convenience, cause, cure periods, renewal

    **Every finding includes:**
    - 📖 Verbatim source quotation
    - 📄 Page number reference
    - § Section identifier
    - 🎯 Extraction confidence score
    """)

    st.divider()

    # Demo with sample text
    with st.expander("🧪 Try a Demo (paste contract text)"):
        sample_text = st.text_area(
            "Paste contract text here:",
            height=200,
            placeholder="Paste any contract text to test the extraction engine...",
        )
        if st.button("Analyze Text", type="primary") and sample_text.strip():
            with st.spinner("Analyzing..."):
                results = analyze_text(sample_text)

            contract = results["contract"]
            risk_report = results["risk_report"]

            st.success("✅ Analysis complete!")

            st.markdown(f"**Title:** {contract.metadata.title}")
            st.markdown(f"**Type:** `{contract.metadata.contract_type}`")
            st.markdown(f"**Parties:** {', '.join(p.name for p in contract.parties)}")
            st.markdown(f"**Risk Score:** {risk_report.overall_risk_score:.0f}/100")
            st.markdown(f"**Risks Found:** {risk_report.total_risks_identified}")

            for risk in risk_report.risks:
                render_risk_card(risk)

