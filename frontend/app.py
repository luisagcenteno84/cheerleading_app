import os
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(page_title="Cheer Competition Manager", layout="wide")


def api_request(method, path, token=None, json=None, params=None):
    url = f"{API_BASE_URL}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.request(method, url, headers=headers, json=json, params=params, timeout=20)
    return resp


def login_view():
    st.title("Cheer Competition Manager")
    st.subheader("Sign in")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
    if submit:
        resp = api_request("POST", "/auth/login", json={"email": email, "password": password})
        if resp.ok:
            token = resp.json()["access_token"]
            st.session_state["token"] = token
            st.experimental_rerun()
        else:
            st.error(resp.text)

    st.divider()
    st.subheader("Bootstrap Admin (first-time setup)")
    with st.form("bootstrap_form"):
        admin_email = st.text_input("Admin Email")
        admin_password = st.text_input("Admin Password", type="password")
        create = st.form_submit_button("Create Admin")
    if create:
        resp = api_request("POST", "/auth/register", json={"email": admin_email, "password": admin_password, "role": "admin"})
        if resp.ok:
            token = resp.json()["access_token"]
            st.session_state["token"] = token
            st.success("Admin created.")
            st.experimental_rerun()
        else:
            st.error(resp.text)


def load_me(token):
    resp = api_request("GET", "/auth/me", token=token)
    if resp.ok:
        return resp.json()
    return None


def list_events():
    resp = api_request("GET", "/events")
    return resp.json() if resp.ok else []


def list_divisions(event_id):
    resp = api_request("GET", f"/events/{event_id}/divisions")
    return resp.json() if resp.ok else []


def list_teams(event_id, division_id):
    resp = api_request("GET", f"/events/{event_id}/divisions/{division_id}/teams")
    return resp.json() if resp.ok else []


def list_results(event_id, division_id):
    resp = api_request("GET", f"/events/{event_id}/divisions/{division_id}/results")
    return resp.json() if resp.ok else []


def admin_dashboard(token):
    st.header("Admin Dashboard")

    with st.expander("Create Event", expanded=True):
        with st.form("create_event"):
            name = st.text_input("Event Name")
            location = st.text_input("Location")
            date = st.text_input("Date (YYYY-MM-DD)")
            status = st.selectbox("Status", ["draft", "published"], index=0)
            submit = st.form_submit_button("Create Event")
        if submit:
            resp = api_request("POST", "/events", token=token, json={"name": name, "location": location, "date": date, "status": status})
            st.success("Event created") if resp.ok else st.error(resp.text)

    events = list_events()
    if not events:
        st.info("No events yet.")
        return

    event_names = {f"{e['name']} ({e['date']})": e for e in events}
    selected_event_key = st.selectbox("Select Event", list(event_names.keys()))
    event = event_names[selected_event_key]

    st.subheader("Divisions")
    divisions = list_divisions(event["id"])
    if divisions:
        st.dataframe(divisions, use_container_width=True)

    with st.expander("Create Division", expanded=True):
        with st.form("create_division"):
            d_name = st.text_input("Division Name")
            age_group = st.text_input("Age Group")
            skill_level = st.text_input("Skill Level")
            category = st.text_input("Category")
            criteria = st.text_input("Scoring Criteria (comma-separated)", value="Difficulty,Execution,Creativity")
            weights_raw = st.text_input("Weights (e.g., Difficulty=1,Execution=1,Creativity=1)", value="Difficulty=1,Execution=1,Creativity=1")
            submit = st.form_submit_button("Create Division")
        if submit:
            scoring_criteria = [c.strip() for c in criteria.split(",") if c.strip()]
            weights = {}
            for pair in weights_raw.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    weights[k.strip()] = float(v.strip())
            payload = {
                "name": d_name,
                "age_group": age_group,
                "skill_level": skill_level,
                "category": category,
                "scoring_criteria": scoring_criteria,
                "weights": weights,
            }
            resp = api_request("POST", f"/events/{event['id']}/divisions", token=token, json=payload)
            st.success("Division created") if resp.ok else st.error(resp.text)

    st.subheader("Create Users")
    with st.form("create_user"):
        email = st.text_input("User Email")
        password = st.text_input("User Password", type="password")
        role = st.selectbox("Role", ["coach", "judge", "admin"])
        submit = st.form_submit_button("Create User")
    if submit:
        resp = api_request("POST", "/auth/register", token=token, json={"email": email, "password": password, "role": role})
        st.success("User created") if resp.ok else st.error(resp.text)


def coach_dashboard(token):
    st.header("Coach Dashboard")
    events = list_events()
    if not events:
        st.info("No events available.")
        return

    event_names = {f"{e['name']} ({e['date']})": e for e in events}
    selected_event_key = st.selectbox("Select Event", list(event_names.keys()))
    event = event_names[selected_event_key]
    divisions = list_divisions(event["id"])
    if not divisions:
        st.info("No divisions available.")
        return

    division_names = {d["name"]: d for d in divisions}
    selected_division_key = st.selectbox("Select Division", list(division_names.keys()))
    division = division_names[selected_division_key]

    with st.form("register_team"):
        team_name = st.text_input("Team Name")
        participants = st.number_input("Participants Count", min_value=1, value=10)
        submit = st.form_submit_button("Register Team")
    if submit:
        payload = {"team_name": team_name, "division_id": division["id"], "participants_count": participants}
        resp = api_request("POST", f"/events/{event['id']}/divisions/{division['id']}/teams", token=token, json=payload)
        st.success("Team registered") if resp.ok else st.error(resp.text)

    st.subheader("Teams in Division")
    teams = list_teams(event["id"], division["id"])
    if teams:
        st.dataframe(teams, use_container_width=True)


def judge_dashboard(token):
    st.header("Judge Scoring")
    events = list_events()
    if not events:
        st.info("No events available.")
        return

    event_names = {f"{e['name']} ({e['date']})": e for e in events}
    selected_event_key = st.selectbox("Select Event", list(event_names.keys()))
    event = event_names[selected_event_key]

    divisions = list_divisions(event["id"])
    if not divisions:
        st.info("No divisions available.")
        return

    division_names = {d["name"]: d for d in divisions}
    selected_division_key = st.selectbox("Select Division", list(division_names.keys()))
    division = division_names[selected_division_key]

    teams = list_teams(event["id"], division["id"])
    if not teams:
        st.info("No teams in this division.")
        return

    team_names = {t["team_name"]: t for t in teams}
    selected_team_key = st.selectbox("Select Team", list(team_names.keys()))
    team = team_names[selected_team_key]

    st.subheader("Enter Scores (1-5)")
    scores = {}
    cols = st.columns(len(division["scoring_criteria"]))
    for idx, cat in enumerate(division["scoring_criteria"]):
        with cols[idx]:
            scores[cat] = st.number_input(cat, min_value=1, max_value=5, value=3)

    if st.button("Submit Score"):
        payload = {"team_id": team["id"], "scores_by_category": scores}
        resp = api_request("POST", f"/events/{event['id']}/divisions/{division['id']}/scores", token=token, json=payload)
        if resp.ok:
            st.success("Score submitted")
        else:
            st.error(resp.text)


def public_results():
    st.header("Public Results")
    events = list_events()
    if not events:
        st.info("No events available.")
        return

    event_names = {f"{e['name']} ({e['date']})": e for e in events}
    selected_event_key = st.selectbox("Select Event", list(event_names.keys()), key="public_event")
    event = event_names[selected_event_key]

    divisions = list_divisions(event["id"])
    if not divisions:
        st.info("No divisions available.")
        return

    division_names = {d["name"]: d for d in divisions}
    selected_division_key = st.selectbox("Select Division", list(division_names.keys()), key="public_division")
    division = division_names[selected_division_key]

    results = list_results(event["id"], division["id"])
    if results:
        st.dataframe(results, use_container_width=True)
    else:
        st.info("No results yet.")


def main():
    token = st.session_state.get("token")
    if not token:
        login_view()
        return

    user = load_me(token)
    if not user:
        st.session_state.pop("token", None)
        login_view()
        return

    st.sidebar.write(f"Logged in as {user['email']} ({user['role']})")
    if st.sidebar.button("Logout"):
        st.session_state.pop("token", None)
        st.experimental_rerun()

    role = user["role"]

    if role == "admin":
        admin_dashboard(token)
    elif role == "coach":
        coach_dashboard(token)
    elif role == "judge":
        judge_dashboard(token)

    st.divider()
    public_results()


if __name__ == "__main__":
    main()
