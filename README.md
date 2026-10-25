# SuperKart Sales Forecast

Low-code model deployment project by Alfred Manasseh, DBA AIML.

The repository contains separate Flask/Gunicorn and Streamlit services. Both use Docker containers connected through a private bridge network. The Streamlit app calls the backend at `http://backend:7860` in Docker. No model is loaded in the frontend.

## Run in GitHub Codespaces

1. Create a Codespace from this repository. Its dev-container configuration installs Docker and runs `docker compose up --build -d`.
2. Check service health with `docker compose ps` and `docker compose logs --tail=50`.
3. Open forwarded port 8501 for the Streamlit interface.
4. For the public assessment API, set the forwarded port 7860 to Public in the Codespaces Ports panel. Copy its HTTPS URL.
5. Submit a single record and the supplied `frontend/Batch_Data_SuperKart.csv` in the UI. Download the predictions to preserve row-level estimates and warnings.

The development image removes an unused Yarn APT source before installing the Docker feature. This avoids an upstream Yarn signing-key failure in the base image. Package signature verification remains enabled; SuperKart does not depend on Yarn.

The forwarded address is specific to the running Codespace. It stops serving when the Codespace is stopped. Keep the Codespace running during assessment, subject to your account's compute quota.

## Run with Docker locally

```bash
docker compose up --build -d
docker compose ps
```

Open http://localhost:8501. Backend health is at http://localhost:7860/health.

## API contract

| Endpoint | Input | Output |
|---|---|---|
| `GET /health` | None | Loaded model status, version and SHA-256 |
| `GET /v1/schema` | None | Feature definitions and training coverage |
| `POST /v1/predict` | One JSON object with 10 features | `Sales`, warnings, version and processing time |
| `POST /v1/predictbatch` | Multipart field `file` containing a CSV | Ordered predictions, row numbers, warnings and aggregate |

The endpoint names match the learner notebook. Responses include additional warning and version metadata. Batch responses use an ordered `predictions` array instead of the template's index-keyed dictionary so each row can carry its own warning. All input rows remain in their original order.

Required columns: `Product_Weight`, `Product_Sugar_Content`, `Product_Allocated_Area`, `Product_MRP`, `Store_Size`, `Store_Location_City_Type`, `Store_Type`, `Product_Id_char`, `Store_Age_Years`, `Product_Type_Category`.

The supplied batch file already has these engineered features. Raw `SuperKart.csv` is training data and is not the upload contract. Store age uses the fixed training reference `2025 - Store_Establishment_Year`. The frontend labels this explicitly.

## Interpretation and scope

The target is revenue for a product-store record in the supplied data's observation period. The dataset has no sales dates and does not identify a currency or period length. The UI therefore displays original revenue units. A next-quarter forecasting claim requires period metadata and out-of-time validation.

The supplied batch contains two unseen `Supermarket Type3` values. Its store-attribute combinations differ from the training profiles. The pipeline can still produce estimates because its encoder ignores unseen categories. These estimates carry explicit review warnings. The batch has no observed target values and demonstrates inference, not validated batch accuracy.

## Validation and safeguards

The API enforces required features, finite numeric values, valid physical ranges, whole-year store age, nonblank categories, a 2 MB upload limit, and a 5,000-row batch limit. It normalizes `reg` to `Regular`. Unknown categories and values outside the training range are flagged. The frontend handles request failures, exposes warnings, and provides a row-preserving CSV download.

Run the HTTP checks against the running API:

```bash
python -m pip install -r backend/requirements.txt requests==2.32.5
BACKEND_URL=http://localhost:7860 python tests/verify_api.py
```

The checks compare the API response against the actual serialized pipeline, validate row ordering, verify extrapolation warnings, and exercise malformed inputs. They write evidence to `evidence/`.

Check the actual containers and the frontend-to-backend connection separately:

```bash
docker compose ps
docker compose exec -T frontend python -c "import requests; r=requests.get('http://backend:7860/health', timeout=10); r.raise_for_status(); print(r.json())"
```

`tests/capture_frontend.cjs` is an optional browser test for an environment with Node.js, Playwright and its Chromium browser installed. It accepts `FRONTEND_URL`, uses Playwright's normal browser installation, and optionally accepts `CHROME_EXECUTABLE`. It writes UI evidence without changing the separately verified deployment status. Evidence generated against localhost only demonstrates local functionality; record the actual forwarded URLs and container state when assessing the Codespaces deployment.

This is an educational deployment with a public assessment endpoint. An enterprise rollout should add authentication, authorization, rate limits, monitoring, data retention controls, and operational ownership before connecting sensitive customer data.

## Official implementation references

- [Flask production deployment](https://flask.palletsprojects.com/en/stable/deploying/)
- [Gunicorn with Flask](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/)
- [Streamlit Docker deployment](https://docs.streamlit.io/deploy/tutorials/docker)
- [GitHub Codespaces forwarded ports](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace)
