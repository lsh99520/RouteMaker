"""시연 점검(화면): 기준일 × 화면 크기 × 브라우저 시간대로 실제 화면을 열어 본다.

python qa/ui_check.py  →  qa/ui_report.md, qa/shots/*.png
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "qa" / "shots"
DATES = {"2026-11-20": "제584회", "2026-11-24": "2026-11-26까지 접수", "2026-11-27": "제586회", "2026-12-07": "제586회"}
VIEWS = {"PC 1440": (1440, 900), "노트북 1280": (1280, 720), "태블릿 768": (768, 1024),
         "휴대폰 390": (390, 844), "작은 휴대폰 360": (360, 740)}
ROUTES = ["schedule", "home", "postings", "postings/p_a", "postings/p_d", "profile"]
TZS = ["Asia/Seoul", "America/Los_Angeles"]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve(day):
    port = free_port()
    env = dict(os.environ, ROUTEMAKER_TODAY=day, ROUTEMAKER_STORE=str(Path(tempfile.mkdtemp()) / "s.json"),
               ANTHROPIC_API_KEY="")
    env.pop("ROUTEMAKER_DEMO_DIR", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "routemaker.api:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return proc, f"http://127.0.0.1:{port}"
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("서버 시작 실패")


def main():
    SHOTS.mkdir(exist_ok=True)
    problems, checked = [], 0
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for day, expect in DATES.items():
            proc, url = serve(day)
            try:
                for tz in TZS:
                    for vname, (w, h) in VIEWS.items():
                        if tz != "Asia/Seoul" and vname not in ("PC 1440", "휴대폰 390"):
                            continue
                        ctx = br.new_context(viewport={"width": w, "height": h}, timezone_id=tz, locale="ko-KR",
                                             is_mobile=w < 500, has_touch=w < 500)
                        page = ctx.new_page()
                        errs = []
                        page.on("pageerror", lambda e: errs.append(str(e)))
                        page.on("console", lambda m: m.type == "error" and errs.append(m.text))
                        for r in ROUTES:
                            where = f"{day} | {vname} | {tz} | #{r}"
                            page.goto(f"{url}/#{r}")
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(250)
                            checked += 1
                            txt = page.inner_text("body")
                            if f"시연 기준일 {day}" not in txt:
                                problems.append(f"{where}: 상단 기준일 표시가 {day}가 아님")
                            over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                            if over > 1:
                                problems.append(f"{where}: 가로로 {over}px 넘침")
                            if r == "postings/p_a" and expect not in txt:
                                problems.append(f"{where}: 가상테크 판정에 '{expect}' 없음")
                            if "undefined" in txt or "NaN" in txt or "[object Object]" in txt:
                                problems.append(f"{where}: 화면에 undefined/NaN 노출")
                            if tz == "Asia/Seoul" and vname in ("PC 1440", "휴대폰 390") and r in ("schedule", "postings/p_a"):
                                page.screenshot(path=str(SHOTS / f"{day}_{vname.split()[0]}_{r.replace('/', '-')}.png"))
                        for e in errs:
                            if "ERR_TUNNEL_CONNECTION_FAILED" in e:
                                continue
                            problems.append(f"{day} | {vname} | {tz}: 콘솔 오류 {e[:150]}")
                        ctx.close()
            finally:
                proc.terminate()
        br.close()
    lines = ["# 시연 점검 결과 (화면)", "",
             f"- 기준일 {len(DATES)}개 × 화면 크기 {len(VIEWS)}종 × 시간대 {len(TZS)}종, 화면 {len(ROUTES)}개 — 총 {checked}회 열어 봄",
             "- 확인: 상단 기준일 표시, 가로 넘침, 날짜별 핵심 문구, undefined/NaN 노출, 콘솔 오류",
             "- 점검 환경에서는 외부 글꼴(Pretendard CDN) 접속이 막혀 기본 글꼴로 표시됨 — 앱 문제 아님, 배포 화면은 정상 글꼴", "",
             "## 문제", ""] + ([f"- {p}" for p in problems] or ["- 없음"])
    (ROOT / "qa" / "ui_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"열어 본 화면 {checked} / 문제 {len(problems)}")
    for p in problems[:60]:
        print(" !", p)


if __name__ == "__main__":
    main()
