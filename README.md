# egym-mcp

An unofficial [MCP](https://modelcontextprotocol.io) server that gives an AI assistant access to your EGYM Fitness account: workouts, strength values, bio age and body metrics. It can also create, change and delete your own training plans in the app. It is not affiliated with or endorsed by EGYM.

It builds on [python-egym](https://github.com/marcelpoelstra/python-egym), which talks to the member API behind the app. That API is undocumented and can change or stop working at any time. Using it may go against your gym's or EGYM's terms, so use it at your own risk.

## What to know first

- **It writes to your real account.** `save_plan` and `delete_plan` change plans you see in the app, and a deleted plan cannot be restored. Only plans of type `USER_TRAINING_PLAN` can be changed; gym and trainer plans are refused.
- **Your health data goes to your AI provider.** Whatever a tool returns is sent to the model your MCP client uses.
- **It is not medical advice.** Training suggestions from an AI assistant do not replace a doctor or physiotherapist, least of all with injuries or health conditions.
- **Your password stays local.** It is read from your own `.env` file, which is kept outside this repository.

## Setup

Requires Python 3.10 or newer.

```bash
git clone https://github.com/FreDJ1996/egym-mcp.git
cd egym-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

Store your login in the data folder, `~/.egym-mcp` by default:

```bash
mkdir -p ~/.egym-mcp
cp .env.example ~/.egym-mcp/.env
chmod 600 ~/.egym-mcp/.env
```

Then edit `~/.egym-mcp/.env`, and add the server to your MCP client. `.mcp.json.example` shows the format; replace the path with your own absolute path.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `EGYM_EMAIL`, `EGYM_PASSWORD` | required | Your EGYM Fitness login |
| `EGYM_LOCALE` | `en-GB` | Language of exercise names and API answers |
| `EGYM_BASE_URL` | found from the email address | Your gym's Netpulse address, if finding it fails |
| `EGYM_MCP_DATA_DIR` | `~/.egym-mcp` | Folder for `.env`, notes, catalogue and coach files |
| `EGYM_MCP_NOTES_FILE` | `<data>/training_notes.md` | Training notes |
| `EGYM_MCP_CATALOG_FILE` | `<data>/exercise_catalog.json` | Cached exercise catalogue, fetched on first use and after 90 days |
| `EGYM_MCP_COACH_DIR` | `<data>/coach` | Markdown files returned by `get_coach_context` |

## Tools

| Tool | Purpose |
| --- | --- |
| `get_recent_workouts`, `get_workouts` | Completed workouts with sets, weights and reps |
| `get_strength_status`, `get_strength_history` | EGYM maximum strength values and their history |
| `get_bio_age`, `get_bio_age_history` | Bio age and its parts |
| `get_flexibility` | Flexibility angles in degrees per joint and side, with rating and history |
| `get_squat_analysis` | Squat scans: depth, back and shoulder angle |
| `get_check_ins` | Gym visits, with the minutes from check-in to the end of that day's workout |
| `get_body_composition`, `get_body_metric_history` | Body metrics and their history |
| `get_muscle_imbalances` | Muscle imbalance analysis |
| `get_activity_level` | Activity level, points and goal |
| `search_exercises` | Exercise catalogue, with `activityId` and the name in the app |
| `get_available_plans`, `get_plan` | Plans in the app and the sets stored in them |
| `save_plan` | **Writes:** creates an own plan or replaces one |
| `delete_plan` | **Writes:** deletes an own plan |
| `get_coach_context` | Your coach files, if you have any |
| `read_training_notes`, `add_training_note` | Local notes for what EGYM does not record |

## Coaching files

To give the assistant a role and your goals, copy the templates and fill them in:

```bash
mkdir -p ~/.egym-mcp/coach
cp examples/coach/*.md ~/.egym-mcp/coach/
```

Every `.md` file in that folder is returned by `get_coach_context`, so this works with any MCP client. Keep them out of public repositories if they hold personal data.

With Claude Code you can use them as a skill that activates by itself: put them in `.claude/skills/fitness-coach/` in your project and set `EGYM_MCP_COACH_DIR` to that folder.

## Known gaps

- `get_workouts` only holds workouts entered in the app. Circuit training on EGYM machines does not appear there; use the strength tools for those. `get_check_ins` shows every gym visit.
- Check-outs are only recorded if the gym reports them; otherwise `get_check_ins` has no time spent in the gym.
- `weight: 0.0` on a free-weight set means no weight was entered, not body weight.
- `get_available_plans` can show the values last trained; `get_plan` shows those stored in the plan.

## Tests

```bash
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

The tests make no network calls.

## License

GPL-3.0, the license of python-egym, which this server imports.
