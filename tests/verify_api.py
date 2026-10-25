"""Exercise the real HTTP API and persist evidence for the final presentation."""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("BACKEND_URL", "http://127.0.0.1:7860").rstrip("/")
EVIDENCE = ROOT / "evidence"
EVIDENCE.mkdir(exist_ok=True)
MODEL = joblib.load(ROOT / "backend/superkart_model.joblib")
payload = {
    "Product_Weight": 12.66,
    "Product_Sugar_Content": "Low Sugar",
    "Product_Allocated_Area": 0.027,
    "Product_MRP": 117.08,
    "Store_Size": "Medium",
    "Store_Location_City_Type": "Tier 2",
    "Store_Type": "Supermarket Type2",
    "Product_Id_char": "FD",
    "Store_Age_Years": 16,
    "Product_Type_Category": "Non Perishables",
}
checks = []


def check(name, condition, detail):
    checks.append(dict(test=name, passed=bool(condition), detail=detail))
    if not condition:
        raise AssertionError(f"{name}: {detail}")


health = requests.get(BASE + "/health", timeout=15)
check("Health and model loaded", health.status_code == 200 and health.json()["model_loaded"], health.json())
start = perf_counter()
r = requests.post(BASE + "/v1/predict", json=payload, timeout=60)
single_elapsed = perf_counter() - start
single = r.json()
check("Single inference HTTP 200", r.status_code == 200 and isinstance(single["Sales"], (int, float)), single)
expected = float(MODEL.predict(pd.DataFrame([payload]))[0])
check("Single API agrees with serialized pipeline", abs(single["Sales"] - expected) <= 0.00501,
      {"api": single["Sales"], "pipeline_unrounded": expected})

batch = pd.read_csv(ROOT / "frontend/Batch_Data_SuperKart.csv")
start = perf_counter()
r = requests.post(BASE + "/v1/predictbatch", files={"file": ("Batch_Data_SuperKart.csv", batch.to_csv(index=False).encode(), "text/csv")}, timeout=60)
batch_elapsed = perf_counter() - start
batch_result = r.json()
check("Batch inference HTTP 200 and 10 rows", r.status_code == 200 and batch_result["row_count"] == 10, {"status": r.status_code, "row_count": batch_result.get("row_count")})
predictions = np.array([x["Sales"] for x in batch_result["predictions"]])
direct = MODEL.predict(batch)
check("Batch API agrees with serialized pipeline", np.max(np.abs(predictions - direct)) <= 0.00501, {"max_absolute_difference": float(np.max(np.abs(predictions - direct)))})
check("Batch row order preserved", [x["row"] for x in batch_result["predictions"]] == list(range(1, 11)), "Rows 1–10 retained")
type3_indices = batch.index[batch.Store_Type == "Supermarket Type3"].tolist()
check("Unseen Type3 warnings", all(any("Unseen category: Store_Type" in w for w in batch_result["predictions"][i]["warnings"]) for i in type3_indices), {"zero_based_indices": type3_indices})
check("Unobserved store profile warnings", all(any("combination absent" in w for w in p["warnings"]) for p in batch_result["predictions"]), {"rows_with_warnings": batch_result["rows_with_warnings"]})

missing = payload.copy()
missing.pop("Product_MRP")
r = requests.post(BASE + "/v1/predict", json=missing, timeout=15)
check("Missing feature rejected", r.status_code == 400 and "Product_MRP" in r.json()["error"], r.json())
invalid = payload.copy()
invalid["Product_Allocated_Area"] = 1.5
r = requests.post(BASE + "/v1/predict", json=invalid, timeout=15)
check("Invalid display area rejected", r.status_code == 400, r.json())
r = requests.post(BASE + "/v1/predict", data="{invalid", headers={"Content-Type": "application/json"}, timeout=15)
check("Malformed JSON rejected", r.status_code == 400, r.json())
r = requests.post(BASE + "/v1/predict", json=[payload], timeout=15)
check("JSON list rejected for single record", r.status_code == 400, r.json())
r = requests.post(BASE + "/v1/predictbatch", files={"file": ("empty.csv", b"")}, timeout=15)
check("Empty batch rejected", r.status_code == 400, r.json())
r = requests.post(BASE + "/v1/predictbatch", files={"file": ("missing.csv", b"Product_MRP\n100\n")}, timeout=15)
check("Batch missing schema rejected", r.status_code == 400, r.json())
r = requests.post(BASE + "/v1/predictbatch", files={"file": ("duplicate.csv", b"a,a\n1,2\n")}, timeout=15)
check("Duplicate CSV column rejected", r.status_code == 400, r.json())
r = requests.post(BASE + "/v1/predict", json={**payload, "Product_Weight": "not a number"}, timeout=15)
check("Nonnumeric input rejected", r.status_code == 400, r.json())
r = requests.post(BASE + "/v1/predict", json={**payload, "Store_Type": ""}, timeout=15)
check("Blank category rejected", r.status_code == 400, r.json())

batch_output = batch.copy()
batch_output.insert(0, "Row", list(range(1, 11)))
batch_output["Predicted_Sales"] = predictions
batch_output["Warnings"] = [" ".join(x["warnings"]) for x in batch_result["predictions"]]
batch_output.to_csv(EVIDENCE / "SuperKart_Batch_Predictions.csv", index=False)
evidence = dict(verified_at=datetime.now(timezone.utc).isoformat(), backend_url=BASE,
                total_checks=len(checks), passed=sum(t["passed"] for t in checks),
                single_payload=payload, single_response=single, batch_response=batch_result,
                single_http_wall_time_ms=round(single_elapsed * 1000, 2),
                batch_http_wall_time_ms=round(batch_elapsed * 1000, 2), checks=checks)
(EVIDENCE / "api_verification.json").write_text(json.dumps(evidence, indent=2))
print(json.dumps({"checks": len(checks), "passed": evidence["passed"], "single_response": single,
                  "batch_rows": batch_result["row_count"], "batch_total": batch_result["total_predicted_sales"],
                  "evidence": str(EVIDENCE / "api_verification.json")}, indent=2))
