# TrafficSense

**Event-driven congestion intelligence for Bengaluru.** TrafficSense forecasts
per-corridor traffic impact, plans police/barricade deployments around planned
events, routes traffic and ambulances around closures, and continuously
re-learns from real outcomes through a closed feedback loop.

Built for the *Gridlock 2.0 · PS2* problem statement. The system pairs a
FastAPI backend (models + planners + a background scheduler) with a Streamlit
dashboard for traffic operators.

---

## What it does

There are two pipelines, both built on the same three trained models:

1. **Live / unplanned monitoring** — every 15 minutes a background scheduler
   polls each corridor, pulls live speeds from TomTom, fuses them with the
   model's risk forecast, weather, and any active event context into a single
   `0–100` composite score, and drives a per-corridor incident state machine.
   Surfaced on the **Live Impact Map**.

2. **Planned-event deployment briefs** — given an event (venue, attendance,
   type, time; point *or* moving route), the system forecasts the affected
   corridors and produces a full operational brief: barricade cordon, officer
   manpower plan + resource optimization, congestion-aware diversions, an
   emergency ambulance route, and a historical-blockage prediction. Surfaced on
   the **Event Planner**.

Every prediction the system makes is logged. When incidents resolve (speed
recovery, officer close, or 24 h timeout), the actual outcome is logged too —
and the **retraining loop** uses those labelled pairs to train, validate, and
(only if it doesn't regress) promote a new model version.

---

## Architecture

```
                          ┌──────────────────────────────────────┐
                          │            Streamlit dashboard        │
                          │  Live Map · Event Planner · Resource  │
                          │  Deployment · Diversions · Analytics  │
                          └───────────────────┬──────────────────┘
                                              │ HTTP (TRAFFICSENSE_API)
                          ┌───────────────────▼──────────────────┐
                          │              FastAPI  (api/)          │
                          │  /corridor-risk  /event-impact        │
                          │  /retrain  /model-info  /rollback     │
                          │  /incidents/active  /incident/resolve │
                          └───┬───────────────┬──────────────┬────┘
        APScheduler (15 min)  │               │              │
        poll_corridors() ─────┘               │              │
                          ┌───────────────────▼──────┐  ┌────▼──────────────┐
                          │  Models (model_registry)  │  │  Planners         │
                          │  impact_clf  duration_reg │  │  barricade /      │
                          │  corridor_reg  fusion     │  │  diversion /      │
                          └───────────────────┬───────┘  │  manpower /       │
                                              │          │  emergency router │
                   ┌──────────────────────────▼───┐      └───────────────────┘
                   │  Feedback loop                │
                   │  feedback_logger →            │   External: TomTom (live
                   │  incident_tracker (state m/c) │   speeds), weather, OSMnx
                   │  → retrain.py → promote/reject │   road graph + centrality
                   └───────────────────────────────┘
```

### The three models

All three are CatBoost, share the **same 16 features** (3 categorical), and are
trained with a **time-based split** (first 80% train / last 20% test — no random
shuffle, which would leak temporal structure).

| Model          | Type           | Target                       |
|----------------|----------------|------------------------------|
| `impact_clf`   | Classifier     | `impact_level` (Low/Med/High)|
| `duration_reg` | Regressor      | `congestion_duration_min`    |
| `corridor_reg` | Regressor      | `affected_corridor_count`    |

**Composite score (fusion)** combines four signals into one `0–100` number per
corridor (`modules/fusion.py`):

```
score = 0.40·live_speed_deviation + 0.35·model_risk
      + 0.15·(event_multiplier−1) + 0.10·(weather−1)
```

These fixed weights are the default; once enough live-vs-actual data is logged,
`LearnedFusionMLP` can replace them with learned weights (auto-used if
`models/trained/fusion_mlp.pkl` exists).

---

## The feedback & retraining loop

This is the part that makes the system self-improving rather than static.

1. **Log prediction** (`feedback_logger.log_prediction`) — when an incident
   opens, the full feature snapshot + prediction is written to
   `data/feedback/predictions/<date>.parquet`.
2. **Track** (`incident_tracker`) — a per-corridor state machine
   (`NORMAL → INCIDENT_OPEN → resolved`) driven by the 15-min poll. Onset at
   >35% speed drop; resolved when back within 10% of free-flow, on officer
   close, or after a 24 h timeout. State persists to disk so restarts resume.
3. **Log outcome** (`log_outcome`) — on resolution the *actual* duration,
   impact level, and corridor count are written to
   `data/feedback/outcomes/<date>.parquet`.
4. **Retrain** (`retrain.py`, via `POST /retrain` or the Analytics page) —
   merges predictions+outcomes on `incident_id`, combines with the original
   training set, trains candidate models, and validates on a **time-based
   holdout**.
5. **Promote or reject** (`model_registry`) — the candidate is promoted only
   if it doesn't regress against the current production model
   (`AUC ≥ current − 0.02` **and** `MAE ≤ current × 1.02`). Promoted models are
   archived under `models/versions/<date>_v<n>/`; the current pointer lives in
   `models/registry.json`. Any version can be rolled back with one call.

### A note on data honesty (no leakage)

`impact_level` is derived **from duration alone** (`derive_targets.py`):
`Low ≤60 min · Medium ≤180 · High >180`, capped at 500. `road_closure` and
`cause_severity` are deliberately **excluded** from the label formula — they are
model *features*, and folding them into the label created circular leakage
(AUC ~0.99 by memorising the bucketing rule).

Guards against this regressing:
- `scripts/diagnose_leakage.py` — correlation matrix, per-feature AUC, class
  balance, CatBoost importances, and a `road_closure × impact_level` cross-tab.
- Both `train_model.py` and `retrain.py` warn and flag any candidate with
  `AUC > 0.95` as a likely leak.

Current production model (`registry.json`) scores a realistic **AUC ≈ 0.90**;
top features are `veh_type`, `hotspot_id`, `month` — not the label inputs.

---

## Project layout

```
api/                FastAPI app
  main.py             app + lifespan (seeds registry, starts scheduler)
  scheduler.py        APScheduler 15-min poll loop
  state.py            in-memory active-event context
  routes/             corridor / event / incident / admin endpoints
modules/            domain logic
  model_registry.py   versioning, promotion, hot-reload, rollback
  feedback_logger.py  prediction/outcome snapshot logging
  incident_tracker.py per-corridor state machine
  feature_builder.py  builds CatBoost feature rows (live + event)
  fusion.py           composite score (fixed weights + learned MLP)
  tomtom_client.py    live speeds (mock fallback if no key)
  weather.py          weather factor (mock fallback)
  barricade_planner / diversion_planner / manpower_planner /
  resource_optimizer / emergency_router / historical_blockage / ...
dashboard/          Streamlit UI (app.py + pages/)
data/
  raw/ processed/     source + featured datasets (featured_v2.parquet)
  feedback/           predictions/ outcomes/ corridor_state.json
models/
  trained/            original Day-2 build artifacts
  current/            active models the API serves
  versions/           archived promoted versions + metrics.json
  registry.json       current pointer + version history
scripts/diagnose_leakage.py
derive_targets.py   target derivation (impact / duration / corridor count)
train_model.py      train the three CatBoost models
retrain.py          feedback-driven retrain + validate + promote
Day1_Pipeline.ipynb data cleaning / feature engineering pipeline
tests/              pytest suite (endpoints + retrain loop)
```

---

## Setup

Requires **Python 3.11**.

```bash
python -m venv venv
# Windows:  venv\Scripts\activate     |  *nix: source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` and fill in keys (all optional — the app falls
back to deterministic mocks, flagged `*_is_mock=true` in responses):

| Variable            | Purpose                                          |
|---------------------|--------------------------------------------------|
| `TOMTOM_API_KEY`    | Live corridor speeds (TomTom Flow Segment Data).  |
| `WEATHER_API_KEY`   | Live weather factor.                              |
| `TRAFFICSENSE_API`  | API base URL for the dashboard (default `http://localhost:8000`). |

---

## Running

Start the API (seeds the model registry on first run and starts the scheduler):

```bash
uvicorn api.main:app --port 8000
```

In a second terminal, start the dashboard:

```bash
streamlit run dashboard/app.py
```

The dashboard landing page shows whether it can reach the API.

### Rebuilding the models from scratch (optional)

```bash
python derive_targets.py     # derive targets -> data/processed/featured_v2.parquet
python train_model.py        # train the three CatBoost models -> models/trained/
python train_model.py --eval # train + evaluate only, don't save
```

---

## API reference

| Method | Endpoint                              | Purpose                                            |
|--------|---------------------------------------|----------------------------------------------------|
| GET    | `/health`                             | Liveness check.                                    |
| GET    | `/corridor-risk/{corridor}`           | Live composite score + breakdown for one corridor. |
| GET    | `/corridors/all`                      | Latest state for every corridor.                   |
| POST   | `/event-impact`                       | Full planning brief for a planned event.           |
| POST   | `/event/activate-phase2/{event_id}`   | Start live monitoring + pre-open incidents.        |
| GET    | `/incidents/active`                   | List open incidents.                               |
| POST   | `/incident/{id}/resolve`              | Officer manual close (logs the outcome).           |
| POST   | `/retrain`                            | Run merge → train candidate → validate → promote.  |
| GET    | `/model-info`                         | Current version, metrics, history, feedback count. |
| POST   | `/rollback/{version}`                 | Revert current to an archived version.             |

Interactive docs at `http://localhost:8000/docs` once the API is running.

---

## Testing

```bash
pytest                       # full suite
pytest tests/test_retrain.py # feedback loop + versioning
python scripts/diagnose_leakage.py   # leakage audit on current model/data
```
