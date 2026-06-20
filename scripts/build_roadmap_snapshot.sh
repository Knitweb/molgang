#!/usr/bin/env bash
# Build the baked roadmap snapshot (milestones + issues) consumed by the GitHub Pages
# roadmap as instant first-paint + offline/rate-limit fallback. Idempotent; runs in CI and locally.
#   REPO=Knitweb/molgang bash scripts/build_roadmap_snapshot.sh
# Requires: gh (authenticated) + python3. Writes site/data/roadmap.json + roadmap.meta.json.
set -euo pipefail
export REPO="${REPO:-Knitweb/molgang}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export OUT="$ROOT/site/data"
mkdir -p "$OUT"

python3 - <<'PY'
import json, os, subprocess, datetime

repo = os.environ["REPO"]
out  = os.environ["OUT"]

def gh_lines(path):
    """gh api --paginate with --jq '.[]' yields one JSON object per line (NDJSON)."""
    r = subprocess.run(["gh","api","--paginate",path,"--jq",".[]"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gh api failed for {path}:\n{r.stderr}")
    items=[]
    for line in r.stdout.splitlines():
        line=line.strip()
        if line:
            items.append(json.loads(line))
    return items

def derive(labels, prefix):
    for l in labels:
        if l.startswith(prefix):
            return l[len(prefix):]
    return None

milestones = gh_lines(f"repos/{repo}/milestones?state=all&per_page=100")
board=[]
total_open=total_closed=0
for m in milestones:
    issues = gh_lines(f"repos/{repo}/issues?milestone={m['number']}&state=all&per_page=100")
    iss=[]
    for it in issues:
        if it.get("pull_request"): continue
        labels=[l["name"] for l in it.get("labels",[])]
        iss.append({
            "number": it["number"],
            "title": it["title"],
            "state": it["state"],
            "html_url": it["html_url"],
            "labels": labels,
            "moscow": derive(labels,"MoSCoW: "),
            "prio": derive(labels,"prio:"),
            "area": derive(labels,"area:"),
            "type": derive(labels,"type:"),
        })
    total_open += m.get("open_issues",0)
    total_closed += m.get("closed_issues",0)
    board.append({
        "number": m["number"],
        "title": m["title"],
        "description": m.get("description") or "",
        "state": m["state"],
        "open_issues": m.get("open_issues",0),
        "closed_issues": m.get("closed_issues",0),
        "due_on": m.get("due_on"),
        "html_url": m["html_url"],
        "issues": sorted(iss, key=lambda x: x["number"]),
    })

# Stable order: by milestone number (Sprint 1,2,Backlog,3..13 by creation)
board.sort(key=lambda x: x["number"])

with open(os.path.join(out,"roadmap.json"),"w") as f:
    json.dump(board, f, indent=1, ensure_ascii=False)

sha = os.environ.get("GITHUB_SHA")
if not sha:
    try: sha = subprocess.run(["git","rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
    except Exception: sha=""
meta={
    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "repo": repo,
    "sha": sha[:12],
    "total_open": total_open,
    "total_closed": total_closed,
    "milestone_count": len(board),
}
with open(os.path.join(out,"roadmap.meta.json"),"w") as f:
    json.dump(meta, f, indent=1)

print(f"roadmap snapshot: {len(board)} milestones, "
      f"{total_open} open / {total_closed} closed issues -> {out}")
PY
