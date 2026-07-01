"""Runtime compatibility guard for the cross-repo knitweb engine dependency."""

from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Iterable


_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _ROOT / "pyproject.toml"


class EngineCompatibilityError(RuntimeError):
    """Raised when a peer advertises an incompatible knitweb engine."""


@dataclass(frozen=True)
class EngineCompatibility:
    status: str
    compatible: bool
    resolved: str
    requirement: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _version_tuple(version: str) -> tuple[int, int, int]:
    core = re.split(r"[-+]", str(version), maxsplit=1)[0]
    parts = core.split(".")
    nums: list[int] = []
    for part in parts[:3]:
        if not part.isdigit():
            raise ValueError(f"unsupported version segment: {version!r}")
        nums.append(int(part))
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _iter_specs(requirement: str) -> Iterable[tuple[str, str]]:
    for raw in requirement.split(","):
        part = raw.strip()
        if not part:
            continue
        match = re.match(r"(<=|>=|==|<|>)\s*([0-9][0-9A-Za-z.+-]*)$", part)
        if not match:
            raise ValueError(f"unsupported knitweb requirement: {requirement!r}")
        yield match.group(1), match.group(2)


def knitweb_requirement(pyproject: Path = _PYPROJECT) -> str:
    """Return the knitweb dependency range declared by molgang's pyproject."""
    deps: list[str] = []
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        deps = [str(dep) for dep in data.get("project", {}).get("dependencies", [])]
    else:
        try:
            deps = list(metadata.requires("molgang") or [])
        except metadata.PackageNotFoundError:
            deps = []
    for dep in deps:
        name, _, _marker = str(dep).partition(";")
        if name.strip().startswith("knitweb"):
            return name.strip()[len("knitweb"):].strip()
    raise RuntimeError("pyproject.toml does not declare a knitweb dependency")


def resolved_knitweb_version() -> str:
    import knitweb

    return str(getattr(knitweb, "__version__", "unknown"))


def check_knitweb_compatibility(
    resolved: str | None = None,
    requirement: str | None = None,
) -> EngineCompatibility:
    """Compare a resolved knitweb version with molgang's supported range.

    Exact floor matches pass. Patch/minor drift inside the declared range warns.
    Anything outside the range fails.
    """
    requirement = requirement or ""
    try:
        requirement = requirement or knitweb_requirement()
        resolved = resolved if resolved is not None else resolved_knitweb_version()
        got = _version_tuple(str(resolved))
        specs = list(_iter_specs(requirement))
        lower = next((v for op, v in specs if op in (">=", "==")), None)
        for op, ver in specs:
            want = _version_tuple(ver)
            ok = (
                got >= want if op == ">=" else
                got > want if op == ">" else
                got <= want if op == "<=" else
                got < want if op == "<" else
                got == want
            )
            if not ok:
                return EngineCompatibility(
                    "fail", False, str(resolved), requirement,
                    f"knitweb {resolved} is outside supported range {requirement}; "
                    "install the pinned pulse/knitweb engine or update molgang's compatibility range.",
                )
        if lower is not None and got != _version_tuple(lower):
            return EngineCompatibility(
                "warn", True, str(resolved), requirement,
                f"knitweb {resolved} is inside {requirement}, but differs from tested floor {lower}.",
            )
        return EngineCompatibility(
            "pass", True, str(resolved), requirement,
            f"knitweb {resolved} satisfies {requirement}.",
        )
    except Exception as exc:
        return EngineCompatibility(
            "fail", False, str(resolved or "unavailable"), requirement or "unknown",
            f"could not verify knitweb compatibility: {exc}",
        )


def engine_metadata(*, engine: str) -> dict:
    from . import __version__ as molgang_version

    verdict = check_knitweb_compatibility()
    return {
        "engine": engine,
        "molgang": molgang_version,
        "knitweb": verdict.resolved,
        "knitweb_requirement": verdict.requirement,
        "knitweb_compatibility": verdict.as_dict(),
    }


def assert_local_knitweb_compatible() -> EngineCompatibility:
    verdict = check_knitweb_compatibility()
    if not verdict.compatible:
        raise EngineCompatibilityError(verdict.message)
    return verdict


def assert_peer_engine_compatible(peer: dict | None) -> None:
    """Fail closed when a peer advertises an incompatible knitweb engine."""
    if not isinstance(peer, dict):
        return
    verdict = peer.get("knitweb_compatibility")
    if isinstance(verdict, dict) and verdict.get("compatible") is False:
        raise EngineCompatibilityError(str(verdict.get("message") or "peer knitweb is incompatible"))
    version = peer.get("knitweb") or peer.get("resolved")
    if not version or str(version).startswith("n/a"):
        return
    local = check_knitweb_compatibility(str(version))
    if not local.compatible:
        raise EngineCompatibilityError(f"peer advertises incompatible knitweb engine: {local.message}")
