"""Streamlit client for the separate SuperKart Flask inference service."""
from __future__ import annotations

import io
import hashlib
import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:7860").rstrip("/")
HERE = Path(__file__).resolve().parent
st.set_page_config(page_title="SuperKart Sales Forecast", page_icon="🛒", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
  .block-container {padding-top:2rem;padding-bottom:2rem;max-width:1500px;}
  h1 {font-size:2.5rem!important;letter-spacing:-.04em;color:#153047;}
  h2 {font-size:1.45rem!important;letter-spacing:-.02em;}
  [data-testid="stMetric"] {background:white;border:1px solid #DCE6ED;border-radius:12px;padding:14px 20px;}
  [data-testid="stMetricValue"] {font-size:2.1rem!important;color:#087F8C;}
  [data-testid="stSidebar"] {background:#EEF3F7;}
  .subtitle {color:#536B7C;font-size:1.05rem;margin-top:-.6rem;margin-bottom:1.1rem;}
  .eyebrow {color:#087F8C;font-size:.78rem;font-weight:700;letter-spacing:.14em;}
  .scope {color:#536B7C;font-size:.85rem;line-height:1.5;}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=15, show_spinner=False)
def service_health():
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=8)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def request_prediction(route, **kwargs):
    try:
        r = requests.post(f"{BACKEND_URL}{route}", timeout=60, **kwargs)
        try:
            body = r.json()
        except ValueError:
            st.error("The prediction service returned an unreadable response. Please retry.")
            return None
        if not r.ok:
            st.error(body.get("error", f"Prediction request failed (HTTP {r.status_code})."))
            return None
        return body
    except requests.Timeout:
        st.error("The prediction service timed out. Please retry in a moment.")
    except requests.RequestException:
        st.error("The prediction service is unavailable. Check the connection and retry.")
    return None


health = service_health()
with st.sidebar:
    st.markdown("## SuperKart")
    st.caption("SALES PLANNING WORKSPACE")
    st.divider()
    if health:
        st.success("Prediction service connected")
        st.caption(f"Model: {health['model_version']}")
    else:
        st.error("Prediction service unavailable")
    st.markdown("#### How to interpret the result")
    st.markdown("Revenue estimate for one product in one store, in the dataset's original revenue units.")
    st.markdown("#### Planning scope")
    st.markdown("The source data has no sales dates. Treat estimates as a planning baseline until the sales period and next-quarter outcomes are confirmed.")
    st.markdown("#### Store age")
    st.markdown("Use the fixed training reference: **2025 − establishment year**.")
    with st.expander("Service details"):
        st.code(BACKEND_URL, language=None)
        if health:
            st.caption("Serialized pipeline fingerprint")
            st.code(health["model_sha256"][:16], language=None)
    st.caption("Project by Alfred Manasseh · DBA AIML")

st.markdown('<div class="eyebrow">REVENUE PLANNING</div>', unsafe_allow_html=True)
st.title("SuperKart Sales Forecast")
st.markdown('<p class="subtitle">Estimate product-store sales and review a complete batch in one place.</p>', unsafe_allow_html=True)

single_tab, batch_tab = st.tabs(["Single prediction", "Batch prediction"])
with single_tab:
    st.subheader("Product and store details")
    with st.form("single_prediction"):
        left, right = st.columns(2, gap="large")
        with left:
            weight = st.number_input("Product weight", min_value=0.01, value=12.66, step=0.10, format="%.2f")
            sugar = st.selectbox("Sugar content", ["Low Sugar", "Regular", "No Sugar"])
            area = st.number_input("Allocated display area (ratio)", min_value=0.0, max_value=1.0, value=0.027, step=0.001, format="%.3f")
            mrp = st.number_input("Maximum retail price", min_value=0.01, value=117.08, step=1.0, format="%.2f")
            prefix = st.selectbox("Product ID prefix", ["FD", "DR", "NC"])
        with right:
            size = st.selectbox("Store size", ["Medium", "Small", "High"])
            tier = st.selectbox("City tier", ["Tier 2", "Tier 1", "Tier 3"])
            store_type = st.selectbox("Store type", ["Supermarket Type2", "Supermarket Type1", "Departmental Store", "Food Mart"])
            age = st.number_input("Store age in years (2025 reference)", min_value=0, max_value=150, value=16, step=1)
            category = st.selectbox("Product category", ["Non Perishables", "Perishables"])
        submitted = st.form_submit_button("Predict sales", type="primary", use_container_width=True)
    if submitted:
        payload = {
            "Product_Weight": weight, "Product_Sugar_Content": sugar,
            "Product_Allocated_Area": area, "Product_MRP": mrp,
            "Store_Size": size, "Store_Location_City_Type": tier,
            "Store_Type": store_type, "Product_Id_char": prefix,
            "Store_Age_Years": age, "Product_Type_Category": category,
        }
        with st.spinner("Calculating sales estimate..."):
            result = request_prediction("/v1/predict", json=payload)
        if result:
            st.session_state.single_result = result
            st.session_state.single_payload = payload
    if "single_result" in st.session_state:
        result = st.session_state.single_result
        st.success("Prediction completed")
        st.caption(f"Prediction service: {BACKEND_URL}/v1/predict")
        one, two, three = st.columns([2, 1, 1])
        one.metric("Estimated product-store sales", f"{result['Sales']:,.2f}")
        two.metric("Revenue unit", "Source units")
        three.metric("API response", "HTTP 200")
        for warning in result.get("warnings", []):
            st.warning(warning)
        st.caption("The estimate uses the most recently submitted inputs. Submit again after changing the form.")
        with st.expander("Prediction request and response"):
            st.json({"input": st.session_state.single_payload, "response": result})

with batch_tab:
    st.subheader("Estimate sales for multiple product-store records")
    st.write("Upload a CSV with the same 10 feature columns, then download the predictions with the original rows.")
    sample_path = HERE / "Batch_Data_SuperKart.csv"
    if sample_path.exists():
        st.download_button("Download example CSV", sample_path.read_bytes(), "Batch_Data_SuperKart.csv", "text/csv")
    uploaded = st.file_uploader("Upload a CSV file (maximum 2 MB)", type=["csv"])
    upload_digest = hashlib.sha256(uploaded.getvalue()).hexdigest() if uploaded is not None else None
    if upload_digest != st.session_state.get("batch_upload_digest"):
        st.session_state.pop("batch_result", None)
        st.session_state.pop("batch_output", None)
        st.session_state["batch_upload_digest"] = upload_digest
    if uploaded is not None:
        raw = uploaded.getvalue()
        try:
            preview = pd.read_csv(io.BytesIO(raw))
            st.caption(f"{len(preview):,} rows loaded · {len(preview.columns)} columns")
        except (ValueError, pd.errors.EmptyDataError, UnicodeDecodeError):
            st.error("The file could not be read. Upload a UTF-8 CSV with a header row.")
            preview = None
        if preview is not None:
            if st.button("Predict batch sales", type="primary", use_container_width=True):
                with st.spinner("Calculating batch estimates..."):
                    result = request_prediction("/v1/predictbatch", files={"file": (uploaded.name, raw, "text/csv")})
                if result:
                    st.session_state.batch_result = result
                    st.session_state.batch_filename = uploaded.name
                    output = preview.copy().reset_index(drop=True)
                    output.insert(0, "Row", [r["row"] for r in result["predictions"]])
                    output["Predicted_Sales"] = [r["Sales"] for r in result["predictions"]]
                    output["Warnings"] = [" ".join(r["warnings"]) for r in result["predictions"]]
                    st.session_state.batch_output = output
    if "batch_result" in st.session_state:
        result = st.session_state.batch_result
        st.success(f"{result['row_count']} predictions completed")
        st.caption(f"Source file: {st.session_state.batch_filename}")
        st.caption(f"Prediction service: {BACKEND_URL}/v1/predictbatch")
        one, two, three = st.columns(3)
        one.metric("Rows predicted", result["row_count"])
        two.metric("Total estimated sales", f"{result['total_predicted_sales']:,.2f}")
        three.metric("Rows requiring review", result["rows_with_warnings"])
        if result["rows_with_warnings"]:
            st.warning("Review flagged rows before planning. Unseen store types or store combinations are outside the demonstrated training coverage.")
        output = st.session_state.batch_output
        display = output[["Row", "Store_Type", "Store_Size", "Store_Location_City_Type", "Predicted_Sales", "Warnings"]]
        st.dataframe(display, use_container_width=True, hide_index=True, height=390,
                     column_config={"Predicted_Sales": st.column_config.NumberColumn("Predicted sales", format="%.2f"),
                                    "Warnings": st.column_config.TextColumn("Review notes", width="large")})
        st.download_button("Download predictions CSV", output.to_csv(index=False).encode("utf-8"),
                           "SuperKart_Batch_Predictions.csv", "text/csv", type="primary")
        st.caption("No observed sales targets were provided for this batch. These outputs demonstrate inference, not batch forecast accuracy.")
        with st.expander("Batch API response"):
            st.json(result)
