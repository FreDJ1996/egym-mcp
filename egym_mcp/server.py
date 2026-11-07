"""MCP server for the EGYM Fitness app: workouts, strength, bio age, body metrics, own training plans and notes."""

import datetime
import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import egym

DATA_DIR = Path(os.environ.get("EGYM_MCP_DATA_DIR", Path.home() / ".egym-mcp")).expanduser()
load_dotenv(DATA_DIR / ".env")

NOTES_FILE = Path(os.environ.get("EGYM_MCP_NOTES_FILE", DATA_DIR / "training_notes.md"))
CATALOG_FILE = Path(os.environ.get("EGYM_MCP_CATALOG_FILE", DATA_DIR / "exercise_catalog.json"))
COACH_DIR = Path(os.environ.get("EGYM_MCP_COACH_DIR", DATA_DIR / "coach"))
DROP_KEYS = {
    "imageUrl", "thumbnailUrl", "iconUrl", "images", "icon", "image", "videoUrl", "deepLink", "workoutPlanImageUrl",
    "description", "id", "netpulseWorkoutId", "netpulseWorkoutExerciseId", "deletable", "editable", "status", "met",
}
LOCALE = os.environ.get("EGYM_LOCALE", "en-GB")
LANG = LOCALE.split("-")[0]

mcp = MCPServer(
    "egym",
    instructions=(
        "Reads workouts, strength values, bio age and body metrics from the user's EGYM account, creates the user's "
        "own training plans in the app (save_plan, delete_plan; only plans of type USER_TRAINING_PLAN) and keeps "
        "training notes for what EGYM does not record. Before planning or reviewing training, call get_coach_context "
        "unless the coach files are already loaded, for example as a skill."
    ),
)

_api: egym.Api | None = None
_api_lock = threading.Lock()


def api() -> egym.Api:
    global _api
    with _api_lock:
        if _api is None:
            email, password = os.environ.get("EGYM_EMAIL"), os.environ.get("EGYM_PASSWORD")
            if not email or not password:
                raise ToolError(f"EGYM_EMAIL / EGYM_PASSWORD are missing; set them in {DATA_DIR / '.env'}")
            try:
                _api = egym.Api(
                    email=email,
                    password=password,
                    locale=LOCALE,
                    base_url=os.environ.get("EGYM_BASE_URL") or None,
                )
            except egym.EgymError as exc:
                raise ToolError(f"EGYM login failed: {type(exc).__name__}: {exc}") from exc
        return _api


def _egym(method: str, *args):
    """Calls an egym.Api method; EGYM errors reach the model as a readable message."""
    global _api
    try:
        return getattr(api(), method)(*args)
    except egym.EgymError as exc:
        if isinstance(exc, egym.AuthenticationError):
            _api = None
        raise ToolError(f"EGYM: {type(exc).__name__}: {exc}") from exc


def _slim_activity(activity: dict) -> dict:
    """Reduces EGYM's exercise definition (~40 fields) to what matters for planning."""
    muscles = activity.get("muscleMapping") or {}
    return {
        "activityId": activity.get("activityId"),
        "name": activity.get("name"),
        "category": activity.get("category"),
        "movements": activity.get("basicMovements"),
        "laterality": activity.get("laterality"),
        "muscles": sorted(muscles, key=lambda m: -muscles[m])[:5],
    }


def _prune(value):
    """Removes empty values and image/link fields so they do not fill the context window."""
    if isinstance(value, dict):
        if LANG in value and all(len(k) == 2 for k in value):
            return value[LANG]  # translated texts {"de": ..., "en": ..., ...}
        if "activityId" in value and "muscleMapping" in value:
            value = _slim_activity(value)
        pruned = {k: _prune(v) for k, v in value.items() if k not in DROP_KEYS}
        return {k: v for k, v in pruned.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _out(value) -> str:
    return json.dumps(_prune(value), ensure_ascii=False, separators=(",", ":"))


def _date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(value)


def _today() -> datetime.date:
    return datetime.date.today()


@mcp.tool()
def get_recent_workouts(days: int = 14) -> str:
    """Completed workouts of the last `days` days (including today) with exercises, sets, weights and reps."""
    return _out(_egym("get_workouts", _today() - datetime.timedelta(days=days - 1), _today()))


@mcp.tool()
def get_workouts(start_date: str, end_date: str) -> str:
    """Completed workouts between start_date and end_date (ISO format YYYY-MM-DD, both included)."""
    return _out(_egym("get_workouts", _date(start_date), _date(end_date)))


def _with_workout_end(check_ins: list, workouts: list) -> list:
    """Adds the end of the day's last workout and the minutes from check-in to it (both are local times)."""
    ends = {}
    for workout in workouts:
        completed = workout.get("completedAt") or ""
        ends[completed[:10]] = max(ends.get(completed[:10], ""), completed)
    result = []
    for check_in in check_ins:
        entry = {
            "checkIn": check_in["checkInDate"],
            "gym": check_in.get("gymLocationName"),
            "durationMs": check_in.get("duration"),
        }
        end = ends.get(check_in["checkInDate"][:10])
        if end:
            minutes = datetime.datetime.fromisoformat(end) - datetime.datetime.fromisoformat(check_in["checkInDate"])
            entry["workoutCompletedAt"] = end[:19]
            entry["minutesToWorkoutEnd"] = round(minutes.total_seconds() / 60)
        result.append(entry)
    return result


@mcp.tool()
def get_check_ins(days: int = 30) -> str:
    """Gym check-ins (turnstile) of the last `days` days, oldest first, with gym and local check-in time.

    Shows every gym visit, also days with only EGYM circuit training that have no workout entry.
    If a workout was completed in the app that day, workoutCompletedAt and minutesToWorkoutEnd give the time from
    check-in to the end of the workout; the app logs the end when the user finishes the workout, which can be later
    than the last set. durationMs (check-out) is only set if the gym reports check-outs.
    """
    start, end = _today() - datetime.timedelta(days=days - 1), _today()
    return _out(_with_workout_end(_egym("get_check_ins", start, end), _egym("get_workouts", start, end)))


@mcp.tool()
def get_strength_status() -> str:
    """Current EGYM maximum strength per machine/exercise (activityId for get_strength_history)."""
    return _out(_egym("get_latest_strength_metrics"))


@mcp.tool()
def get_strength_history(days: int = 180, activity_id: int | None = None) -> str:
    """EGYM strength measurements over `days` days, optionally for one activityId."""
    return _out(_egym("get_strength_measurements", _today() - datetime.timedelta(days=days), _today(), activity_id))


@mcp.tool()
def get_bio_age() -> str:
    """Current bio age with its parts (muscle, metabolism, cardio, flexibility), including flexibility measurements."""
    return _out(_egym("get_bio_age"))


@mcp.tool()
def get_bio_age_history(period: str = "month", shift: int = 0) -> str:
    """Bio age per month or year (period: 'month' | 'year'; shift: periods back, 0 = current)."""
    return _out(_egym("get_bio_age_summary", period, shift))


def _flexibility_angles(latest: list, history: list) -> list:
    """Per flexibility angle (…_DEGREE): latest value, EGYM's rating and the history of all measurements."""
    histories = {entry["type"]: entry.get("history") or [] for entry in history}
    return [
        {
            "type": metric["type"],
            "degree": round(metric["value"], 1),
            "rating": metric.get("valueInterpretation"),
            "measuredAt": metric.get("createdAt"),
            "history": [
                {"date": item["date"], "degree": round(item["value"], 1)} for item in histories.get(metric["type"], [])
            ],
        }
        for metric in sorted(latest, key=lambda m: m["type"])
        if metric["type"].endswith("_DEGREE")
    ]


@mcp.tool()
def get_flexibility(days: int = 365) -> str:
    """Flexibility angles in degrees from the EGYM flexibility measurement (hip and hamstring extension, chest,
    torso and neck lateral flexion, left/right), each with EGYM's rating and the history over `days` days."""
    latest = _egym("get_latest_flexibility_metrics")
    types = sorted({m["type"] for m in latest if m["type"].endswith("_DEGREE")})
    if not types:
        return "(no flexibility measurement yet)"
    start = _today() - datetime.timedelta(days=days)
    history = _egym("get_flexibility_history", types, start, _today(), "ONE_ITEM_PER_DAY")
    return _out(_flexibility_angles(latest, history))


@mcp.tool()
def get_squat_analysis(days: int = 365) -> str:
    """Squat scans of the EGYM Fitness Hub over `days` days: squat depth (share), back and shoulder angle (degrees),
    each with EGYM's rating."""
    return _out(_egym("get_squat_history", _today() - datetime.timedelta(days=days), _today(), "ONE_ITEM_PER_DAY"))


@mcp.tool()
def get_body_composition() -> str:
    """Latest body metrics (weight, body fat, muscle mass, BIA values and so on)."""
    return _out(_egym("get_latest_body_metrics"))


@mcp.tool()
def get_body_metric_history(types: list[str], days: int = 180) -> str:
    """History of single body metrics, e.g. types=['WEIGHT_KG','BODY_FAT_PERCENTS'] (names from get_body_composition)."""
    return _out(
        _egym("get_body_metrics", types, _today() - datetime.timedelta(days=days), _today(), "ONE_ITEM_PER_DAY")
    )


@mcp.tool()
def get_muscle_imbalances() -> str:
    """EGYM's analysis of muscle imbalances (agonist/antagonist, left/right)."""
    return _out(_egym("get_muscle_imbalances"))


@mcp.tool()
def get_activity_level() -> str:
    """Activity level, points and weekly goal."""
    return _out(_egym("get_activity_level"))


CATALOG_MAX_AGE = datetime.timedelta(days=90)
CATALOG_KEYS = ("activityId", "name", "category", "basicMovements", "laterality", "muscleMapping", "synonyms")
_catalog: list | None = None


def _load_catalog(refresh: bool = False) -> list:
    """Exercise catalogue from the local file; fetched from EGYM the first time, after 90 days or on request."""
    global _catalog
    if not refresh and _catalog is None and CATALOG_FILE.exists():
        age = datetime.datetime.now() - datetime.datetime.fromtimestamp(CATALOG_FILE.stat().st_mtime)
        if age < CATALOG_MAX_AGE:
            _catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    if refresh or _catalog is None:
        _catalog = [{k: a.get(k) for k in CATALOG_KEYS} for a in _egym("get_activities")]
        CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CATALOG_FILE.write_text(json.dumps(_catalog, ensure_ascii=False), encoding="utf-8")
    return _catalog


@mcp.tool()
def search_exercises(query: str, category: str | None = None, limit: int = 15, refresh: bool = False) -> str:
    """Searches EGYM's exercise catalogue (~1200 exercises) for the exact name an exercise has in the app.

    All words in `query` must appear in the local or English name (e.g. 'dumbbell bench', 'pullover', 'face pull').
    Optionally filter by `category`, e.g. FREE_WEIGHTS, BODY_WEIGHT_BASED, WEIGHT_MACHINE_BASED, EGYM_MACHINE,
    MOBILITY, STRETCHING, ROWING. `appName` is the name in the app.
    The catalogue is cached locally; `refresh=True` fetches it again from EGYM (only for missing exercises).
    """
    words = query.lower().split()
    hits = []
    for activity in _load_catalog(refresh):
        if category and activity.get("category") != category.upper():
            continue
        names = activity.get("name") or {}
        local, english = names.get(LANG) or "-", names.get("en") or ""
        haystack = f"{local} {english} {' '.join(activity.get('synonyms') or [])}".lower()
        if all(w in haystack for w in words):
            hit = _slim_activity(activity)
            hit["appName"] = (local if local != "-" else english).strip()
            hit["name"] = english
            hits.append(hit)
    hits.sort(key=lambda h: len(h["appName"]))
    return _out(hits[:limit]) if hits else f"No exercise found for '{query}'."


OWN_PLAN = "USER_TRAINING_PLAN"


def _app_name(activity_id) -> str | None:
    for activity in _load_catalog():
        if activity.get("activityId") == activity_id:
            names = activity.get("name") or {}
            return (names.get(LANG) or names.get("en") or "").strip() or None
    return None


def _slim_plan(plan: dict) -> dict:
    """Plan with planId and, per exercise, exerciseId, activityId, appName and sets (without empty fields)."""
    exercises = []
    for exercise in plan.get("plannedExercises") or []:
        activity_id = (exercise.get("activity") or {}).get("activityId")
        exercises.append({
            "exerciseId": exercise.get("id"),
            "activityId": activity_id,
            "appName": _app_name(activity_id),
            "sets": _prune(exercise.get("sets") or []),
        })
    return {"planId": plan.get("id"), "name": plan.get("name"), "type": plan.get("type"), "exercises": exercises}


def _own_plans() -> dict:
    return {p["id"]: p for p in _egym("get_available_plans") if p.get("type") == OWN_PLAN}


def _require_own_plan(plan_id: int) -> dict:
    plan = _own_plans().get(plan_id)
    if plan is None:
        raise ToolError(f"Plan {plan_id} is not one of the user's own plans ({OWN_PLAN}).")
    return plan


def _plan_exercises(exercises: list[dict]) -> list[dict]:
    """Adds setType (TIME_BASED for duration without numberOfReps, else REP_BASED) and checks required fields."""
    if not exercises:
        raise ToolError("A plan needs at least one exercise.")
    result = []
    for exercise in exercises:
        if not exercise.get("activityId") or not exercise.get("sets"):
            raise ToolError(f"Every exercise needs an activityId and at least one set: {exercise}")
        sets = []
        for item in exercise["sets"]:
            item = {k: v for k, v in item.items() if v is not None}
            if "setType" not in item:
                timed = "duration" in item and "numberOfReps" not in item
                item["setType"] = "TIME_BASED" if timed else "REP_BASED"
            sets.append(item)
        result.append({**exercise, "sets": sets})
    return result


@mcp.tool()
def get_available_plans(own_only: bool = False) -> str:
    """Training plans in the app with planId: the user's own (USER_TRAINING_PLAN), from trainers and gym templates.
    own_only=True returns only the user's own plans. Sets here can show the values last trained;
    get_plan returns the stored ones."""
    plans = _egym("get_available_plans")
    return _out([_slim_plan(p) for p in plans if not own_only or p.get("type") == OWN_PLAN])


@mcp.tool()
def get_plan(plan_id: int) -> str:
    """Details of a plan (any type) with all exercises and sets."""
    return _out(_slim_plan(_egym("get_plan", plan_id)))


@mcp.tool()
def save_plan(name: str, exercises: list[dict], plan_id: int | None = None) -> str:
    """Creates an own training plan in the EGYM app or replaces an existing one (plan_id).

    exercises: list in training order, each {"activityId": <from search_exercises>, "sets": [...]}.
    Every set is its own entry, with the fields:
      numberOfReps (int), weight (kg, per dumbbell for two dumbbells; required for strength exercises unless
      body-weight based), recoveryTime (rest in s), duration (s, for timed sets such as cardio or stretching),
      optionally distance (m), speed, incline, heartRate, sideMode ('BOTH'|'LEFT'|'RIGHT'),
      trainingMethod (EGYM machines), setType (added if missing).
    Example: {"activityId": 95, "sets": [{"numberOfReps": 8, "weight": 22, "recoveryTime": 120}]}
    Replacing overwrites the whole plan; only replace plans the user has agreed to change.
    """
    exercises = _plan_exercises(exercises)
    if plan_id is not None:
        _require_own_plan(plan_id)
        _egym("update_personal_plan", plan_id, name, exercises)
        return f"Plan {plan_id} '{name}' updated ({len(exercises)} exercises)."
    before = set(_own_plans())
    _egym("create_personal_plan", name, exercises)
    new = [pid for pid, p in _own_plans().items() if pid not in before and p.get("name") == name]
    created = f" with planId {new[0]}" if len(new) == 1 else ""
    return f"Plan '{name}'{created} created ({len(exercises)} exercises)."


@mcp.tool()
def delete_plan(plan_id: int) -> str:
    """Permanently deletes an own training plan (USER_TRAINING_PLAN only). Only after the user has confirmed."""
    name = _require_own_plan(plan_id).get("name")
    _egym("delete_personal_plan", plan_id)
    return f"Plan {plan_id} '{name}' deleted."


@mcp.tool()
def get_coach_context() -> str:
    """Coaching context from the user's Markdown files in the coach folder: role, planning rules, athlete profile.
    Call this first before planning or reviewing training, unless these files are already loaded."""
    paths = sorted(COACH_DIR.glob("*.md"), key=lambda path: (path.name != "SKILL.md", path.name))
    if not paths:
        return f"(no coach files in {COACH_DIR}; plan from the EGYM data and ask the user for goals and limits)"
    return "\n\n".join(f"===== {path.name} =====\n{path.read_text(encoding='utf-8').strip()}" for path in paths)


@mcp.tool()
def read_training_notes() -> str:
    """Training notes: runs, how the user felt, mobility impressions, free-weight loads that are not in EGYM."""
    return NOTES_FILE.read_text(encoding="utf-8") if NOTES_FILE.exists() else "(no notes yet)"


@mcp.tool()
def add_training_note(text: str, date: str | None = None) -> str:
    """Adds an entry to the training notes (date: YYYY-MM-DD, today by default)."""
    day = _date(date) if date else _today()
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with NOTES_FILE.open("a", encoding="utf-8") as f:
        f.write(f"- **{day.isoformat()}**: {text.strip()}\n")
    return f"Noted for {day.isoformat()}."


def main():
    mcp.run()


if __name__ == "__main__":
    main()
