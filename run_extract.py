import json
import sys
from datetime import date

from routemaker.engine import analyze
from routemaker.extract import extract_posting
from routemaker.loader import DATA, load_all


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = sys.argv[1] if len(sys.argv) > 1 else str(DATA / "sample_posting_a.txt")
    import os
    today = date.fromisoformat(os.environ["ROUTEMAKER_TODAY"]) if os.environ.get("ROUTEMAKER_TODAY") else date.today()
    d = load_all()
    text = open(path, encoding="utf-8").read()
    e = extract_posting(text, "p_live", d["exams"], today.isoformat())
    print(json.dumps(e.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if e.deadline is not None:
        a = analyze(d["profiles"]["u1"], e.to_posting(), d["sessions"], today, d["exams"])
        print(json.dumps(a.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
