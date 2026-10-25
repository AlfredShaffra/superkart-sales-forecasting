"""SuperKart inference API. Model and preprocessing are loaded once per worker."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

HERE = Path(__file__).resolve().parent
MODEL_PATH = Path(os.environ.get("MODEL_PATH", str(HERE / "superkart_model.joblib")))
SCHEMA_PATH = Path(os.environ.get("SCHEMA_PATH", str(HERE / "model_schema.json")))
SCHEMA = json.loads(SCHEMA_PATH.read_text())
MODEL = joblib.load(MODEL_PATH)
MODEL_SHA256 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
FEATURES = SCHEMA["feature_columns"]
NUMERIC = SCHEMA["numeric_features"]
CATEGORICAL = SCHEMA["categorical_features"]
VERSION = SCHEMA.get("model_version", "superkart-1.0")
MAX_ROWS = 5000
PROFILE_FIELDS = ["Store_Size", "Store_Location_City_Type", "Store_Type", "Store_Age_Years"]
OBSERVED_PROFILES = {
    tuple(str(p[k]) if k != "Store_Age_Years" else float(p[k]) for k in PROFILE_FIELDS)
    for p in SCHEMA.get("observed_store_profiles", [])
}

superkart_api = Flask("SuperKart")
superkart_api.config.update(MAX_CONTENT_LENGTH=2 * 1024 * 1024, JSON_SORT_KEYS=False)
superkart_api.json.sort_keys = False


class InputError(ValueError):
    """An input contract error that is safe to return to a caller."""


def validate_frame(frame: pd.DataFrame):
    """Validate physical ranges and record extrapolation warnings without hiding them."""
    missing = [c for c in FEATURES if c not in frame.columns]
    if missing:
        raise InputError("Missing required columns: " + ", ".join(missing))
    if frame.empty:
        raise InputError("Provide at least one data row.")
    if len(frame) > MAX_ROWS:
        raise InputError(f"A batch may contain at most {MAX_ROWS:,} rows.")
    if frame.columns.duplicated().any():
        raise InputError("Column names must be unique.")
    frame = frame[FEATURES].copy().reset_index(drop=True)
    for c in NUMERIC:
        if frame[c].map(lambda x: isinstance(x, (bool, np.bool_))).any():
            raise InputError(f"{c} must contain numbers, not Boolean values.")
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
        invalid = ~np.isfinite(frame[c].to_numpy(dtype=float))
        if invalid.any():
            rows = (np.flatnonzero(invalid)[:5] + 1).tolist()
            raise InputError(f"{c} must contain finite numbers. Invalid rows: {rows}.")
    ranges = {
        "Product_Weight": (0, None, False),
        "Product_MRP": (0, None, False),
        "Product_Allocated_Area": (0, 1, True),
        "Store_Age_Years": (0, 150, True),
    }
    for c, (low, high, inclusive) in ranges.items():
        bad = frame[c] < low if inclusive else frame[c] <= low
        if high is not None:
            bad |= frame[c] > high
        if bad.any():
            raise InputError(f"{c} is outside its permitted range.")
    if ((frame["Store_Age_Years"] % 1) != 0).any():
        raise InputError("Store_Age_Years must be a whole number relative to 2025.")
    for c in CATEGORICAL:
        if frame[c].isna().any():
            raise InputError(f"{c} cannot be blank.")
        frame[c] = frame[c].astype(str).str.strip()
        if (frame[c] == "").any():
            raise InputError(f"{c} cannot be blank.")
    frame["Product_Sugar_Content"] = frame["Product_Sugar_Content"].replace({"reg": "Regular"})
    warnings = [[] for _ in range(len(frame))]
    for i, row in frame.iterrows():
        for c in CATEGORICAL:
            domain = SCHEMA.get("allowed_categories", {}).get(c, [])
            if domain and row[c] not in domain:
                warnings[i].append(f"Unseen category: {c}={row[c]}. Treat this estimate as extrapolation.")
        for c in NUMERIC:
            bounds = SCHEMA.get("numeric_bounds", {}).get(c, {})
            if bounds and (float(row[c]) < float(bounds["min"]) or float(row[c]) > float(bounds["max"])):
                warnings[i].append(f"{c} is outside the model training range.")
        profile = tuple(str(row[k]) if k != "Store_Age_Years" else float(row[k]) for k in PROFILE_FIELDS)
        if OBSERVED_PROFILES and profile not in OBSERVED_PROFILES:
            warnings[i].append("Store attributes form a combination absent from training data.")
    return frame, warnings


@superkart_api.errorhandler(InputError)
def input_error(error):
    return jsonify(error=str(error)), 400


@superkart_api.errorhandler(BadRequest)
def malformed_request(error):
    return jsonify(error="Malformed request. Send valid JSON or a valid CSV file."), 400


@superkart_api.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(error="The uploaded file exceeds the 2 MB limit."), 413


@superkart_api.get("/")
def home():
    return jsonify(service="SuperKart Sales Forecast API", status="ready", model_version=VERSION,
                   routes=["/health", "/v1/schema", "/v1/predict", "/v1/predictbatch"])


@superkart_api.get("/health")
def health():
    return jsonify(status="ok", model_loaded=True, model_version=VERSION,
                   model_sha256=MODEL_SHA256, feature_count=len(FEATURES))


@superkart_api.get("/v1/schema")
def schema():
    return jsonify(**SCHEMA, maximum_batch_rows=MAX_ROWS, maximum_upload_bytes=2097152)


@superkart_api.post("/v1/predict")
def predict_sales():
    start = perf_counter()
    if not request.is_json:
        return jsonify(error="Content-Type must be application/json."), 415
    data = request.get_json()
    if not isinstance(data, dict):
        raise InputError("Send one product-store record as a JSON object.")
    frame, warnings = validate_frame(pd.DataFrame([data]))
    prediction = float(MODEL.predict(frame)[0])
    if not math.isfinite(prediction):
        return jsonify(error="The model could not produce a finite estimate."), 500
    return jsonify(Sales=round(prediction, 2), model_version=VERSION, warnings=warnings[0],
                   elapsed_ms=round((perf_counter() - start) * 1000, 2))


@superkart_api.post("/v1/predictbatch")
def predict_sales_batch():
    start = perf_counter()
    if "file" not in request.files:
        raise InputError("Attach a CSV file using the multipart field named 'file'.")
    uploaded = request.files["file"]
    try:
        raw = uploaded.read()
        if not raw.strip():
            raise InputError("The uploaded CSV is empty.")
        # Parse the header separately so duplicate columns cannot be silently renamed.
        import csv
        header = next(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        if len(header) != len(set(header)):
            raise InputError("Column names must be unique.")
        frame = pd.read_csv(io.BytesIO(raw))
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError, StopIteration):
        raise InputError("The file must be a valid, UTF-8 encoded CSV with a header row.")
    clean, warnings = validate_frame(frame)
    predictions = MODEL.predict(clean)
    if not np.isfinite(predictions).all():
        return jsonify(error="The model could not produce finite estimates."), 500
    results = [dict(row=i + 1, Sales=round(float(p), 2), warnings=warnings[i]) for i, p in enumerate(predictions)]
    return jsonify(model_version=VERSION, row_count=len(results),
                   total_predicted_sales=round(float(np.sum(predictions)), 2),
                   rows_with_warnings=sum(bool(w) for w in warnings), predictions=results,
                   elapsed_ms=round((perf_counter() - start) * 1000, 2))


if __name__ == "__main__":
    superkart_api.run(host="0.0.0.0", port=7860, debug=False)
