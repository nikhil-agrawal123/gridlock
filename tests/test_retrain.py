"""Tests for the retraining feedback loop: logging roundtrip, label
derivation, the retrain pipeline, and model versioning/rollback."""
from datetime import datetime, timedelta, timezone


def test_compute_impact_level_bins():
    from derive_targets import compute_impact_level

    rank = {"Low": 0, "Medium": 1, "High": 2}
    assert compute_impact_level(10) == "Low"
    assert compute_impact_level(480, road_closure=1, cause_severity=5) == "High"
    # monotonic: a closed road of the same duration is never lower impact
    assert rank[compute_impact_level(300, road_closure=1)] >= rank[compute_impact_level(300, road_closure=0)]


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
