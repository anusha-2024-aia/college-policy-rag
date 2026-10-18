"""Streamlit User Interface for Document RAG - College Policy Intelligence."""

import sys
from pathlib import Path

# Ensure project root is in sys.path and remove 'ui' directory from sys.path
# to prevent 'ui/app.py' from shadowing the top-level 'app/' package.
_project_root = str(Path(__file__).resolve().parent.parent)
_ui_dir = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
while _ui_dir in sys.path:
    sys.path.remove(_ui_dir)

import json
from typing import Any
import streamlit as st

from ui.client import (
    BackendAPIClient,
    BackendConnectionError,
    APIValidationError,
    RateLimitError,
    ServiceUnavailableError,
    GatewayTimeoutError,
    APIClientError,
)

# Page configuration
st.set_page_config(
    page_title="College Policy Intelligence - Document RAG",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Institutional & Synthetic Dataset Disclaimer (Prominent Banner)
st.markdown(
    """
    > ⚠️ **Institutional & Synthetic Corpus Notice**: This assistant generates responses strictly based on ingested documents 
    > and is **not an official or legally binding source of institutional decisions**. All underlying college policy documents 
    > (e.g. Kestrel Valley Institute of Technology / KVIT) are **synthetic demonstration data** created for benchmarking and portfolio evaluation.
    """
)

# Sidebar Configuration
st.sidebar.title("🏛️ Document RAG")
st.sidebar.subheader("System Configuration")

api_base_url = st.sidebar.text_input(
    "Backend API Base URL",
    value="http://127.0.0.1:8080",
    help="Target FastAPI service address",
)

st.sidebar.markdown("---")
st.sidebar.subheader("User Identity & Access")

selected_role = st.sidebar.selectbox(
    "Simulated Access Role",
    options=["student", "faculty", "admin"],
    index=0,
    help="Governs SQL-level document filtering based on document allowed_roles",
)

st.sidebar.caption(
    "🔒 **Demonstration Interface**: The role selector simulates permissions for testing and demonstration. "
    "In a production environment, user roles must be verified server-side through cryptographically authenticated identity (e.g. SSO / OAuth2)."
)

st.sidebar.markdown("---")
st.sidebar.subheader("Retrieval & Reasoning Parameters")

top_k = st.sidebar.slider("Initial Candidates Depth (top_k)", min_value=5, max_value=50, value=20, step=5)
top_n = st.sidebar.slider("Final Passages Depth (top_n)", min_value=1, max_value=10, value=5, step=1)
version_aware = st.sidebar.checkbox("Enable Version-Aware Reasoning", value=True, help="Detects superseded documents and prioritizes current policy")
include_diagnostics = st.sidebar.checkbox("Show Retrieval Diagnostics", value=False, help="Displays latency breakdown and candidate counts (off by default)")

if st.sidebar.button("🧹 Clear Conversation History", use_container_width=True):
    st.session_state.messages = []
    st.rerun()

# Initialize session state for messages
if "messages" not in st.session_state:
    st.session_state.messages = []

# Main Area: Tabs
tab_assistant, tab_eval, tab_docs = st.tabs([
    "💬 Policy Assistant",
    "📊 Evaluation Benchmarks",
    "📑 Document Repository",
])


# ============================================================================
# TAB 1: POLICY ASSISTANT
# ============================================================================
with tab_assistant:
    st.header("College Policy & Document Assistant")
    st.markdown(
        f"Ask questions about course syllabi, grading criteria, administrative policies, or compliance guidelines. "
        f"Currently browsing as **`{selected_role.upper()}`**."
    )

    # Render previous conversation history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                # Assistant message rendering
                if msg.get("has_policy_conflict"):
                    st.warning("⚠️ **Policy Version Conflict Detected**: Evidence contains both active and superseded policies.")
                    if msg.get("conflict_details"):
                        for conf in msg["conflict_details"]:
                            st.info(
                                f"**Active**: {conf.get('current_title', 'Current Policy')} "
                                f"(Effective: {conf.get('current_effective_date', 'N/A')})\n\n"
                                f"**Superseded**: {conf.get('superseded_title', 'Older Policy')} "
                                f"(Effective: {conf.get('superseded_effective_date', 'N/A')})\n\n"
                                f"*{conf.get('description', '')}*"
                            )

                if msg.get("abstained"):
                    st.info(
                        "ℹ️ **No Sufficient Evidence Found**: The system searched available authorized documents for your role, "
                        "but could not find sufficient verifiable evidence to answer this question. (Abstained to prevent hallucination)."
                    )
                else:
                    st.markdown(msg["content"])

                    # Citations Accordion
                    citations = msg.get("citations", [])
                    if citations:
                        with st.expander(f"📚 Verified Citations ({len(citations)})", expanded=False):
                            for c in citations:
                                st.markdown(f"**[{c['index']}]** 📄 `{c['file_name']}` — **Page {c['page_number']}**")
                                if c.get("snippet"):
                                    st.caption(f'"{c["snippet"]}"')

                # Diagnostics Accordion
                diagnostics = msg.get("diagnostics")
                if diagnostics and include_diagnostics:
                    with st.expander("🔬 Retrieval Diagnostics (Role-Filtered)", expanded=False):
                        timings = diagnostics.get("timings_ms", {})
                        col1, col2, col3, col4, col5 = st.columns(5)
                        col1.metric("Vector Matches", diagnostics.get("vector_count", 0))
                        col2.metric("Keyword Matches", diagnostics.get("keyword_count", 0))
                        col3.metric("Fused Candidates", diagnostics.get("fused_count", 0))
                        col4.metric("Final Passages", diagnostics.get("reranked_count", 0))
                        col5.metric("Total Latency", f"{timings.get('total_retrieval_ms', 0):.1f} ms")

                        st.markdown("**Stage Timings**:")
                        st.text(
                            f"  - Dense Vector Search:  {timings.get('vector_search_ms', 0):.2f} ms\n"
                            f"  - Sparse Keyword Search: {timings.get('keyword_search_ms', 0):.2f} ms\n"
                            f"  - Reciprocal Rank Fusion: {timings.get('rrf_fusion_ms', 0):.2f} ms\n"
                            f"  - Cross-Encoder Rerank:  {timings.get('reranking_ms', 0):.2f} ms"
                        )
                        st.caption("🔒 Security Note: Diagnostics counts reflect only documents authorized for your active role.")

    # User Input
    user_query = st.chat_input("Ask a question about college policies, grading, remote work, or academic integrity...")
    if user_query:
        # Display user turn
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        # Call Backend Client
        client = BackendAPIClient(base_url=api_base_url)
        with st.chat_message("assistant"):
            with st.spinner("Searching authorized policies and generating answer..."):
                try:
                    response = client.ask(
                        question=user_query,
                        role=selected_role,
                        top_k=top_k,
                        top_n=top_n,
                        version_aware=version_aware,
                        include_diagnostics=include_diagnostics,
                    )

                    # Extract response data
                    msg_data = {
                        "role": "assistant",
                        "content": response.answer,
                        "abstained": response.abstained,
                        "has_policy_conflict": response.has_policy_conflict,
                        "conflict_details": [c.model_dump() for c in (response.conflict_details or [])],
                        "citations": [c.model_dump() for c in response.citations],
                        "diagnostics": response.diagnostics.model_dump() if response.diagnostics else None,
                    }
                    st.session_state.messages.append(msg_data)

                    # Render response
                    if response.has_policy_conflict:
                        st.warning("⚠️ **Policy Version Conflict Detected**: Evidence contains both active and superseded policies.")
                        if response.conflict_details:
                            for conf in response.conflict_details:
                                st.info(
                                    f"**Active**: {conf.current_title} (Effective: {conf.current_effective_date or 'N/A'})\n\n"
                                    f"**Superseded**: {conf.superseded_title} (Effective: {conf.superseded_effective_date or 'N/A'})\n\n"
                                    f"*{conf.description}*"
                                )

                    if response.abstained:
                        st.info(
                            "ℹ️ **No Sufficient Evidence Found**: The system searched available authorized documents for your role, "
                            "but could not find sufficient verifiable evidence to answer this question. (Abstained to prevent hallucination)."
                        )
                    else:
                        st.markdown(response.answer)

                        if response.citations:
                            with st.expander(f"📚 Verified Citations ({len(response.citations)})", expanded=True):
                                for c in response.citations:
                                    st.markdown(f"**[{c.index}]** 📄 `{c.file_name}` — **Page {c.page_number}**")
                                    if c.snippet:
                                        st.caption(f'"{c.snippet}"')

                    if response.diagnostics and include_diagnostics:
                        with st.expander("🔬 Retrieval Diagnostics (Role-Filtered)", expanded=False):
                            diag = response.diagnostics
                            col1, col2, col3, col4, col5 = st.columns(5)
                            col1.metric("Vector Matches", diag.vector_count)
                            col2.metric("Keyword Matches", diag.keyword_count)
                            col3.metric("Fused Candidates", diag.fused_count)
                            col4.metric("Final Passages", diag.reranked_count)
                            col5.metric("Total Latency", f"{diag.timings_ms.get('total_retrieval_ms', 0):.1f} ms")

                            st.markdown("**Stage Timings**:")
                            st.text(
                                f"  - Dense Vector Search:  {diag.timings_ms.get('vector_search_ms', 0):.2f} ms\n"
                                f"  - Sparse Keyword Search: {diag.timings_ms.get('keyword_search_ms', 0):.2f} ms\n"
                                f"  - Reciprocal Rank Fusion: {diag.timings_ms.get('rrf_fusion_ms', 0):.2f} ms\n"
                                f"  - Cross-Encoder Rerank:  {diag.timings_ms.get('reranking_ms', 0):.2f} ms"
                            )
                            st.caption("🔒 Security Note: Diagnostics counts reflect only documents authorized for your active role.")

                except BackendConnectionError as exc:
                    st.error(f"🔌 **Backend Connection Error**: {exc}")
                except APIValidationError as exc:
                    st.error(f"❌ **Validation Error**: {exc}")
                except RateLimitError as exc:
                    st.warning(f"⏳ **Rate Limit Exceeded**: {exc}")
                except ServiceUnavailableError as exc:
                    st.error(f"⚠️ **Service Unavailable**: {exc}")
                except GatewayTimeoutError as exc:
                    st.error(f"⏱️ **Gateway Timeout**: {exc}")
                except APIClientError as exc:
                    st.error(f"🚨 **API Error**: {exc}")
                except Exception as exc:
                    st.error(f"🚨 **Unexpected Application Error**: {exc}")


# ============================================================================
# TAB 2: EVALUATION BENCHMARKS
# ============================================================================
with tab_eval:
    st.header("Evaluation Benchmarks & Diagnostics")
    st.markdown(
        "Inspect real evaluation results and comparative benchmarks generated from `eval/results/`. "
        "Benchmarks compare vector-only, keyword-only, hybrid, hybrid-plus-reranking, and version-aware pipelines."
    )

    results_dir = Path("eval/results")
    if not results_dir.exists():
        st.info("Directory `eval/results/` does not exist yet. Run the evaluation CLI to generate reports.")
        st.code("python -m eval.run_eval --golden-path eval/golden.jsonl", language="bash")
    else:
        # Find all markdown reports
        md_reports = sorted(list(results_dir.glob("eval_report_*.md")), reverse=True)
        json_reports = sorted(list(results_dir.glob("eval_results_*.json")), reverse=True)

        if not md_reports and not json_reports:
            st.info("No benchmark reports found in `eval/results/`. Run the evaluation CLI to generate reports:")
            st.code("python -m eval.run_eval --golden-path eval/golden.jsonl", language="bash")
        else:
            selected_report = st.selectbox(
                "Select Benchmark Run",
                options=[r.name for r in md_reports],
                index=0,
            )

            if selected_report:
                report_path = results_dir / selected_report
                with open(report_path, "r", encoding="utf-8") as f:
                    report_content = f.read()

                st.markdown(report_content)

                # Matching JSON export for download
                matching_json_name = selected_report.replace("eval_report_", "eval_results_").replace(".md", ".json")
                matching_json_path = results_dir / matching_json_name

                if matching_json_path.exists():
                    with open(matching_json_path, "r", encoding="utf-8") as jf:
                        json_data = jf.read()
                    st.download_button(
                        label="📥 Download Raw JSON Results",
                        data=json_data,
                        file_name=matching_json_name,
                        mime="application/json",
                    )


# ============================================================================
# TAB 3: DOCUMENT REPOSITORY (READ-ONLY)
# ============================================================================
with tab_docs:
    st.header("Institutional Document Repository")
    st.markdown(
        "Inspect policy documents and chunks currently stored in the database. "
        "Access is governed by institutional Role-Based Access Control (RBAC) and version lineage."
    )

    try:
        from app.core.database import SessionLocal
        from app.models.document import Document

        with SessionLocal() as db:
            docs = db.query(Document).order_by(Document.effective_date.desc()).all()

            col1, col2, col3 = st.columns(3)
            total_chunks = sum(d.total_chunks for d in docs)
            total_pages = sum(d.total_pages for d in docs)
            col1.metric("Indexed Documents", len(docs))
            col2.metric("Total Extracted Chunks", total_chunks)
            col3.metric("Total Document Pages", total_pages)

            table_data = [
                {
                    "File Name": d.file_name,
                    "Title": d.title,
                    "Effective Date": str(d.effective_date),
                    "Supersedes": d.supersedes or "—",
                    "Allowed Roles": ", ".join(d.allowed_roles) if isinstance(d.allowed_roles, list) else str(d.allowed_roles),
                    "Pages": d.total_pages,
                    "Chunks": d.total_chunks,
                    "Status": d.status,
                }
                for d in docs
            ]
            st.dataframe(table_data, use_container_width=True)

    except Exception as exc:
        st.warning(f"Could not load live document records from database: {exc}")

    st.markdown("---")
    st.subheader("📄 Policy PDF Inspection & Preview (Read-Only)")
    st.caption("Upload a policy PDF to inspect its page count and structure prior to formal ingestion.")

    uploaded_pdf = st.file_uploader("Select PDF file to inspect", type=["pdf"], key="pdf_preview_uploader")
    if uploaded_pdf is not None:
        try:
            import pypdf
            reader = pypdf.PdfReader(uploaded_pdf)
            num_pages = len(reader.pages)
            file_size_kb = len(uploaded_pdf.getvalue()) / 1024.0

            pcol1, pcol2 = st.columns(2)
            pcol1.metric("File Name", uploaded_pdf.name)
            pcol2.metric("Parsed Pages", f"{num_pages} pages ({file_size_kb:.1f} KB)")

            if num_pages > 0:
                preview_text = reader.pages[0].extract_text() or ""
                with st.expander("🔍 Page 1 Text Preview", expanded=True):
                    st.text(preview_text[:500] + ("..." if len(preview_text) > 500 else ""))

            st.info(
                "🔒 **Read-Only Inspection Notice**: Direct database ingestion from the UI is disabled for institutional data integrity. "
                "To ingest new institutional policies, register them in `docs/documents_manifest.csv` and run the verified CLI pipeline: "
                "`python -m app.cli.ingest`."
            )
        except Exception as exc:
            st.error(f"Failed to parse PDF file: {exc}")

