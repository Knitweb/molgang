#!/usr/bin/env python3
"""Build the serverless engine wheel the dapp boots from.

The browser shell (``serverless/web/peer.js`` + ``sw.js``) installs ONE wheel,
``engine/molgang_engine-0.0.0-py3-none-any.whl``, into Pyodide — the UNCHANGED
pure-Python ``molgang`` + ``knitweb`` packages. Shipping the exact ``.py`` bytes
is what makes cross-peer byte-identity free (README). This script assembles that
wheel reproducibly from the live sources, so the live dapp always runs the
current engine instead of a stale hand-built artifact.

Both packages are stdlib-only pure Python; the one compiled dependency
(``cryptography`` for secp256k1/SHA-256) is installed separately by the shell via
micropip, so this wheel needs no binary content.

Usage:
    python3 serverless/build_engine.py            # molgang from ../src, knitweb from ../pulse
    KNITWEB_SRC=/path/to/pulse/src python3 serverless/build_engine.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WHEEL_NAME = "molgang_engine-0.0.0-py3-none-any.whl"
OUT_DIR = HERE / "web" / "engine"

PYPROJECT = """\
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "molgang_engine"
version = "0.0.0"
description = "MOLGANG serverless engine bundle — molgang + knitweb pure-Python for Pyodide"
requires-python = ">=3.11"

[tool.setuptools]
include-package-data = true

[tool.setuptools.packages.find]
where = ["."]
include = ["molgang*", "knitweb*"]
"""


def _find_knitweb_src() -> Path:
    env = os.environ.get("KNITWEB_SRC")
    candidates = [Path(env)] if env else []
    candidates += [
        REPO.parent / "pulse" / "src",
        Path("/tmp/pulse/src"),
        Path("/tmp/pulse-clean/src"),
    ]
    for c in candidates:
        if (c / "knitweb" / "__init__.py").is_file():
            return c
    raise SystemExit(
        "knitweb source not found — clone https://github.com/knitweb/pulse next to this "
        "repo, or set KNITWEB_SRC=/path/to/pulse/src")


def main() -> int:
    molgang_src = REPO / "src"
    if not (molgang_src / "molgang" / "__init__.py").is_file():
        raise SystemExit(f"molgang source not found at {molgang_src}")
    knitweb_src = _find_knitweb_src()

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copytree(molgang_src / "molgang", stage / "molgang",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(knitweb_src / "knitweb", stage / "knitweb",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (stage / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")

        print(f"building {WHEEL_NAME} from molgang={molgang_src} knitweb={knitweb_src}")
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(stage / "dist")],
                       cwd=stage, check=True)

        built = sorted((stage / "dist").glob("molgang_engine-*.whl"))
        if not built:
            raise SystemExit("wheel build produced no output")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        target = OUT_DIR / WHEEL_NAME
        shutil.copyfile(built[0], target)
        size_kb = target.stat().st_size // 1024
        print(f"wrote {target.relative_to(REPO)}  ({size_kb} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
