"""Tests for the retraining feedback loop: logging roundtrip, label
derivation, the retrain pipeline, and model versioning/rollback."""
from datetime import datetime, timedelta, timezone


def test_compute_impact_level_bins():
    from derive_targets import compute_impact_level

    # Duration-only bins (minutes): Low <=60 | Medium <=180 | High >180.
    # road_closure / cause_severity are deliberately NOT inputs -- they are
    # model features, and folding them into the label caused circular leakage.
    assert compute_impact_level(10) == "Low"
    assert compute_impact_level(60) == "Low"        # lower-edge inclusive
    assert compute_impact_level(120) == "Medium"
    assert compute_impact_level(180) == "Medium"    # mid-edge inclusive
    assert compute_impact_level(480) == "High"
    # clipping: negatives floor to Low, anything past the 500 cap stays High
    assert compute_impact_level(-5) == "Low"
    assert compute_impact_level(9999) == "High"


def test_feedback_logging_roundtrip(tmp_path, monkeypatch):
    from modules import feedback_logger as fb

    monkeypatch.setattr(fb, "PREDICTIONS_DIR", tmp_path / "predictions")
    monkeypatch.setattr(fb, "OUTCOMES_DIR", tmp_path / "outcomes")
    fb.OPEN_INCIDENTS.clear()

    iid = fb.log_prediction("MG Road", {"hour": 19, "veh_type": "bmtc_bus"},
                            impact="High", duration=120, corridor_count=4,
                            score=70.0, event_ctx=None, model_version="v1")
    assert fb.has_open_incident("MG Road")
    inc = fb.get_open_incident("MG Road")
    fb.log_outcome(iid, inc["predicted_at"], inc["predicted_at"] + timedelta(minutes=140),
                   actual_corridor_count=3, resolution_method="auto_speed_recovery")
    fb.close_incident("MG Road")
    assert not fb.has_open_incident("MG Road")
    assert fb.resolved_count() == 1


def test_manual_report_roundtrip(tmp_path, monkeypatch):
    """An officer's manual report writes a linked prediction+outcome pair that
    counts as a resolved incident (so the retrain merge picks it up)."""
    from modules import feedback_logger as fb

    monkeypatch.setattr(fb, "PREDICTIONS_DIR", tmp_path / "predictions")
    monkeypatch.setattr(fb, "OUTCOMES_DIR", tmp_path / "outcomes")

    started = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    iid = fb.log_manual_report(
        corridor="Hosur Road",
        features={"hour": 9, "veh_type": "truck", "cause_severity": 4},
        started_at=started,
        resolved_at=started + timedelta(minutes=200),   # >180 -> High
        actual_corridor_count=3,
        predicted={"impact_level": "Medium", "duration_min": 90},
        notes="overturned truck blocking two lanes",
    )
    assert iid
    # both snapshots written and joinable -> one resolved incident
    assert fb.resolved_count() == 1
    # a manual report is already resolved, so it must NOT register as open
    assert not fb.has_open_incident("Hosur Road")

    outs = fb._read_all(fb.OUTCOMES_DIR)
    assert outs.iloc[0]["actual_impact_level"] == "High"
    assert outs.iloc[0]["resolution_method"] == "officer_report"


def test_model_registry_seed_and_rollback():
    from modules import model_registry as mr

    mr.seed_if_needed()
    reg = mr.read_registry()
    assert reg["current"]
    assert any(v["version"] == reg["current"] for v in reg["versions"])
    # round-trip rollback to current is a no-op that still succeeds
    assert mr.rollback_to(reg["current"]) is True
    assert mr.rollback_to("nope_v99") is False


def test_retrain_skips_without_feedback(tmp_path, monkeypatch):
    import retrain

    # point the pipeline at an empty feedback dir
    monkeypatch.setattr(retrain, "_read_dir", lambda pattern: __import__("pandas").DataFrame())
    out = retrain.run_retrain()
    assert out["status"] == "skipped"
