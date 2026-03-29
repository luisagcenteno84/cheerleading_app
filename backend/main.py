from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from google.cloud import firestore


JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "24"))
FIRESTORE_PROJECT = os.getenv("FIRESTORE_PROJECT")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="Cheerleading Competition API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> firestore.Client:
    return firestore.Client(project=FIRESTORE_PROJECT) if FIRESTORE_PROJECT else firestore.Client()


# -----------------
# Models
# -----------------
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: str
    role: str
    email: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    role: str = Field(..., description="admin|coach|judge")


class EventCreate(BaseModel):
    name: str
    location: str
    date: str
    status: str = "draft"


class EventOut(BaseModel):
    id: str
    name: str
    location: str
    date: str
    status: str


class DivisionCreate(BaseModel):
    name: str
    age_group: str
    skill_level: str
    category: str
    scoring_criteria: List[str]
    weights: Dict[str, float]


class DivisionOut(DivisionCreate):
    id: str


class TeamCreate(BaseModel):
    team_name: str
    division_id: str
    participants_count: int
    order: Optional[int] = None


class TeamOut(BaseModel):
    id: str
    team_name: str
    coach_id: str
    participants_count: int
    order: int


class ScoreCreate(BaseModel):
    team_id: str
    scores_by_category: Dict[str, float]


class ScoreOut(BaseModel):
    id: str
    team_id: str
    judge_id: str
    scores_by_category: Dict[str, float]
    total_score: float
    submitted_at: str


class ResultOut(BaseModel):
    team_id: str
    avg_score: float
    execution_total: float
    rank: int


# -----------------
# Auth helpers
# -----------------

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=TOKEN_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def get_current_user_optional(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth header")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    return {"id": payload["sub"], "role": payload["role"]}


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing auth header")
    return user


def require_role(required: List[str]):
    def _inner(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in required:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _inner


# -----------------
# Auth endpoints
# -----------------
@app.post("/auth/login", response_model=TokenResponse)
def login(data: LoginRequest):
    db = get_db()
    users_ref = db.collection("users").where("email", "==", data.email).limit(1).stream()
    user_doc = next(users_ref, None)
    if not user_doc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user = user_doc.to_dict()
    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_token(user_doc.id, user["role"])
    return TokenResponse(access_token=token)


@app.post("/auth/register", response_model=TokenResponse)
def register(data: RegisterRequest, user: Optional[dict] = Depends(get_current_user_optional)):
    db = get_db()
    users_col = db.collection("users")

    # Allow bootstrap if no users exist
    existing_users = list(users_col.limit(1).stream())
    if existing_users:
        if not user or user["role"] != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")

    if data.role not in {"admin", "coach", "judge"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    existing = users_col.where("email", "==", data.email).limit(1).stream()
    if next(existing, None):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    doc_ref = users_col.document()
    doc_ref.set({
        "email": data.email,
        "password_hash": hash_password(data.password),
        "role": data.role,
        "created_at": datetime.utcnow().isoformat(),
        "status": "active",
    })

    token = create_token(doc_ref.id, data.role)
    return TokenResponse(access_token=token)


@app.get("/auth/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    db = get_db()
    doc = db.collection("users").document(user["id"]).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    data = doc.to_dict()
    return UserOut(id=doc.id, role=data["role"], email=data["email"])


# -----------------
# Events
# -----------------
@app.get("/events", response_model=List[EventOut])
def list_events():
    db = get_db()
    events = []
    for doc in db.collection("events").stream():
        data = doc.to_dict()
        events.append(EventOut(id=doc.id, **data))
    return events


@app.post("/events", response_model=EventOut)
def create_event(data: EventCreate, user: dict = Depends(require_role(["admin"]))):
    db = get_db()
    doc_ref = db.collection("events").document()
    payload = data.dict()
    payload["created_by"] = user["id"]
    doc_ref.set(payload)
    return EventOut(id=doc_ref.id, **data.dict())


@app.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: str):
    db = get_db()
    doc = db.collection("events").document(event_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventOut(id=doc.id, **doc.to_dict())


# -----------------
# Divisions
# -----------------
@app.get("/events/{event_id}/divisions", response_model=List[DivisionOut])
def list_divisions(event_id: str):
    db = get_db()
    divisions = []
    for doc in db.collection("events").document(event_id).collection("divisions").stream():
        divisions.append(DivisionOut(id=doc.id, **doc.to_dict()))
    return divisions


@app.post("/events/{event_id}/divisions", response_model=DivisionOut)
def create_division(event_id: str, data: DivisionCreate, user: dict = Depends(require_role(["admin"]))):
    db = get_db()
    doc_ref = db.collection("events").document(event_id).collection("divisions").document()
    doc_ref.set(data.dict())
    return DivisionOut(id=doc_ref.id, **data.dict())


# -----------------
# Teams
# -----------------
@app.get("/events/{event_id}/divisions/{division_id}/teams", response_model=List[TeamOut])
def list_teams(event_id: str, division_id: str):
    db = get_db()
    teams = []
    teams_ref = db.collection("events").document(event_id).collection("divisions").document(division_id).collection("teams")
    for doc in teams_ref.order_by("order").stream():
        data = doc.to_dict()
        teams.append(TeamOut(id=doc.id, **data))
    return teams


@app.post("/events/{event_id}/divisions/{division_id}/teams", response_model=TeamOut)
def create_team(event_id: str, division_id: str, data: TeamCreate, user: dict = Depends(require_role(["coach", "admin"]))):
    db = get_db()
    teams_ref = db.collection("events").document(event_id).collection("divisions").document(division_id).collection("teams")

    order = data.order
    if order is None:
        last_team = list(teams_ref.order_by("order", direction=firestore.Query.DESCENDING).limit(1).stream())
        order = (last_team[0].to_dict().get("order", 0) + 1) if last_team else 1

    doc_ref = teams_ref.document()
    payload = {
        "team_name": data.team_name,
        "coach_id": user["id"],
        "participants_count": data.participants_count,
        "order": order,
        "created_at": datetime.utcnow().isoformat(),
    }
    doc_ref.set(payload)
    return TeamOut(id=doc_ref.id, **payload)


@app.patch("/events/{event_id}/divisions/{division_id}/teams/{team_id}", response_model=TeamOut)
def update_team_order(event_id: str, division_id: str, team_id: str, order: int, user: dict = Depends(require_role(["admin"]))):
    db = get_db()
    doc_ref = db.collection("events").document(event_id).collection("divisions").document(division_id).collection("teams").document(team_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    data = doc.to_dict()
    data["order"] = order
    doc_ref.update({"order": order})
    return TeamOut(id=doc.id, **data)


# -----------------
# Scores & Results
# -----------------

def compute_results(event_id: str, division_id: str) -> List[ResultOut]:
    db = get_db()
    division_ref = db.collection("events").document(event_id).collection("divisions").document(division_id)
    division_doc = division_ref.get()
    if not division_doc.exists:
        raise HTTPException(status_code=404, detail="Division not found")
    division = division_doc.to_dict()
    criteria = division.get("scoring_criteria", [])
    weights = division.get("weights", {})

    teams_ref = division_ref.collection("teams")
    teams = {doc.id: doc.to_dict() for doc in teams_ref.stream()}

    scores_ref = division_ref.collection("scores")
    scores = {}
    for doc in scores_ref.stream():
        score = doc.to_dict()
        scores.setdefault(score["team_id"], []).append(score)

    results: List[ResultOut] = []
    for team_id, team_data in teams.items():
        team_scores = scores.get(team_id, [])
        if not team_scores:
            avg_score = 0.0
            execution_total = 0.0
        else:
            totals = []
            execution_total = 0.0
            for s in team_scores:
                total = 0.0
                for c in criteria:
                    val = float(s["scores_by_category"].get(c, 0))
                    weight = float(weights.get(c, 1.0))
                    total += val * weight
                    if c.lower() == "execution":
                        execution_total += val
                totals.append(total)
            avg_score = sum(totals) / len(totals)

        results.append(ResultOut(team_id=team_id, avg_score=round(avg_score, 3), execution_total=round(execution_total, 3), rank=0))

    results.sort(key=lambda r: (-r.avg_score, -r.execution_total, teams[r.team_id].get("order", 9999)))
    for idx, r in enumerate(results, start=1):
        r.rank = idx

    # Persist results
    results_ref = division_ref.collection("results")
    batch = db.batch()
    for r in results:
        doc_ref = results_ref.document(r.team_id)
        batch.set(doc_ref, {
            "team_id": r.team_id,
            "avg_score": r.avg_score,
            "execution_total": r.execution_total,
            "rank": r.rank,
            "updated_at": datetime.utcnow().isoformat(),
        })
    batch.commit()

    return results


@app.post("/events/{event_id}/divisions/{division_id}/scores", response_model=ScoreOut)
def submit_score(event_id: str, division_id: str, data: ScoreCreate, user: dict = Depends(require_role(["judge"]))):
    db = get_db()
    scores_ref = db.collection("events").document(event_id).collection("divisions").document(division_id).collection("scores")

    existing = scores_ref.where("team_id", "==", data.team_id).where("judge_id", "==", user["id"]).limit(1).stream()
    if next(existing, None):
        raise HTTPException(status_code=409, detail="Score already submitted")

    for k, v in data.scores_by_category.items():
        if v < 1 or v > 5:
            raise HTTPException(status_code=400, detail=f"Score for {k} must be 1-5")

    total_score = sum(float(v) for v in data.scores_by_category.values())
    payload = {
        "team_id": data.team_id,
        "judge_id": user["id"],
        "scores_by_category": data.scores_by_category,
        "total_score": total_score,
        "submitted_at": datetime.utcnow().isoformat(),
    }

    doc_ref = scores_ref.document()
    doc_ref.set(payload)

    compute_results(event_id, division_id)

    return ScoreOut(id=doc_ref.id, **payload)


@app.get("/events/{event_id}/divisions/{division_id}/results", response_model=List[ResultOut])
def get_results(event_id: str, division_id: str):
    db = get_db()
    results_ref = db.collection("events").document(event_id).collection("divisions").document(division_id).collection("results")
    existing = list(results_ref.stream())
    if not existing:
        return compute_results(event_id, division_id)
    results = [ResultOut(**doc.to_dict()) for doc in existing]
    results.sort(key=lambda r: r.rank)
    return results


@app.get("/health")
def health():
    return {"status": "ok", "ts": int(time.time())}






