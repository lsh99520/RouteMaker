import json
import re
import threading
import time
from pathlib import Path
from typing import Callable

from .models import Analysis, ExtractedPosting, Profile

MAX_USERS = 500
USER_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
DEFAULT_USER = "default"


def clean_user_id(raw) -> str:
    return raw if isinstance(raw, str) and USER_ID.match(raw) else DEFAULT_USER


class Store:
    def __init__(self, path: Path, seed: Callable[[], dict]):
        self.path = path
        self.seed = seed
        self.lock = threading.RLock()
        self.data = {"users": {}}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if "users" in loaded:
                self.data = loaded

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        for attempt in range(5):
            try:
                tmp.replace(self.path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _evict(self):
        users = self.data["users"]
        while len(users) > MAX_USERS:
            oldest = min((u for u in users if u != DEFAULT_USER), key=lambda u: users[u].get("seen", 0), default=None)
            if oldest is None:
                break
            users.pop(oldest)

    def user(self, uid: str) -> "UserStore":
        with self.lock:
            users = self.data["users"]
            if uid not in users:
                users[uid] = self.seed()
                self._evict()
                self.save()
            users[uid]["seen"] = time.time()
            return UserStore(self, uid)

    def reset(self, uid: str) -> "UserStore":
        with self.lock:
            self.data["users"][uid] = self.seed()
            self.data["users"][uid]["seen"] = time.time()
            self.save()
            return UserStore(self, uid)


class UserStore:
    def __init__(self, store: Store, uid: str):
        self.store, self.uid = store, uid

    @property
    def d(self) -> dict:
        return self.store.data["users"][self.uid]

    def _write(self, fn):
        with self.store.lock:
            fn(self.d)
            self.store.save()

    def get_profile(self, pid):
        raw = self.d["profiles"].get(pid)
        return Profile.model_validate(raw) if raw else None

    def put_profile(self, p: Profile):
        self._write(lambda d: d["profiles"].__setitem__(p.id, p.model_dump(mode="json")))

    def profiles(self):
        return [Profile.model_validate(x) for x in self.d["profiles"].values()]

    def get_posting(self, pid):
        raw = self.d["postings"].get(pid)
        return ExtractedPosting.model_validate(raw) if raw else None

    def put_posting(self, p: ExtractedPosting):
        self._write(lambda d: d["postings"].__setitem__(p.id, p.model_dump(mode="json")))

    def postings(self):
        return [ExtractedPosting.model_validate(x) for x in self.d["postings"].values()]

    def delete_posting(self, pid):
        def fn(d):
            d["postings"].pop(pid, None)
            d["analyses"].pop(pid, None)
        self._write(fn)

    def done_set(self) -> set:
        return set(self.d["done"].keys())

    def set_done(self, task_id: str, done: bool):
        def fn(d):
            if done:
                d["done"][task_id] = True
            else:
                d["done"].pop(task_id, None)
        self._write(fn)

    def get_analysis(self, pid):
        raw = self.d["analyses"].get(pid)
        return Analysis.model_validate(raw) if raw else None

    def put_analysis(self, a: Analysis):
        self._write(lambda d: d["analyses"].__setitem__(a.posting_id, a.model_dump(mode="json")))

    def plan_overrides(self) -> dict:
        return dict(self.d.get("plan", {}).get("blocks", {}))

    def plan_strategy(self) -> str:
        return self.d.get("plan", {}).get("strategy", "deadline")

    def put_plan_block(self, bid: str, data: dict):
        self._write(lambda d: d.setdefault("plan", {}).setdefault("blocks", {}).__setitem__(bid, data))

    def set_plan(self, overrides: dict, strategy: str):
        self._write(lambda d: d.__setitem__("plan", {"blocks": overrides, "strategy": strategy}))
