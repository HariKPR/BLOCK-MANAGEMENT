"""Streamlit dashboard for Railway Block Management.

Run locally with:
    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from main import run_pipeline


st.set_page_config(
    page_title="Railway Block Management",
    page_icon="🚆",
    layout="wide",
)

st.title("🚆 Railway Block Management")
st.caption("BDMS → Priority Scoring → Joint Block Merge → CP-SAT Scheduling")

with st.sidebar:
    st.header("Simulation Controls")
    request_count = st.slider("Maintenance requests", 5, 100, 15)
    timetable_count = st.slider("Timetable entries", 10, 200, 40)
    seed = st.number_input("Random seed", min_value=0, value=42, step=1)
    run = st.button("Run Optimization", type="primary", use_container_width=True)

if run or "results" not in st.session_state:
    try:
        with st.spinner("Running optimization..."):
            st.session_state.results = run_pipeline(
                request_count=request_count,
                timetable_count=timetable_count,
                seed=int(seed),
            )
        st.success("Optimization completed successfully.")
    except ModuleNotFoundError as exc:
        st.error("A required Python package is missing.")
        st.code("pip install -r requirements.txt")
        st.exception(exc)
        st.stop()
    except Exception as exc:
        st.error("The optimization could not be completed.")
        st.exception(exc)
        st.stop()

results = st.session_state.results
requests = results["requests"]
scored = results["scored"]
blocks = results["blocks"]
scheduled = results["scheduled"]

original_hours = int(blocks["original_duration_hours"].sum()) if not blocks.empty else 0
optimized_hours = int(blocks["duration_hours"].sum()) if not blocks.empty else 0
hours_saved = int(blocks["hours_saved"].sum()) if not blocks.empty else 0
joint_blocks = int((blocks["block_type"] == "JOINT").sum()) if not blocks.empty else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Requests", len(requests))
c2.metric("Final Blocks", len(blocks))
c3.metric("Joint Blocks", joint_blocks)
c4.metric("Original Hours", original_hours)
c5.metric("Hours Saved", hours_saved)

st.subheader("📅 Optimized Schedule")
if scheduled.empty:
    st.info("No blocks were generated for the selected inputs.")
else:
    display_columns = [
        "block_id",
        "section_id",
        "requested_date",
        "departments",
        "block_type",
        "duration_hours",
        "scheduled_start_hr",
        "scheduled_end_hr",
        "priority_score",
    ]
    st.dataframe(
        scheduled[display_columns],
        use_container_width=True,
        hide_index=True,
    )

st.subheader("🔗 Departmental Block Merging")
st.dataframe(
    blocks,
    use_container_width=True,
    hide_index=True,
)

st.subheader("🎯 Priority Scoring")
st.dataframe(
    scored,
    use_container_width=True,
    hide_index=True,
)

with st.expander("View Generated Maintenance Requests"):
    st.dataframe(requests, use_container_width=True, hide_index=True)

st.subheader("⬇️ Download Results")
for key, filename in [
    ("requests", "block_requests.csv"),
    ("scored", "scored_requests.csv"),
    ("blocks", "merged_blocks.csv"),
    ("scheduled", "scheduled_blocks.csv"),
]:
    st.download_button(
        label=f"Download {filename}",
        data=results[key].to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
    )
