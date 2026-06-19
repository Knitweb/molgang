#!/usr/bin/env python3
"""MOLGANG browser end-to-end smoke test (Playwright, headless).

Spins up a pristine `molgang serve` instance and runs:
walk-in → sit → knit a term → wait for the woven result.
Produces screenshots, prints pass/fail, and exits with a non-zero status on failure.
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
        "(s, v) => (document.querySelector(s)?.textContent || '').trim() === v",
        arg=(selector, expected),
        timeout=timeout_ms,
    ) is not None


def _wait_for_contains(page, selector: str, expected: str, timeout_ms: int = 15_000) -> bool:
    return page.wait_for_function(
        "(s, v) => (document.querySelector(s)?.textContent || '').includes(v)",
        arg=(selector, expected),
        timeout=timeout_ms,
    ) is not None


def _click(page, selector: str) -> None:
    # deterministic click path for re-rendering cards / detached DOM nodes.
    page.evaluate(
        "(s) => { const el = document.querySelector(s); if (!el) throw new Error(`missing ${s}`); el.click(); }",
        selector,
    )


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

    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    return proc


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

            _click(page, "#floor .table-card .join-table")
            page.wait_for_selector("#table:not(.hidden) #knit", timeout=15_000)
            page.wait_for_timeout(400)
            page.screenshot(path=str(shots / "03-table.png"))

            page.fill("#term", term)
            _click(page, "#knit")

            if not _wait_for_contains(page, "#fabric", term, timeout_ms=15_000):
                failures.append(f"term '{term}' never appeared in table fabric")
            if not _wait_for_text(page, "#me-silk", "9", timeout_ms=8_000):
                failures.append("silk did not spend 1 on successful knit")

            open_block = (page.text_content("#open") or "")
            if term in open_block and "✓" not in open_block:
                failures.append("open knit did not settle into woven state")

            page.wait_for_timeout(600)
            page.screenshot(path=str(shots / "04-woven.png"))
        finally:
            browser.close()

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="MOLGANG browser e2e smoke test")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host used for launching local server")
    parser.add_argument("--base", default="", help="Molgang base URL (defaults to http://{host}:{port})")
    parser.add_argument("--term", default="H2O", help="Term to knit")
    parser.add_argument("--shots", default=str(_repo_root() / ".artifacts/e2e"),
                        help="Screenshot output directory")
    parser.add_argument("--port", type=int, default=8765, help="Port for the local one-shot server")
    parser.add_argument("--reuse", action="store_true",
                        help="Reuse an already-running server at --base")
    args = parser.parse_args()

    host_for_base = args.host if args.host not in {"0.0.0.0", "::"} else "127.0.0.1"
    base = args.base or f"http://{host_for_base}:{args.port}"

    shots = Path(args.shots).resolve()
    failures: list[str] = []
    proc: subprocess.Popen[str] | None = None

    try:
        if not args.reuse:
            tmp = tempfile.TemporaryDirectory(prefix="molgang-e2e-")
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
    except Exception as e:
        print(f"E2E PLAYWRIGHT: failed ({e})")
        if proc and proc.stdout:
            tail = proc.stdout.read().strip().splitlines()[-15:]
            if tail:
                print("server log tail:")
                print("\n".join(tail))
        return 1

    if failures:
        print(f"E2E PLAYWRIGHT: {len(failures)} FAILED")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print("E2E PLAYWRIGHT: PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
