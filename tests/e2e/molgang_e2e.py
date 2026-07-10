#!/usr/bin/env python3
"""MOLGANG browser end-to-end smoke tests (Playwright + Selenium, headless).

Spins up pristine `molgang serve` instances per test suite and runs:
walk-in → sit → knit a term → woven consensus flow.
Produces screenshots, prints pass/fail, and exits with non-zero status on failure.

IMPORTANT: Quorum determinism is only guaranteed with a fresh backend per test run.
A fresh world is required because crowded tables may not reach voting consensus
if too many concurrent proposals exist. Each test creates a clean instance via
tempfile.TemporaryDirectory to ensure reproducible weaving behavior.
"""

from __future__ import annotations

import argparse
import os
import os.path
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib import error, request


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _augment_pythonpath(*paths: Path) -> str:
    parts: list[str] = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    for extra in paths:
        sp = str(extra)
        if sp not in parts:
            parts.append(sp)
    return os.pathsep.join(parts)


def _wait_for_api(base: str, timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    last: BaseException | None = None
    while time.time() < deadline:
        try:
            with request.urlopen(f"{base}/api/state", timeout=1) as r:
                if r.status == 200:
                    return
        except (error.URLError, OSError) as e:
            last = e
            time.sleep(0.25)
    raise RuntimeError(f"server did not become ready at {base} in {timeout_s}s") from last


def _wait_for_text(page, selector: str, expected: str, timeout_ms: int = 10_000) -> bool:
    return page.wait_for_function(
        "([s, v]) => (document.querySelector(s)?.textContent || '').trim() === v",
        arg=(selector, expected),
        timeout=timeout_ms,
    ) is not None


def _wait_for_contains(page, selector: str, expected: str, timeout_ms: int = 15_000) -> bool:
    return page.wait_for_function(
        "([s, v]) => (document.querySelector(s)?.textContent || '').includes(v)",
        arg=(selector, expected),
        timeout=timeout_ms,
    ) is not None


def _click(page, selector: str) -> None:
    # deterministic click path for re-rendering cards / detached DOM nodes.
    page.evaluate(
        "(s) => { const el = document.querySelector(s); if (!el) throw new Error(`missing ${s}`); el.click(); }",
        selector,
    )


def _browser_diag(page, shots: Path, label: str) -> dict:
    """Collect enough browser/server state to make CI timeouts actionable."""
    try:
        page.screenshot(path=str(shots / f"{label}.png"))
    except Exception:
        # Best-effort artifact: failing to write a screenshot should not block
        # collection of more useful browser/server diagnostics below.
        pass
    try:
        return page.evaluate(
            """async () => {
              const sid = localStorage.getItem("molgang_sid") || "";
              const table = localStorage.getItem("molgang_table") || "";
              let state = null;
              try {
                const res = await fetch("/api/state?sid=" + encodeURIComponent(sid));
                state = await res.json();
              } catch (e) {
                state = {error: String(e)};
              }
              const current = state && state.tables && state.you
                ? state.tables.find((t) => t.id === state.you.table)
                : null;
              return {
                sid,
                table,
                term: document.querySelector("#term")?.value || "",
                fabricText: document.querySelector("#fabric")?.textContent || "",
                openText: document.querySelector("#open")?.textContent || "",
                you: state ? state.you : null,
                currentFabric: current ? current.fabric : null,
                currentOpen: current ? current.open : null,
              };
            }"""
        )
    except Exception as e:
        return {"diagnostic_error": str(e)}


def _serve_process(base_dir: Path, host: str, port: int) -> subprocess.Popen[str]:
    world = base_dir / "world.json"
    db = base_dir / "registry.db"
    wallet = base_dir / "pulse-identity.cbor"

    cmd = [
        sys.executable,
        "-m",
        "molgang.cli",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--world",
        str(world),
        "--db",
        str(db),
        "--wallet",
        str(wallet),
        "--host-genesis",
        "1",
    ]

    root = _repo_root()
    env = os.environ.copy()
    pulse_src = (root.parent / "pulse" / "src").resolve()
    extra = [root / "src"]
    if pulse_src.is_dir():
        extra.append(pulse_src)
    env["PYTHONPATH"] = _augment_pythonpath(*extra)

    return subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def run_flow(base: str, shots: Path, term: str) -> list[str]:
    failures: list[str] = []

    from playwright.sync_api import sync_playwright

    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
        try:
            page.goto(base + "/", wait_until="networkidle", timeout=30_000)
            page.add_style_tag(content="*{animation:none!important;transition:none!important}")
            page.wait_for_selector("#avatars .av-pick", timeout=15_000)
            page.screenshot(path=str(shots / "01-walkin.png"))

            tutorial_flow = term == "H2O"
            if tutorial_flow:
                if not _wait_for_contains(page, "#tour-title", "Pick an avatar", timeout_ms=10_000):
                    failures.append("first-run tutorial did not open on the walk-in screen")
                _click(page, "#tour-skip")
                page.wait_for_function(
                    "() => document.querySelector('#tour-layer')?.classList.contains('hidden')",
                    timeout=5_000,
                )
                _click(page, "#tutorial-replay")
                if not _wait_for_contains(page, "#tour-title", "Pick an avatar", timeout_ms=5_000):
                    failures.append("tutorial replay did not restart the walk-in step")

            # #139 age/consent gate: acknowledge 13+/guardian like a real player,
            # otherwise #go stays disabled and the join can never happen.
            page.check("#age-ok")
            page.fill("#name", "🤖 Playwright")
            _click(page, "#go")
            page.wait_for_selector("#floor:not(.hidden) .table-card", timeout=15_000)

            try:
                _wait_for_text(page, "#me-silk", "10", timeout_ms=10_000)
            except Exception:
                failures.append("wallet not initialized with silk 10")

            pill = page.text_content("#me-wallet") or ""
            if "👛" not in pill:
                failures.append("wallet pill missing after join")
            page.screenshot(path=str(shots / "02-floor.png"))

            if tutorial_flow:
                if not _wait_for_contains(page, "#tour-title", "Take a seat", timeout_ms=10_000):
                    failures.append("tutorial did not advance to the seat step")
                _click(page, "#tour-primary")
            else:
                _click(page, "#floor .table-card .join-table")
            page.wait_for_selector("#table:not(.hidden) #knit", timeout=15_000)
            page.wait_for_timeout(400)
            page.screenshot(path=str(shots / "03-table.png"))

            if tutorial_flow:
                if not _wait_for_contains(page, "#tour-title", "Knit a real term", timeout_ms=10_000):
                    failures.append("tutorial did not advance to the knit step")
                _click(page, "#tour-primary")
            else:
                page.fill("#term", term)
                _click(page, "#knit")

            try:
                woven_visible = _wait_for_contains(page, "#fabric", term, timeout_ms=15_000)
            except Exception as e:
                failures.append(f"term '{term}' never appeared in table fabric; diag={_browser_diag(page, shots, '04-timeout')}; error={e}")
                woven_visible = False
            if not woven_visible:
                failures.append(f"term '{term}' never appeared in table fabric")
            else:
                if not _wait_for_text(page, "#me-knits", "1", timeout_ms=8_000):
                    failures.append("successful knit did not increment the knit counter")
                silk_after = int((page.text_content("#me-silk") or "0").strip() or "0")
                if silk_after < 10:
                    failures.append("successful useful work did not restore enough silk to keep knitting")

            open_block = (page.text_content("#open") or "")
            if term in open_block and "✓" not in open_block:
                failures.append("open knit did not settle into woven state")

            page.wait_for_timeout(600)
            page.screenshot(path=str(shots / "04-woven.png"))

            if tutorial_flow:
                if not _wait_for_contains(page, "#tour-title", "Peers vote", timeout_ms=10_000):
                    failures.append("tutorial did not explain peer voting after a knit")
                _click(page, "#tour-primary")
                if not _wait_for_contains(page, "#tour-title", "Woven into the fabric", timeout_ms=5_000):
                    failures.append("tutorial did not finish on the fabric step")
                _click(page, "#tour-primary")
                page.wait_for_function(
                    "() => document.querySelector('#tour-layer')?.classList.contains('hidden')",
                    timeout=5_000,
                )
                done = page.evaluate("localStorage.getItem('molgang_tutorial_done_v1')")
                if done != "done":
                    failures.append("tutorial completion was not remembered per device")

            # 🏅 Progress tab — ladder, quests, achievements & seasonal leaderboard (#110-#113)
            _click(page, '#tabs button[data-view="progress"]')
            page.wait_for_selector("#progress:not(.hidden)", timeout=10_000)
            # reputation ladder renders the player's perks (#113); "Faucet access" is the level-1 perk
            if not _wait_for_contains(page, "#ladder", "Faucet access", timeout_ms=10_000):
                failures.append("reputation ladder did not render the player's perks")
            if not _wait_for_contains(page, "#quests-list", "First bond", timeout_ms=10_000):
                failures.append("quests panel did not render the First bond quest")
            if not _wait_for_contains(page, "#achievements-list", "First bond", timeout_ms=10_000):
                failures.append("achievements panel did not render the First bond badge")
            if term == "H2O":
                # weaving a known molecule must complete first-bond, unlock its badge, rank the player
                if not _wait_for_contains(page, "#quests-list", "✅ First bond", timeout_ms=10_000):
                    failures.append("first-bond quest did not show complete after weaving H2O")
                if not _wait_for_contains(page, "#achievements-list", "\U0001f3c5 First bond", timeout_ms=10_000):
                    failures.append("first-bond badge did not unlock after weaving H2O")
                if not _wait_for_contains(page, "#season-board", "Playwright", timeout_ms=10_000):
                    failures.append("player not listed on the all-time leaderboard")
            _click(page, "#lb-season")            # season toggle switches the board without error
            page.wait_for_timeout(400)
            page.screenshot(path=str(shots / "05-progress.png"))
        finally:
            browser.close()

    return failures


def run_flow_selenium(base: str, shots: Path, term: str) -> list[str]:
    """Selenium-based e2e flow: walk-in → sit → knit → woven (core path coverage).

    Uses ChromeDriver for cross-browser validation. Gracefully skips if Chrome version
    doesn't match chromedriver (common in dev; CI ensures sync). Fresh backend per run.
    """
    failures: list[str] = []
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        failures.append("Selenium not installed; skipping Selenium flow")
        return failures

    shots.mkdir(parents=True, exist_ok=True)
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1280,900")

        try:
            driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            if "version" in str(e).lower() or "sessionnotcreated" in str(e).lower():
                failures.append("Selenium: Chrome/chromedriver version mismatch (skipping for dev; CI will have sync)")
                return failures
            raise

        wait = WebDriverWait(driver, 20)
        driver.get(f"{base}/")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#avatars .av-pick")))
        driver.save_screenshot(str(shots / "sel_01-walkin.png"))

        # Join flow
        age_checkbox = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#age-ok")))
        age_checkbox.click()
        driver.find_element(By.CSS_SELECTOR, "#name").send_keys("🤖 Selenium")
        driver.find_element(By.CSS_SELECTOR, "#go").click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#floor:not(.hidden) .table-card")))
        driver.save_screenshot(str(shots / "sel_02-floor.png"))

        # Sit and knit
        driver.find_element(By.CSS_SELECTOR, "#floor .table-card .join-table").click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#table:not(.hidden) #knit")))
        driver.find_element(By.CSS_SELECTOR, "#term").send_keys(term)
        driver.find_element(By.CSS_SELECTOR, "#knit").click()

        # Wait for woven
        fabric_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#fabric")))
        if term not in fabric_elem.text:
            failures.append(f"Selenium: term '{term}' never appeared in table fabric")

        time.sleep(0.6)
        driver.save_screenshot(str(shots / "sel_03-woven.png"))
    except Exception as e:
        failures.append(f"Selenium: flow failed: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="MOLGANG browser e2e smoke tests (Playwright + Selenium)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host used for launching local server")
    parser.add_argument("--base", default="", help="Molgang base URL (defaults to http://{host}:{port})")
    parser.add_argument("--term", default="H2O", help="Term to knit")
    parser.add_argument("--shots", default=str(_repo_root() / ".artifacts/e2e"),
                        help="Screenshot output directory")
    parser.add_argument("--port", type=int, default=8799, help="Port for the local one-shot server")
    parser.add_argument("--reuse", action="store_true",
                        help="Reuse an already-running server at --base")
    args = parser.parse_args()

    host_for_base = args.host if args.host not in {"0.0.0.0", "::"} else "127.0.0.1"
    base = args.base or f"http://{host_for_base}:{args.port}"

    shots = Path(args.shots).resolve()
    all_failures: dict[str, list[str]] = {}
    proc: subprocess.Popen[str] | None = None

    # Run Playwright test suite with fresh backend
    try:
        if not args.reuse:
            tmp = tempfile.TemporaryDirectory(prefix="molgang-e2e-pw-")
            proc = _serve_process(Path(tmp.name), host=args.host, port=args.port)
            try:
                _wait_for_api(base, timeout_s=20)
                failures = run_flow(base, shots, args.term)
            finally:
                _stop_process(proc)
                tmp.cleanup()
        else:
            _wait_for_api(base, timeout_s=20)
            failures = run_flow(base, shots, args.term)
        all_failures["playwright"] = failures
    except Exception as e:
        print(f"E2E PLAYWRIGHT: failed ({e})")
        if proc and proc.stdout:
            try:
                tail = proc.stdout.read().strip().splitlines()[-15:]
                if tail:
                    print("server log tail:")
                    print("\n".join(tail))
            except Exception:
                pass
        all_failures["playwright"] = [str(e)]

    # Run Selenium test suite with fresh backend
    try:
        if not args.reuse:
            tmp = tempfile.TemporaryDirectory(prefix="molgang-e2e-sel-")
            proc = _serve_process(Path(tmp.name), host=args.host, port=args.port)
            try:
                _wait_for_api(base, timeout_s=20)
                failures = run_flow_selenium(base, shots, args.term)
            finally:
                _stop_process(proc)
                tmp.cleanup()
        else:
            _wait_for_api(base, timeout_s=20)
            failures = run_flow_selenium(base, shots, args.term)
        all_failures["selenium"] = failures
    except Exception as e:
        print(f"E2E SELENIUM: failed ({e})")
        if proc and proc.stdout:
            try:
                tail = proc.stdout.read().strip().splitlines()[-15:]
                if tail:
                    print("server log tail:")
                    print("\n".join(tail))
            except Exception:
                pass
        all_failures["selenium"] = [str(e)]

    # Report results
    any_failed = False
    for suite_name, failures in all_failures.items():
        if failures:
            any_failed = True
            print(f"E2E {suite_name.upper()}: {len(failures)} FAILED")
            for msg in failures:
                print(f"  - {msg}")
        else:
            print(f"E2E {suite_name.upper()}: PASS ✅")

    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
