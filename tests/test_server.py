import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from egym_mcp import server

OWN = {"id": 1, "name": "Mine", "type": "USER_TRAINING_PLAN"}
GYM = {"id": 2, "name": "Gym", "type": "GLOBAL_TEMPLATE"}


@pytest.fixture
def calls(monkeypatch):
    log = []

    def fake(method, *args):
        log.append((method, *args))
        return [OWN, GYM] if method == "get_available_plans" else None

    monkeypatch.setattr(server, "_egym", fake)
    return log


@pytest.mark.parametrize(
    "item, expected",
    [
        ({"numberOfReps": 8, "weight": 10}, "REP_BASED"),
        ({"duration": 60}, "TIME_BASED"),
        ({"duration": 60, "numberOfReps": 8}, "REP_BASED"),
        ({"setType": "TIME_BASED", "numberOfReps": 8}, "TIME_BASED"),
    ],
)
def test_plan_exercises_sets_type(item, expected):
    result = server._plan_exercises([{"activityId": 95, "sets": [item]}])
    assert result[0]["sets"][0]["setType"] == expected


@pytest.mark.parametrize("exercises", [[], [{"activityId": 95, "sets": []}], [{"sets": [{"duration": 60}]}]])
def test_plan_exercises_refuses_incomplete(exercises):
    with pytest.raises(ToolError):
        server._plan_exercises(exercises)


def test_plan_exercises_drops_empty_fields():
    result = server._plan_exercises([{"activityId": 95, "sets": [{"numberOfReps": 8, "weight": None}]}])
    assert "weight" not in result[0]["sets"][0]


def test_delete_plan_refuses_gym_plan(calls):
    with pytest.raises(ToolError):
        server.delete_plan(2)
    assert not [call for call in calls if call[0] == "delete_personal_plan"]


def test_delete_plan_deletes_own_plan(calls):
    server.delete_plan(1)
    assert ("delete_personal_plan", 1) in calls


def test_save_plan_refuses_to_replace_gym_plan(calls):
    with pytest.raises(ToolError):
        server.save_plan("New", [{"activityId": 95, "sets": [{"duration": 60}]}], 2)
    assert not [call for call in calls if call[0] == "update_personal_plan"]


def test_slim_plan_keeps_ids_and_prunes_sets(monkeypatch):
    monkeypatch.setattr(server, "_app_name", lambda activity_id: "Bench")
    plan = {
        **OWN,
        "plannedExercises": [
            {"id": 7, "activity": {"activityId": 95}, "sets": [{"setType": "REP_BASED", "numberOfReps": 8, "weight": None}]}
        ],
    }
    assert server._slim_plan(plan) == {
        "planId": 1,
        "name": "Mine",
        "type": "USER_TRAINING_PLAN",
        "exercises": [
            {
                "exerciseId": 7,
                "activityId": 95,
                "appName": "Bench",
                "sets": [{"setType": "REP_BASED", "numberOfReps": 8}],
            }
        ],
    }


def test_out_removes_images_and_empty_values():
    assert json.loads(server._out({"imageUrl": "x", "name": "A", "note": None})) == {"name": "A"}


def test_notes_are_appended(monkeypatch, tmp_path):
    notes = tmp_path / "sub" / "notes.md"
    monkeypatch.setattr(server, "NOTES_FILE", notes)
    assert server.read_training_notes() == "(no notes yet)"
    server.add_training_note("Ran 5 km", "2026-01-02")
    assert server.read_training_notes() == "- **2026-01-02**: Ran 5 km\n"


def test_coach_context_puts_skill_first(monkeypatch, tmp_path):
    (tmp_path / "SKILL.md").write_text("role")
    (tmp_path / "evidence.md").write_text("rules")
    monkeypatch.setattr(server, "COACH_DIR", tmp_path)
    context = server.get_coach_context()
    assert context.index("SKILL.md") < context.index("evidence.md")


def test_coach_context_without_files(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "COACH_DIR", tmp_path)
    assert "no coach files" in server.get_coach_context()


def test_check_ins_get_minutes_to_last_workout_of_the_day():
    check_ins = [
        {"checkInDate": "2026-11-07T13:45:34", "timezone": "Europe/Berlin", "gymLocationName": "Gym", "duration": None},
        {"checkInDate": "2026-11-08T10:00:00", "timezone": "Europe/Berlin", "gymLocationName": "Gym", "duration": None},
    ]
    workouts = [{"completedAt": "2026-11-07T15:30:00.1"}, {"completedAt": "2026-11-07T15:45:34.2"}]
    result = server._with_workout_end(check_ins, workouts)
    assert result[0]["checkIn"] == "2026-11-07T14:45:34"
    assert result[0]["workoutCompletedAt"] == "2026-11-07T15:45:34"
    assert result[0]["minutesToWorkoutEnd"] == 60
    assert "minutesToWorkoutEnd" not in result[1]


def test_check_ins_are_converted_from_utc_with_summer_time():
    check_in = {"checkInDate": "2026-09-11T09:50:02", "timezone": "Europe/Berlin"}
    assert server._local_check_in(check_in) == "2026-09-11T11:50:02"


def test_flexibility_keeps_only_degrees_with_history():
    latest = [
        {"type": "HIP_EXTENSION_LEFT_DEGREE", "value": 26.3985, "valueInterpretation": "TOO_LOW", "createdAt": "x"},
        {"type": "HIP_EXTENSION_LEFT_NORMALIZED", "value": 0.4},
    ]
    history = [{"type": "HIP_EXTENSION_LEFT_DEGREE", "history": [{"value": 24.04, "date": "2026-09-11"}]}]
    result = server._flexibility_angles(latest, history)
    assert result == [
        {
            "type": "HIP_EXTENSION_LEFT_DEGREE",
            "degree": 26.4,
            "rating": "TOO_LOW",
            "measuredAt": "x",
            "history": [{"date": "2026-09-11", "degree": 24.0}],
        }
    ]
