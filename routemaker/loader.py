import json
import os
from pathlib import Path

from .models import ExamSession, JobPosting, Profile

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name, model, base=None):
    return [model.model_validate(x) for x in json.loads(((base or DATA) / name).read_text(encoding="utf-8"))]


def demo_dir() -> Path:
    d = os.environ.get("ROUTEMAKER_DEMO_DIR")
    return Path(d) if d else DATA


def load_all(qnet_path=None):
    from . import qnet
    sessions = _load("exam_sessions.json", ExamSession)
    exams = json.loads((DATA / "exams.json").read_text(encoding="utf-8"))
    official = qnet.load_snapshot(qnet_path or qnet.SNAPSHOT)
    covered = {s.exam_id for s in official}
    sessions = [s for s in sessions if s.exam_id not in covered] + official
    for e in exams:
        if e["exam_id"] in covered:
            e["full_year_schedule"] = True
            e["schedule_source"] = "qnet_api"
    return {
        "sessions": sessions,
        "profiles": {p.id: p for p in _load("profiles.json", Profile, demo_dir())},
        "postings": {p.id: p for p in _load("postings.json", JobPosting, demo_dir())},
        "exams": exams,
    }
