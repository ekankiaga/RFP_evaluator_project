"""Supplier PDF intake and metadata validation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

from ...tools.document_tool import DocumentTool
from ...ui.components import chip


def render() -> None:
    st.title("Supplier proposals")
    st.caption("Step 2 of 3 · Upload one PDF per supplier, then check each supplier name, submission date, and experience rating.")
    st.info("Sample files are in `sample_data/pdfs/it_software_saas/` and `sample_data/pdfs/healthcare_life_sciences/`. Upload proposals from the same folder for one evaluation.")
    viewer = st.session_state.get("role") == "Viewer"
    files = st.file_uploader("Choose supplier proposal PDFs", type=["pdf"], accept_multiple_files=True,
        key="supplier_pdfs", disabled=viewer, help="Select multiple files at once. Each uploaded file becomes one supplier in this evaluation.")
    if not files:
        st.info("Upload one or more PDF responses to start a batch.")
        st.session_state["supplier_inputs"] = []
        return
    metadata = st.session_state.setdefault("supplier_metadata", {})
    st.caption(f"{len(files)} file{'s' if len(files) != 1 else ''} selected · Metadata defaults can be edited below.")
    prepared = []
    seen_names: set[str] = set()
    for index, uploaded in enumerate(files):
        content = uploaded.getvalue()
        entry = metadata.setdefault(uploaded.name, {"supplier_name": Path(uploaded.name).stem, "submission_date": date.today(), "experience_rating": 5.0})
        with st.expander(f"{uploaded.name} · {len(content):,} bytes", expanded=index == 0):
            if not uploaded.name.casefold().endswith(".pdf"):
                st.error("File is not a PDF.")
                continue
            try:
                extracted = DocumentTool().extract(content)
                st.caption(f"{extracted.page_count} pages · text quality {'Low / scanned' if extracted.scanned else 'Readable'} · SHA-256 `{extracted.document_hash[:12]}`")
                for warning in extracted.warnings:
                    st.warning(warning)
            except Exception as exc:
                st.error(f"PDF is empty, damaged, or unreadable: {exc}")
                continue
            col1, col2, col3 = st.columns([2, 1.2, 1])
            name = col1.text_input("Supplier name", value=entry["supplier_name"], key=f"supplier_name_{index}", disabled=viewer).strip()
            submitted = col2.date_input("Submission date", value=entry["submission_date"], key=f"supplier_date_{index}", disabled=viewer)
            experience = col3.number_input("Experience rating", min_value=1.0, max_value=10.0, value=float(entry["experience_rating"]), step=.5, key=f"supplier_rating_{index}", disabled=viewer)
            entry.update({"supplier_name": name, "submission_date": submitted, "experience_rating": experience})
            errors = []
            if not name:
                errors.append("Missing supplier name")
            elif name.casefold() in seen_names:
                errors.append("Duplicate supplier name")
            if submitted is None:
                errors.append("Bad submission date")
            if not 1 <= float(experience) <= 10:
                errors.append("Experience rating must be 1–10")
            if errors:
                st.markdown(" ".join(chip(error, "bad") for error in errors), unsafe_allow_html=True)
            else:
                st.markdown(chip("Metadata valid"), unsafe_allow_html=True)
                seen_names.add(name.casefold())
                prepared.append({"supplier_name": name, "submission_date": submitted, "experience_rating": float(experience),
                                 "pdf": content, "document_name": uploaded.name})
    st.session_state["supplier_inputs"] = prepared
    st.metric("Ready suppliers", len(prepared))
    if files and not prepared:
        st.warning("No supplier is ready. Resolve PDF and metadata validation messages above.")
