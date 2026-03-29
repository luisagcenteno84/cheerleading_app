# Cheer Competition Manager

MVP web app for cheerleading competition management: event setup, team registration, judge scoring, and live results.

## Stack
- Backend: FastAPI
- Frontend: Streamlit
- DB: Firestore
- Hosting: Cloud Run (us-west4)
- CI/CD: Cloud Build

## Local Development

### Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set JWT_SECRET=dev-secret
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set API_BASE_URL=http://localhost:8000
streamlit run app.py
```

## Cloud Build Deployment
1. Set substitutions in `cloudbuild.yaml` for `_JWT_SECRET` and `_API_BASE_URL`.
2. Run Cloud Build:
```bash
gcloud builds submit --config cloudbuild.yaml
```

## Notes
- First-time setup: use the Streamlit "Bootstrap Admin" form to create the initial admin account.
- Tie-breaker: higher **Execution** category total wins.
- Production deployment is pinned to **us-west4** to control costs.
