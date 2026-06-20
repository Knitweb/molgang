/* MOLGANG roadmap — render the sprint board.
 * Strategy: paint the baked snapshot instantly, then try to hydrate from the live GitHub API
 * (unauthenticated, 60 req/hr/IP). On any error / rate-limit / offline, keep the snapshot. */
(function () {
  "use strict";
  var REPO = "Knitweb/molgang";
  var API = "https://api.github.com/repos/" + REPO;

  // Sprints 3..10 form the "road to 1M"; 1-2 are history, Backlog + 11-13 go in "later".
  function sprintNum(title) {
    var m = /^Sprint\s+(\d+)/.exec(title || "");
    return m ? parseInt(m[1], 10) : null;
  }
  function isFuture(title) { var n = sprintNum(title); return n !== null && n >= 11; }

  function moscowOf(labels) {
    for (var i = 0; i < labels.length; i++)
      if (labels[i].indexOf("MoSCoW: ") === 0) return labels[i].slice(8);
    return null;
  }
  function prioOf(labels) {
    for (var i = 0; i < labels.length; i++)
      if (labels[i].indexOf("prio:") === 0) return labels[i].slice(5);
    return null;
  }

  function esc(s) {
    return (s || "").replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function fetchJSON(url) {
    return fetch(url, { headers: { Accept: "application/vnd.github+json" } })
      .then(function (r) { if (!r.ok) throw new Error(url + " -> " + r.status); return r.json(); });
  }

  /* ---- live: milestones + their issues, shaped like the baked snapshot ---- */
  function loadLive() {
    return fetchJSON(API + "/milestones?state=all&per_page=100").then(function (ms) {
      ms.sort(function (a, b) { return a.number - b.number; });
      return Promise.all(ms.map(function (m) {
        return fetchJSON(API + "/issues?milestone=" + m.number + "&state=all&per_page=100")
          .then(function (issues) {
            var iss = issues.filter(function (it) { return !it.pull_request; }).map(function (it) {
              var labels = (it.labels || []).map(function (l) { return l.name; });
              return {
                number: it.number, title: it.title, state: it.state, html_url: it.html_url,
                labels: labels, moscow: moscowOf(labels), prio: prioOf(labels)
              };
            }).sort(function (a, b) { return a.number - b.number; });
            return {
              number: m.number, title: m.title, description: m.description || "",
              state: m.state, open_issues: m.open_issues, closed_issues: m.closed_issues,
              due_on: m.due_on, html_url: m.html_url, issues: iss
            };
          });
      }));
    });
  }

  function loadBaked() {
    return Promise.all([
      fetchJSON("./data/roadmap.json"),
      fetchJSON("./data/roadmap.meta.json").catch(function () { return null; })
    ]);
  }

  /* ---- render ---- */
  function cardHTML(m) {
    var total = m.open_issues + m.closed_issues;
    var pct = total ? Math.round((m.closed_issues / total) * 100) : 0;
    var counts = { Must: 0, Should: 0, Could: 0, Would: 0 };
    (m.issues || []).forEach(function (i) { if (i.moscow && counts[i.moscow] != null) counts[i.moscow]++; });
    var mcTotal = counts.Must + counts.Should + counts.Could + counts.Would || 1;
    function seg(k, cls) { return counts[k] ? '<i class="' + cls + '" style="width:' + (counts[k] / mcTotal * 100) + '%" title="' + counts[k] + ' ' + k + '"></i>' : ""; }

    var n = sprintNum(m.title);
    var cls = "card" + (pct === 100 && total ? " done" : (m.state === "open" && pct > 0 && pct < 100 ? " active" : ""));

    var shown = (m.issues || []).slice(0, 6), rest = (m.issues || []).slice(6);
    function li(i) {
      var st = i.state === "closed" ? "closed" : "open";
      var prio = i.prio ? '<span class="prio ' + (i.prio === "high" ? "high" : "") + '">' + esc(i.prio) + '</span>' : "";
      return '<li><span class="st ' + st + '"></span><a href="' + i.html_url + '" target="_blank" rel="noopener">'
        + esc(i.title) + '</a>' + prio + '</li>';
    }
    var list = shown.map(li).join("");
    var more = rest.length
      ? '<details class="more"><summary>+ ' + rest.length + ' more</summary><ul class="issues">'
        + rest.map(li).join("") + '</ul></details>' : "";

    return '<article class="' + cls + '">'
      + '<div class="card-h"><h3>' + esc(m.title) + '</h3><span class="pct">' + pct + '%</span></div>'
      + (m.description ? '<p class="desc">' + esc(m.description) + '</p>' : "")
      + '<div class="prog"><span style="width:' + pct + '%"></span></div>'
      + '<div class="counts">' + m.closed_issues + ' done · ' + m.open_issues + ' open · ' + total + ' total</div>'
      + '<div class="moscow">' + seg("Must", "m-must") + seg("Should", "m-should") + seg("Could", "m-could") + seg("Would", "m-would") + '</div>'
      + '<ul class="issues">' + list + '</ul>' + more
      + '</article>';
  }

  function render(board, source, meta) {
    var main = board.filter(function (m) { return /^Sprint\s+(\d+)/.test(m.title) && !isFuture(m.title); });
    main.sort(function (a, b) { return sprintNum(a.title) - sprintNum(b.title); });
    document.getElementById("board").innerHTML = main.map(cardHTML).join("") || "<p>No sprints found.</p>";

    // north-star aggregate over the road-to-1M sprints (3..10)
    var road = board.filter(function (m) { var n = sprintNum(m.title); return n !== null && n >= 3 && n <= 10; });
    var done = 0, total = 0;
    road.forEach(function (m) { done += m.closed_issues; total += m.open_issues + m.closed_issues; });
    document.getElementById("ns-done").textContent = done;
    document.getElementById("ns-total").textContent = total;
    document.getElementById("ns-sprints").textContent = road.length;
    document.getElementById("ns-fill").style.width = (total ? (done / total * 100) : 0) + "%";

    // "later" pills: Backlog + Sprint 11-13
    var later = board.filter(function (m) { return /Backlog/i.test(m.title) || isFuture(m.title); });
    if (later.length) {
      document.getElementById("later").innerHTML =
        '<h2>Later</h2><div class="row">' + later.map(function (m) {
          var t = m.open_issues + m.closed_issues;
          return '<a class="pill" href="' + m.html_url + '" target="_blank" rel="noopener"><b>' + esc(m.title) + '</b> · ' + t + ' issues</a>';
        }).join("") + '</div>';
    }

    var badge = document.getElementById("sync-badge");
    if (source === "live") {
      badge.className = "badge live"; badge.textContent = "● live from GitHub";
    } else {
      var when = meta && meta.generated_at ? new Date(meta.generated_at).toLocaleString() : "baked snapshot";
      badge.className = "badge snap"; badge.textContent = "snapshot · " + when;
    }
  }

  /* ---- boot: baked first, then hydrate live ---- */
  loadBaked().then(function (r) {
    render(r[0], "snapshot", r[1]);
    loadLive().then(function (live) { render(live, "live", null); })
      .catch(function (e) { /* keep snapshot */ console.warn("live hydrate failed:", e.message); });
  }).catch(function (e) {
    // no baked snapshot yet — try live alone
    loadLive().then(function (live) { render(live, "live", null); })
      .catch(function (e2) {
        document.getElementById("board").innerHTML =
          '<p class="loading">Could not load the roadmap (' + esc(e2.message) + '). '
          + 'See the <a href="https://github.com/Knitweb/molgang/milestones">milestones</a>.</p>';
      });
  });
})();
