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
        browser = p.chromium.launch(headless=True, args=["--lang=en-US"])
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
        try:
            # pin the UI locale to EN — the app's locale cascade uses the host
            # timezone and an ISP geo hint, so an NL/BE machine (or runner) would
            # otherwise render Dutch chrome under these EN assertions. The
            # explicit-player-choice slot always wins the cascade.
            page.add_init_script("try{localStorage.setItem('molgang_locale','en')}catch(e){}")
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


def _skip_tour(page) -> None:
    """Dismiss the first-run tutorial if it opened (fresh device) — not the flow under test."""
    try:
        page.wait_for_selector("#tour-skip", state="visible", timeout=2_500)
        _click(page, "#tour-skip")
        page.wait_for_function(
            "() => document.querySelector('#tour-layer')?.classList.contains('hidden')",
            timeout=5_000,
        )
    except Exception:
        pass


def _walk_in(page, name: str) -> None:
    page.wait_for_selector("#avatars .av-pick", timeout=15_000)
    _skip_tour(page)
    page.check("#age-ok")
    page.fill("#name", name)
    _click(page, "#go")
    page.wait_for_selector("#floor:not(.hidden) .table-card", timeout=15_000)


def run_platform_checks(base: str, shots: Path) -> list[str]:
    """#120: PWA installability, offline-first service worker, i18n switch, mobile viewport.

    Everything runs against the live ``molgang serve`` — real /api/*, real sw.js, no mocks.
    """
    failures: list[str] = []
    from playwright.sync_api import sync_playwright

    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--lang=en-US"])

        # ── PWA surface + service worker + cache-served shell ────────────────
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
        ctx.add_init_script("try{localStorage.setItem('molgang_locale','en')}catch(e){}")
        page_errors: list[str] = []
        page = ctx.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.goto(base + "/", wait_until="networkidle", timeout=30_000)
        page.add_style_tag(content="*{animation:none!important;transition:none!important}")

        manifest = page.evaluate(
            """async () => {
              const link = document.querySelector('link[rel="manifest"]');
              if (!link) return { ok: false, why: "no <link rel=manifest>" };
              const res = await fetch(link.href);
              if (!res.ok) return { ok: false, why: "manifest HTTP " + res.status };
              const m = await res.json();
              return { ok: !!m.name && Array.isArray(m.icons) && m.icons.length >= 2
                           && !!m.start_url && !!m.display,
                       name: m.name, display: m.display, icons: (m.icons || []).length };
            }"""
        )
        if not manifest.get("ok"):
            failures.append(f"PWA manifest not installable: {manifest}")

        # registration settles (app.js registers sw.js on load)
        page.evaluate("() => navigator.serviceWorker.ready.then(() => true)")
        page.reload(wait_until="networkidle")
        controlled = page.evaluate("() => !!navigator.serviceWorker.controller")
        if not controlled:
            failures.append("service worker does not control the page after a second load")
        cache = page.evaluate(
            """async () => {
              const keys = await caches.keys();
              const shell = keys.find((k) => k.startsWith("molgang-shell-"));
              if (!shell) return { keys };
              const stored = await (await caches.open(shell)).keys();
              return { shell, urls: stored.map((r) => new URL(r.url).pathname) };
            }"""
        )
        urls = cache.get("urls") or []
        if not cache.get("shell") or not any(u.endswith("app.js") for u in urls) \
                or not any(u.endswith(("/", "index.html")) for u in urls):
            failures.append(f"app shell not precached by the service worker: {cache}")
        page.screenshot(path=str(shots / "10-pwa-shell.png"))

        # ── i18n: NL locale switch translates chrome + sets <html lang> ──────
        _walk_in(page, "🤖 Platform Probe")
        page.select_option("#lang-switch", "en")
        try:
            _wait_for_contains(page, '#tabs button[data-view="ledger"]',
                               "My knits", timeout_ms=10_000)
        except Exception:
            failures.append("EN locale did not render the tab chrome (tab.ledger)")
        # after its first use the switcher retires into the ⚙ settings popover —
        # open it like a returning player would before switching again
        page.wait_for_selector("#settings-gear:not(.hidden)", timeout=10_000)
        _click(page, "#settings-gear")
        page.wait_for_selector("#settings-pop:not(.hidden) #lang-switch", timeout=10_000)
        page.select_option("#settings-pop #lang-switch", "nl")
        try:
            page.wait_for_function(
                "() => document.documentElement.lang === 'nl'", timeout=10_000)
        except Exception:
            failures.append("locale switch did not set <html lang=nl>")
        try:
            _wait_for_contains(page, '#tabs button[data-view="ledger"]',
                               "Mijn knits", timeout_ms=10_000)
        except Exception:
            failures.append("NL locale did not translate the tab chrome (tab.ledger)")
        page.screenshot(path=str(shots / "12-i18n-nl.png"))
        if page_errors:
            failures.append(f"uncaught page errors in the PWA/i18n flow: {page_errors[:3]}")
        ctx.close()

        # ── offline → reconnecting toast → recovery (#116) ───────────────────
        # In a SW-BLOCKED context: Chromium's offline emulation does not apply to
        # service-worker-initiated fetches (with the sw active the poll is served
        # from the API cache by design — that resilience is covered by the cache
        # assertions above). Blocking the sw exercises app.js's own blip path:
        # one reconnecting toast, keep last state, recover on the next poll.
        off = browser.new_context(viewport={"width": 1280, "height": 900},
                                  service_workers="block", locale="en-US")
        off.add_init_script("try{localStorage.setItem('molgang_locale','en')}catch(e){}")
        opage = off.new_page()
        off_errors: list[str] = []
        opage.on("pageerror", lambda e: off_errors.append(str(e)))
        opage.goto(base + "/", wait_until="networkidle", timeout=30_000)
        opage.add_style_tag(content="*{animation:none!important;transition:none!important}")
        _walk_in(opage, "🤖 Offline Probe")
        off.set_offline(True)
        # Chromium's offline emulation blocks NEW requests but leaves an already-
        # ESTABLISHED websocket open; a real network drop kills it. Close the live
        # world socket like the drop would, so the poll fallback (and its toast) runs.
        opage.evaluate("() => { try { closeWorldSocket(); } catch (e) {} }")
        # locale-agnostic: assert against the ACTIVE locale's own string (headless
        # chromium keeps the host language list even with a context locale pin)
        expect_reconnecting = opage.evaluate("() => t('toast.reconnecting')")
        try:
            _wait_for_contains(opage, "#toast", expect_reconnecting, timeout_ms=10_000)
        except Exception:
            failures.append("offline poll did not surface the reconnecting toast")
        opage.screenshot(path=str(shots / "11-offline.png"))
        off.set_offline(False)
        expect_reconnected = opage.evaluate("() => t('toast.reconnected')")
        try:
            _wait_for_contains(opage, "#toast", expect_reconnected, timeout_ms=10_000)
        except Exception:
            failures.append("going back online did not surface the reconnected toast")
        if off_errors:
            failures.append(f"uncaught page errors during offline round-trip: {off_errors[:3]}")
        off.close()

        # ── mobile viewport: the core loop completes with no horizontal scroll ─
        mob = browser.new_context(viewport={"width": 360, "height": 640}, locale="en-US",
                                  device_scale_factor=2, is_mobile=True, has_touch=True)
        mob.add_init_script("try{localStorage.setItem('molgang_locale','en')}catch(e){}")
        mpage = mob.new_page()
        mob_errors: list[str] = []
        mpage.on("pageerror", lambda e: mob_errors.append(str(e)))
        mpage.goto(base + "/", wait_until="networkidle", timeout=30_000)
        mpage.add_style_tag(content="*{animation:none!important;transition:none!important}")
        _walk_in(mpage, "📱 Mobile Probe")
        mpage.screenshot(path=str(shots / "13-mobile-floor.png"))
        # sit at an EMPTY table: an earlier suite's player may still be seated at the
        # first one, and a stale co-seated peer holds the weave quorum above what the
        # NPC backing can settle — solo-at-a-table is the flow under test here
        mpage.evaluate(
            """() => {
              const cards = [...document.querySelectorAll('#floor .table-card')];
              const empty = cards.find((c) => /\\b0\\/\\d+/.test(c.textContent));
              (empty || cards[cards.length - 1]).querySelector('.join-table').click();
            }"""
        )
        mpage.wait_for_selector("#table:not(.hidden) #knit", timeout=15_000)
        mpage.fill("#term", "NaCl")
        _click(mpage, "#knit")
        try:
            # NPC backing is deliberately delayed (#26) and other seated peers may
            # share the table — give the quorum room before calling it a failure
            _wait_for_contains(mpage, "#fabric", "NaCl", timeout_ms=30_000)
        except Exception:
            failures.append("mobile flow: 'NaCl' never appeared in the table fabric")
        overflow = mpage.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if overflow > 1:
            failures.append(f"mobile viewport has {overflow}px of horizontal overflow")
        if mob_errors:
            failures.append(f"uncaught page errors in the mobile flow: {mob_errors[:3]}")
        mpage.screenshot(path=str(shots / "14-mobile-woven.png"))
        mob.close()

        browser.close()
    return failures


def _run_suites(base: str, shots: Path, args) -> list[str]:
    failures: list[str] = []
    if args.suite in ("core", "all"):
        failures += run_flow(base, shots, args.term)
    if args.suite in ("platform", "all"):
        failures += run_platform_checks(base, shots)
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
    parser.add_argument("--suite", choices=("core", "platform", "all"), default="core",
                        help="core = walk-in→knit→woven; platform = PWA/offline/i18n/mobile (#120)")
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
                failures = _run_suites(base, shots, args)
            finally:
                _stop_process(proc)
                tmp.cleanup()
        else:
            _wait_for_api(base, timeout_s=20)
            failures = _run_suites(base, shots, args)
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
