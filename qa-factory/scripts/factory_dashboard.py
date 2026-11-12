"""Event-driven QA evidence dashboard: testing, automation, factory health and cost.
Definitions are shipped in references/metrics-contract.md and metrics/catalogue.json.
Rendering never invokes models, product tests, schedulers or external connectors.
"""
import argparse
import fnmatch
import html
import json
import os
import shutil
import tempfile
import uuid
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import artifact_root, project_root, parse_frontmatter
import adapter_forms as AF  # noqa: E402  — the project's ticket key form (B-405): which task name is a story
import contract as C  # noqa: E402  — C.artifact resolves work/ or flat artifact paths
import runtime_paths as RP  # noqa: E402  — where the carried records and the readiness report live (t-232)
import task_price as TP  # noqa: E402  — the ONE price of a task (t-137): every money surface of a story reads it
from project_decisions import FINDING_SCOPES  # noqa: E402  — the ONE list of a finding's addressees (the writer's own)

# How each addressee is drawn in the factory tab. Presentation only: the WORDS come from the writer
# (`project_decisions.FINDING_SCOPES`); a word the writer gains and this table lacks is drawn grey, never dropped.
SCOPE_COLOR = {"local-urgent": "#F9303C", "local-calibration": "#FDB022", "upstream-candidate": "#2297F6"}
SCOPE_COLOR_OTHER = "#98A2B3"

# Marathon cap: a dispatch longer than this many turns is a signal, not the norm (cache
# rebill grows with every turn x the accumulated context). The rule's canon lives in
# "Orchestrator economy" of the qa-story skill; here it colours the turns column and the card.
MARATHON_TURNS = 80
MARATHON_TIP = (
    "A dispatch longer than ~80 turns. Long contexts can increase cost; actual usage depends on the model and caching. The cure is windows: the agent hands off a partial result with a checkpoint and the orchestrator re-dispatches with a fresh context. The norm is 0.")
GATE_BLOCK_TIP = (
    "The exit gate stopped an agent from handing off a broken artifact (exit_gate.py) and returned the list of errors to fix. On its own this is the mechanism working, not a disaster - what is bad is blocks piling up: each unresolved block remains visible and follows the bounded controller recovery policy. See the event notes in journal.jsonl.")
UNSAFE_TIP = (
    "A handoff that went past honest acceptance: the agent's claim diverged from the detector re-run (FB-27 - a retelling is not a witness). This is not a success: every event is reviewed by its notes in journal.jsonl.")
RETRY_TIP = (
    "Dispatches that resumed work an earlier dispatch had already started, by the cause the parent recorded when it stopped (contract.RETRY_REASONS). Every cause is something the factory or the host did - a turn budget that ran out, a stand that was not installed, a factory script that broke, a question waiting for a person - never the person's work. The norm is a small share; the reason with the largest count is the one to fix.")
# A retry share above this, or one cause repeated this often, is worth a banner row: on
# TP1-15045 10 of 53 dispatches (19 %) were second attempts and the tab said only "10".
RETRY_SHARE_PERCENT = 10
RETRY_REASON_COUNT = 3
ORCHESTRATOR_TIP = (
    "What the orchestrator itself spent on holding the story together - dispatching, re-assembling requests, repeated acceptances and carrying context across the stages - against the story's whole priced cost. On TP2-2553 that was $47.86 of $100.37 and 123.8M tokens: management cost as much as the work it managed. The limit is retro.orchestrator_share_max in the project's config.json; above it the share is a finding about the factory, never a cost line the person is asked to repair. In a driver run the orchestrator is the conductor plus the driver's code: the code spends no model money, so the share counts the conductor's sessions, and a ticket or data-fetching call is the scout's spend, never the orchestrator's.")

DEFAULT_WEIGHTS = {"blocker": 8, "critical": 5, "major": 3, "minor": 1}
OPEN_STATUSES = {"Open", "Fixed", "Reopened", "Blocked", "Intended"}
SEV_RANK = {"blocker": 0, "critical": 1, "major": 2, "minor": 3}
SIZE_RANGES = {"XS": (1, 2), "S": (2, 5), "M": (5, 10), "L": (10, 18), "XL": (18, 28)}  # the canonical estimation scale (scenarios)
SIZE_ORDER = ["XS", "S", "M", "L", "XL"]
# Size $-bands — the Hyperfactory tokenomics (example.com/tokenomics, captured 2026-09-02):
# the expected cost by phase from their calculator (defaults: medium repo, full verification, subagents/inline
# per the size default) x the size's low/high_factor. Operator's decision 09-02: dashboard estimates are tracked by cost.
COST_SCALE_MAX = 150  # the right edge of the dumbbell $ scale
# The sample-view dumbbell of invented dollars was removed: on a board whose whole promise
# is that nothing is guessed, four mock rows sat where the reader expected recorded cost.

from metrics_projection import CATALOGUE, BANDS as SIZE_COST_BANDS
FORMULAS = {group: [(r["label"], r["formula"] + " Sources/update: " + r["source_update"] + ". Missing: " + r["missing"])
                    for r in CATALOGUE if r["id"].startswith(prefix)]
            for group, prefix in (("runs", "A"), ("testing", "T"), ("cost", "C"), ("estimates", "C"), ("factory", "F"))}



def esc(s):
    return html.escape(str(s), quote=True)


def fmt_tok(n):
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(int(n))


def fmt_usd(v):
    return f"${v:,.2f}" if v is not None else "—"


def fmt_dur(s):
    s = int(s)
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s"


def num(cell):
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(cell or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def spark(values, color="#2297F6", width=220, height=40):
    vals = [v for v in values if v is not None]
    if not vals:
        return "<span class='nd'>no data</span>"
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    n = len(vals)
    pts = [(round(6 + (width - 12) * (i / (n - 1) if n > 1 else 0.5), 1),
            round(height - 6 - (height - 12) * ((v - lo) / span), 1)) for i, v in enumerate(vals)]
    line = f"<polyline points='{' '.join(f'{x},{y}' for x, y in pts)}' fill='none' stroke='{color}' stroke-width='2'/>" if n > 1 else ""
    return f"<svg width='{width}' height='{height}'>{line}<circle cx='{pts[-1][0]}' cy='{pts[-1][1]}' r='3' fill='{color}'/></svg>"


def delta(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    d = vals[-1] - vals[-2]
    return "<span class='flat'>=</span>" if d == 0 else f"<span class='d'>{'↑' if d > 0 else '↓'} {abs(round(d, 1))}</span>"


def card(label, value, sub="", accent="#2297F6", chart="", tip=""):
    """tip - the hover explanation: a counter without one reads as a rebuke, not a signal."""
    t = f" title=\"{esc(tip)}\"" if tip else ""
    return (f"<div class='card' style='border-top-color:{accent}'{t}><div class='val'>{value}</div>"
            f"<div class='lbl'>{esc(label)}</div><div class='sub'>{sub}</div>{chart}</div>")


def donut(items, center_top, center_sub, size=150, thick=22):
    # Traffic-light ring: items = [(n, color)], clockwise from 12 o'clock. A non-zero
    # segment is never thinner than min_seg (~4 deg): 1 red out of 1950 is 0.3px of arc,
    # antialiasing eats it, and an invisible red is worse than an imprecise proportion
    # (operator's finding 09-02).
    total = sum(n for n, _ in items)
    if not total:
        return "<span class='nd'>no data</span>"
    r = (size - thick) / 2
    c = 2 * 3.14159265 * r
    min_seg = c * 0.012
    raw = [(c * n / total, color) for n, color in items if n]
    boost = sum(min_seg - s for s, _ in raw if s < min_seg)
    donor = max((s for s, _ in raw), default=0)
    segs, acc = "", 0.0
    for seg, color in raw:
        if seg < min_seg:
            seg = min_seg
        elif seg == donor and boost:
            seg = max(seg - boost, min_seg)
        segs += (f"<circle r='{r:.1f}' cx='{size / 2}' cy='{size / 2}' fill='none' stroke='{color}' "
                 f"stroke-width='{thick}' stroke-dasharray='{seg:.2f} {c - seg:.2f}' "
                 f"stroke-dashoffset='{c / 4 - acc:.2f}'/>")
        acc += seg
    return (f"<svg width='{size}' height='{size}'>{segs}"
            f"<text x='{size / 2}' y='{size / 2 - 2}' text-anchor='middle' fill='#e6e6e6' font-size='22' font-weight='700'>{center_top}</text>"
            f"<text x='{size / 2}' y='{size / 2 + 16}' text-anchor='middle' fill='#b6bec8' font-size='11'>{center_sub}</text></svg>")


def pyramid_svg(rows, width=330, bar_h=26, gap=10):
    # Level pyramid: rows top-down = [(label, [green, yellow, red])].
    maxn = max((sum(v) for _, v in rows), default=1) or 1
    h = len(rows) * (bar_h + gap) + 8
    cx = width * 0.62
    parts = [f"<svg width='{width}' height='{h}'>",
             f"<path d='M {cx - 16} 4 L {cx - width * 0.36} {h - 6} M {cx + 16} 4 L {cx + width * 0.36} {h - 6}' "
             "stroke='#3a4150' stroke-dasharray='4 4' fill='none'/>"]
    y = 6
    for label, (g, yv, r) in rows:
        n = g + yv + r
        w = max(28.0, (width * 0.7) * (n / maxn)) if n else 28.0
        x = cx - w / 2
        if len(label) > 18 and " " in label:
            # a long label goes on two lines so it does not overlap a wide tier
            cut = min((i for i, ch in enumerate(label) if ch == " "), key=lambda i: abs(i - len(label) // 2))
            parts.append(f"<text x='2' y='{y + bar_h / 2 - 2}' fill='#b6bec8' font-size='10'>{label[:cut]}</text>")
            parts.append(f"<text x='2' y='{y + bar_h / 2 + 10}' fill='#b6bec8' font-size='10'>{label[cut + 1:]}</text>")
        else:
            parts.append(f"<text x='2' y='{y + bar_h / 2 + 4}' fill='#b6bec8' font-size='11'>{label}</text>")
        if n:
            xx = x
            for cnt, color in ((g, "#2dd4a0"), (yv, "#FDB022"), (r, "#F9303C")):
                if not cnt:
                    continue
                ww = w * cnt / n
                parts.append(f"<rect x='{xx:.1f}' y='{y}' width='{ww:.1f}' height='{bar_h}' rx='5' fill='{color}'/>")
                if ww > 16:
                    parts.append(f"<text x='{xx + ww / 2:.1f}' y='{y + bar_h / 2 + 4}' text-anchor='middle' "
                                 f"fill='#0e1013' font-size='12' font-weight='700'>{cnt}</text>")
                xx += ww
        else:
            parts.append(f"<rect x='{x:.1f}' y='{y}' width='{w:.1f}' height='{bar_h}' rx='5' fill='#23272f'/>")
            parts.append(f"<text x='{cx:.1f}' y='{y + bar_h / 2 + 4}' text-anchor='middle' fill='#98a1ab' font-size='11'>0</text>")
        y += bar_h + gap
    parts.append("</svg>")
    return "".join(parts)


def bars_svg(rows, width=340, bar_h=20, gap=8, label_w=150):
    # Horizontal bars: rows = [(label, open, ripe)].
    maxn = max((o + r for _, o, r in rows), default=1) or 1
    h = len(rows) * (bar_h + gap) + 4
    parts = [f"<svg width='{width}' height='{h}'>"]
    y = 2
    for label, o, r in rows:
        n = o + r
        parts.append(f"<text x='{label_w - 6}' y='{y + bar_h / 2 + 4}' text-anchor='end' fill='#b6bec8' font-size='11'>{label}</text>")
        x = float(label_w)
        for cnt, color in ((o, "#2297F6"), (r, "#FDB022")):
            if not cnt:
                continue
            w = max((width - label_w - 30) * cnt / maxn, 3.0)
            parts.append(f"<rect x='{x:.1f}' y='{y}' width='{w:.1f}' height='{bar_h}' rx='4' fill='{color}'/>")
            x += w
        parts.append(f"<text x='{x + 6:.1f}' y='{y + bar_h / 2 + 4}' fill='#e6e6e6' font-size='12' font-weight='700'>{n}</text>")
        y += bar_h + gap
    parts.append("</svg>")
    return "".join(parts)


def age_columns_svg(items, width=340, bar_h=14, gap=6, label_w=50):
    # Horizontal age bars growing left to right: items = [(id, weeks)]; the left label is
    # the id only (the id decode lives in the tables below on the same tab), the value sits
    # to the right of the bar. The widget grows downward for any number of rows — the label
    # width is fixed and the id always fits. Zero age gets a minimal stub so the bar shows.
    # Color: FB findings — blue, DD decisions — purple.
    if not items:
        return "<span class='nd'>nothing open</span>"
    maxw = max(w for _, w in items) or 1
    h = len(items) * (bar_h + gap) + 4
    parts = [f"<svg width='{width}' height='{h}'>"]
    y = 2
    for fid, w in items:
        color = "#C084FC" if str(fid).startswith("DD") else "#2297F6"
        bw = max((width - label_w - 30) * w / maxw, 3.0)
        parts.append(f"<text x='{label_w - 6}' y='{y + bar_h / 2 + 4}' text-anchor='end' fill='#b6bec8' font-size='10'>{esc(str(fid))}</text>")
        parts.append(f"<rect x='{label_w}' y='{y}' width='{bw:.1f}' height='{bar_h}' rx='3' fill='{color}'/>")
        parts.append(f"<text x='{label_w + bw + 6:.1f}' y='{y + bar_h / 2 + 4}' fill='#e6e6e6' font-size='11' font-weight='700'>{w}</text>")
        y += bar_h + gap
    parts.append("</svg>")
    return "".join(parts)


def dumbbell_svg(rows, width=340, bar_h=22, gap=14, scale_max=None, unit="$"):
    # Range vs fact: rows = [(size, lo, hi, fact)] on a shared 0..scale_max scale (default —
    # the $ scale COST_SCALE_MAX). The band is the size's range in dashboard colors (#2297F6,
    # same as .bar); the dot is the median fact (green inside the band, red outside, with a
    # red tail back to the boundary).
    if not rows:
        return "<span class='nd'>no data</span>"
    if scale_max is None:
        scale_max = COST_SCALE_MAX
    label_w = 6
    plot_x0, plot_x1 = label_w, width - 128
    plot_w = plot_x1 - plot_x0
    h = len(rows) * (bar_h + gap) + 26

    def X(v):
        return plot_x0 + plot_w * max(0.0, min(v, scale_max)) / scale_max

    parts = [f"<svg width='{width}' height='{h}'>"]
    ticks = (0, scale_max // 3, 2 * scale_max // 3, scale_max)
    for tick in ticks:
        tx = X(tick)
        parts.append(f"<path d='M {tx:.1f} 14 L {tx:.1f} {h - 16}' stroke='#3a4150' stroke-dasharray='4 4' fill='none'/>")
        parts.append(f"<text x='{tx:.1f}' y='{h - 4}' text-anchor='middle' fill='#8b929c' font-size='10'>{unit}{tick}</text>")
    y = 14
    for label, lo, hi, fact in rows:
        x_lo, x_hi = X(lo), X(hi)
        parts.append(f"<text x='{plot_x0}' y='{y - 4}' fill='#e6e6e6' font-size='11' font-weight='700'>{esc(label)}</text>")
        parts.append(f"<rect x='{x_lo:.1f}' y='{y}' width='{max(x_hi - x_lo, 4):.1f}' height='{bar_h}' "
                     f"rx='{bar_h / 2:.0f}' fill='#2297F6' fill-opacity='0.8'/>")
        in_range = lo <= fact <= hi
        x_fact = X(fact)
        if not in_range:
            x_edge = x_hi if fact > hi else x_lo
            parts.append(f"<line x1='{x_edge:.1f}' y1='{y + bar_h / 2:.1f}' x2='{x_fact:.1f}' y2='{y + bar_h / 2:.1f}' "
                         "stroke='#F9303C' stroke-width='3'/>")
        dot = "#2dd4a0" if in_range else "#F9303C"
        parts.append(f"<circle cx='{x_fact:.1f}' cy='{y + bar_h / 2:.1f}' r='6.5' fill='{dot}' stroke='#101216' stroke-width='2'/>")
        fact_txt = str(int(fact)) if float(fact).is_integer() else f"{fact:.1f}"
        lo_txt = str(int(lo)) if float(lo).is_integer() else f"{lo:.1f}"
        hi_txt = str(int(hi)) if float(hi).is_integer() else f"{hi:.1f}"
        parts.append(f"<text x='{plot_x1 + 8}' y='{y + bar_h / 2 + 4:.1f}' fill='#e6e6e6' font-size='11'>"
                     f"{unit}{lo_txt}–{hi_txt} · fact {unit}{fact_txt}</text>")
        y += bar_h + gap
    parts.append("</svg>")
    return "".join(parts)


def formulas_block(key, note=None):
    rows = "".join(f"<tr><td><b>{esc(n)}</b></td><td>{esc(f)}</td></tr>" for n, f in FORMULAS[key])
    note = note or "The canon for the formulas is the shipped references/metrics-contract.md; this is a mirror."
    return ("<details class='formulas'><summary>Formulas of this suite</summary><table>"
            f"{rows}</table><p class='nd'>{note}</p></details>")


def _jsonl_records(path: Path, key: str) -> list:
    """The one tolerant reader of a `.jsonl` file (B-309 t-422): the objects that carry `key`, in file order. A broken line,
    a line that is not an object and an object without `key` are skipped; the file may not exist at all."""
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict) and rec.get(key):
            out.append(rec)
    return out


def parse_ledger(path: Path) -> list:
    """Estimation precedents (size/scenarios): records/estimation-ledger.jsonl, one line = one JSON object.
    Parsing is tolerant: broken lines and missing fields are skipped, the file may not exist at all."""
    return _jsonl_records(path, "task")


def task_cost_totals(sessions: list) -> dict:
    """Cost join by task id from state/cost/*.json (the same by_task the "Cost" tab reads)."""
    acc: dict = defaultdict(lambda: {"cost": 0.0, "priced": False})
    unknown = set()
    for s in sessions:
        for t, v in (s.get("by_task") or {}).items():
            if isinstance(v, dict) and v.get("cost") is not None:
                acc[t]["cost"] += v["cost"]
                acc[t]["priced"] = True
            else:
                unknown.add(t)
    return {t: d["cost"] for t, d in acc.items() if d["priced"] and t not in unknown}


def task_tail_flags(task_id, ob_list):
    """A task's obligations from the shared ledger obligations.md (already filtered to open/ripe in main()).
    The join is tolerant: an exact task-id match or a substring match either way."""
    open_ = ripe_ = False
    n = 0
    for _typ, tsk, ripe_i, _det, _trg in ob_list or []:
        if task_id and tsk and (task_id == tsk or task_id in tsk or tsk in task_id):
            n += 1
            if ripe_i:
                ripe_ = True
            else:
                open_ = True
    return open_, ripe_, n


def parse_backlog_section(path: Path, section_prefix: str, min_cols: int) -> list:
    """A shared parser for a table section of factory-backlog.md, keyed by the heading
    `## <section_prefix>...` (compared lowercased, startswith). Parsing is tolerant: no file or
    no section — an empty list; the row format follows templates/factory-backlog.md."""
    out = []
    if not path.exists():
        return out
    in_section = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            in_section = m.group(1).strip().lower().startswith(section_prefix)
            continue
        if not in_section or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < min_cols or set("".join(cells)) <= {"-", ":", " "} or cells[0].lower() == "id":
            continue
        out.append(cells)
    return out


def parse_deferred_decisions(path: Path) -> list:
    """The factory's deferred decisions (onboarding/gates): factory-backlog.md, the
    "## Deferred decisions..." section. No file/section — an empty list (the banner is then not
    rendered at all); the row format follows templates/factory-backlog.md."""
    if not path.exists():
        return []
    from project_decisions import parse_rows
    rows = parse_rows(path.read_text(encoding="utf-8", errors="replace"))
    out = []
    for row in rows:
        # Typed columns are canonical. Legacy tables retain their positional headings and
        # are mapped explicitly instead of pretending the third column is the trigger.
        out.append({"id": row.get("id", ""),
                    "essence": row.get("essence + where the marker is", ""),
                    "asked": row.get("asked", ""),
                    "trigger": row.get("ripeness trigger", ""),
                    "created": row.get("created", ""),
                    "status": row.get("status", ""),
                    "resolution": row.get("decision with witness", ""),
                    "field_refs": row.get("field_refs", ""),
                    "scope": row.get("scope", "") or "DD",
                    "owner": row.get("owner", ""),
                    "trigger_type": row.get("trigger_type", "") or "manual",
                    "trigger_value": row.get("trigger_value", ""),
                    "resolution_ref": row.get("resolution_ref", "")})
    return out


def completed_s9_since(root: Path, created: str) -> int:
    """Count accepted completed retros since a DD's creation date."""
    try:
        cutoff = datetime.strptime(str(created)[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    count = 0
    for path in sorted_paths(artifact_root(root=root).rglob("pipeline.json")):
        data = C.load_json(path)
        s9 = (data.get("stages") or {}).get("S9") or {}
        try:
            finished = datetime.strptime(str(s9.get("finished"))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if s9.get("status") == "done" and C.gate_approved(data, "B") and finished >= cutoff:
            count += 1
    return count


def parse_factory_findings(path: Path) -> list:
    """Findings about the factory itself: factory-backlog.md, the "## Findings about the
    factory" section. Template columns: id · essence · scope · witness/details · created ·
    status · operator decision (templates/factory-backlog.md). No file/section — an empty list."""
    return parse_backlog_section(path, "findings about the factory", 7)


def age_weeks_of(created) -> "int | None":
    """The age in whole weeks since the date YYYY-MM-DD... at the start of the string; the date
    was not recognized — None (an honest dash higher up the stack, not 0)."""
    m = re.match(r"\d{4}-\d{2}-\d{2}", str(created or ""))
    if not m:
        return None
    days = (date.today() - datetime.strptime(m.group(0), "%Y-%m-%d").date()).days
    return days // 7


def deferred_decisions_table(dd_open: list) -> str:
    """The full table of open deferred decisions — the same render that used to live in the
    header banner; now reused only by the "Factory" tab (the header keeps just the signal line
    about the ripe ones)."""
    dd_sorted = sorted(dd_open, key=lambda d: not d["ripe"])
    rows_html = "".join(
        f"<tr class='ripe'><td>{esc(d['id'])}</td><td>{esc(d['essence'])} <span class='dd-tag'>&#9679; Ready to perform</span></td>"
        f"<td>{esc(d['file'])}</td><td>{esc(d['trigger'])}</td></tr>" if d["ripe"] else
        f"<tr><td>{esc(d['id'])}</td><td>{esc(d['essence'])}</td><td>{esc(d['file'])}</td><td>{esc(d['trigger'])}</td></tr>"
        for d in dd_sorted)
    return ("<table class='tight1 dd'><tr><th>id</th><th>essence</th><th>marker (file)</th><th>trigger</th></tr>"
            f"{rows_html}</table>")


def parse_journal(path: Path) -> list:
    """The factory event journal: records/journal.jsonl, one line = one JSON object (written by
    log_append.py). Parsing is tolerant: broken lines are skipped, the file may be absent."""
    return _jsonl_records(path, "event")


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _flat_frontmatter(path: Path) -> dict:
    """Flat frontmatter (key: value) with no dependencies — like hooklib.parse_frontmatter."""
    try:
        m = _FM_RE.match(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def load_maintenance(root: Path) -> dict:
    """The "Test suite upkeep" block of the "Factory" tab: live counters from the files (cases in
    quarantine, active red_lock, DEBT open/overdue by sla_due) + the flags of the LAST qa-maintainer
    report (artifacts/maintenance/<date>.json: fired checks, needs_human, escalations, fix_requests,
    calibration candidates). No report → the flags say "none yet" explicitly, not blank."""
    today = date.today()
    quarantined, red_locked = [], []
    tc_root = artifact_root(root=root)
    for c in (C.case_glob(tc_root, tc_root) if tc_root.exists() else []):
        fm = _flat_frontmatter(c)
        if fm.get("quarantine"):
            quarantined.append(f"{fm.get('id', c.stem)} ({fm.get('quarantine')}, since {fm.get('quarantine_since', '?')})")
        if fm.get("red_lock"):
            red_locked.append(f"{fm.get('id', c.stem)} → {fm.get('red_lock')}")
    debt_open, debt_overdue = [], []
    bugs_root = root / "qa-factory" / "bugs"
    for d in (sorted_paths(bugs_root.glob("DEBT-*.md")) if bugs_root.exists() else []):
        fm = _flat_frontmatter(d)
        if fm.get("status", "Open") == "Open":
            debt_open.append(fm.get("id", d.stem))
            m = re.match(r"\d{4}-\d{2}-\d{2}", str(fm.get("sla_due", "")))
            if m and datetime.strptime(m.group(0), "%Y-%m-%d").date() < today:
                debt_overdue.append(f"{fm.get('id', d.stem)} (due {m.group(0)}, {fm.get('kind', '?')})")
    rep = {"exists": False, "file": "", "fired": [], "needs_human": 0, "escalations": [],
           "fix_requests": 0, "calibration": []}
    mdir = artifact_root(root=root) / "maintenance"
    reports = sorted_paths(mdir.glob("*.json")) if mdir.exists() else []
    if reports:
        last = reports[-1]
        try:
            data = json.loads(last.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = {}
        rep.update(exists=True, file=last.name,
                   fired=[f"{c.get('check')}: {c.get('evidence', '')}" for c in data.get("checks", []) if c.get("result") == "fired"],
                   needs_human=len(data.get("needs_human", [])),
                   escalations=[f"{e.get('kind')}: {len(e.get('items', []))}" for e in data.get("escalations", [])],
                   fix_requests=len(data.get("fix_requests", [])),
                   calibration=list(data.get("calibration_candidates", [])))
    return {"quarantined": quarantined, "red_locked": red_locked, "debt_open": debt_open,
            "debt_overdue": debt_overdue, "report": rep}


def maintenance_section(m: dict) -> str:
    def cell(n, warn=False):
        cls = "warn" if (warn and n) else ("ok" if not n else "")
        return f"<span class='{cls}'>{n}</span>" if cls else str(n)
    def ul(items, empty):
        return ("<ul class='nd'>" + "".join(f"<li>{esc(i)}</li>" for i in items[:12]) +
                (f"<li>… {len(items) - 12} more</li>" if len(items) > 12 else "") + "</ul>") if items else f"<p class='nd'>{empty}</p>"
    r = m["report"]
    live = ("<table><tr><th>cases in quarantine</th><th>active red_lock</th><th>DEBT open</th><th>DEBT overdue</th></tr>"
            f"<tr><td>{cell(len(m['quarantined']))}</td><td>{cell(len(m['red_locked']))}</td>"
            f"<td>{cell(len(m['debt_open']))}</td><td>{cell(len(m['debt_overdue']), warn=True)}</td></tr></table>")
    if not r["exists"]:
        flags = "<p class='nd'>No historical upkeep report. Live counts describe inspected records only.</p>"
    else:
        flags = (f"<p class='nd'>Last report: {esc(r['file'])} · awaiting the human's decision: {cell(r['needs_human'], warn=True)} · "
                 f"fix requests to the automator: {r['fix_requests']}</p>"
                 f"<h4>Fired checks</h4>{ul(r['fired'], 'all checks clean')}"
                 f"<h4>Escalations</h4>{ul(r['escalations'], 'none')}"
                 f"<h4>Calibration candidates</h4>{ul(r['calibration'], 'none')}")
    warn = bool(m["debt_overdue"] or r["fired"] or r["needs_human"])
    open_attr = " open" if warn else ""
    return (f"<details class='formulas'{open_attr}><summary>Recorded test health</summary>"
            f"{live}{flags}"
            f"<h4>In quarantine</h4>{ul(m['quarantined'], 'none')}"
            f"<h4>Overdue debt</h4>{ul(m['debt_overdue'], 'none')}"
            "<p class='nd'>Sources — the case files under test-cases/ (quarantine, red_lock), bugs/DEBT-*.md (status, sla_due), "
            "qa-factory/artifacts/maintenance/*.json (the last imported maintenance report). No scheduled maintenance is required.</p></details>")


def split_marker(text: str):
    """The row's essence also carries the marker's file inline ("...— marker in `path`, ...");
    we split it out for the narrow "marker (file)" column. No marker — the file is "—" and the
    essence is returned as is."""
    m = re.search(r"marker\s+in\s+`([^`]+)`", text, re.IGNORECASE)
    if not m:
        return text.strip(), "—"
    essence = re.sub(r"[—\-–]\s*$", "", text[:m.start()]).strip()
    return essence or text.strip(), m.group(1)


def deferred_decision_ripe(trigger: str, created: str, extra_text: str) -> bool:
    """Only explicit evidence marks a legacy decision ripe; age is informational."""
    return bool(re.search(r"\bripe\b", str(extra_text).lower()))


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if not n:
        return None
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _plural_task(n):
    return "task" if n == 1 else "tasks"


def estimate_signals(records: list) -> list:
    """>=3 latest precedents of one size AND ONE UNIT in a row with direction=='above' (or all 'below') — the scale has drifted.

    The unit is the size letter's (CD1-5, OH3-15): rows before, functions now. A change of unit is a change of what the
    letter counts, never a drift, so the cohorts are keyed `(unit, size)` and a record of an unknown unit joins none."""
    from retro_numbers import record_unit            # lazy, as the file's other retro_numbers reads: the ONE reader of a record's unit
    by_size: dict = defaultdict(list)
    for r in sorted(records, key=lambda r: str(r.get("ts") or "")):
        size = (r.get("forecast") or {}).get("size_final") or (r.get("forecast") or {}).get("size_initial")
        unit = record_unit(r.get("forecast"))
        if not size or unit is None:
            continue
        by_size[(unit, size)].append((r.get("delta") or {}).get("direction"))
    msgs = []
    for unit in ("requirements", "functions"):
        for size in SIZE_ORDER:
            seq = by_size.get((unit, size))
            if not seq or len(seq) < 3:
                continue
            tail = seq[-1]
            if tail not in ("above", "below"):
                continue
            n = 0
            for d in reversed(seq):
                if d == tail:
                    n += 1
                else:
                    break
            if n >= 3:
                verb = "underestimates" if tail == "above" else "overestimates"
                cause = "above" if tail == "above" else "below"
                where = " on the function count" if unit == "functions" else ""
                msgs.append(f"The scale {verb} {size}{where}: {n} {_plural_task(n)} in a row {cause} the range")
    return msgs


def size_unit_mark(forecast) -> str:
    """` (rows)` beside the size letter of a precedent counted in the register's rows (a record of before OH3-15, CD1-5); nothing
    for a functions record. The unit is `retro_numbers.record_unit`'s, the one reader; an unknown unit says so."""
    from retro_numbers import record_unit
    if not (forecast or {}).get("size_final") and not (forecast or {}).get("size_initial") and not (forecast or {}).get("size"):
        return ""
    unit = record_unit(forecast)
    return " (rows)" if unit == "requirements" else "" if unit == "functions" else " (unit unknown)"


def revision_matrix(records: list) -> dict:
    cnt: dict = defaultdict(int)
    for r in records:
        sc = (r.get("delta") or {}).get("size_change")
        if not sc:
            continue
        parts = [p.strip() for p in re.split(r"\s*(?:→|->)\s*", str(sc)) if p.strip()]
        if len(parts) == 2:
            cnt[(parts[0], parts[1])] += 1
    return cnt


def driver_counts(records: list) -> dict:
    cnt: dict = defaultdict(int)
    for r in records:
        for d in r.get("drivers") or []:
            d = str(d).strip()
            if d:
                cnt[d] += 1
    return cnt


def size_arrow(rec: dict) -> str:
    # `size_initial`/`size_final` are what sizing.py records now; a record written before
    # those names existed carries a single `size`, and reading only the new pair left the
    # precedents table empty on TP1-15045.
    f = rec.get("forecast") or {}
    si, sf = f.get("size_initial") or f.get("size"), f.get("size_final")
    if not si and not sf:
        return "—"
    if not sf or not si or sf == si:
        return esc(sf or si)
    order = {s: i for i, s in enumerate(SIZE_ORDER)}
    grew = order.get(sf, -1) > order.get(si, -1)
    cls = " class='warn'" if grew else ""
    return f"<span{cls}>{esc(si)} → {esc(sf)}</span>"


def scenario_cell(rec: dict) -> str:
    f, a = rec.get("forecast") or {}, rec.get("actual") or {}
    rng = f.get("range_final") or f.get("range_initial")
    fact = a.get("scenarios")
    direction = (rec.get("delta") or {}).get("direction")
    cls = {"in": "ok", "above": "warn", "below": "skip"}.get(direction, "")
    rng_txt = f"{rng[0]}–{rng[1]}" if isinstance(rng, (list, tuple)) and len(rng) == 2 else "—"
    fact_txt = fact if fact is not None else "—"
    return f"<span class='{cls}'>{esc(rng_txt)} → {esc(fact_txt)}</span>"


def drivers_cell(rec: dict) -> str:
    drivers = rec.get("drivers") or []
    full = "; ".join(str(d) for d in drivers if str(d).strip())
    if not full:
        return "—"
    short = full if len(full) <= 60 else full[:57] + "…"
    return f"<span title='{esc(full)}'>{esc(short)}</span>"


def parse_cases(root: Path) -> list:
    cases=[]
    art=artifact_root(root=root)
    if not art.exists(): return cases
    for task in sorted_paths(art.iterdir()):
        if not task.is_dir() or task.name in {'archive','_archive','requirements','releases'}: continue
        for cid, record in C.case_index(task).items():
            path=record['path']; text=path.read_text(encoding='utf-8',errors='replace')
            fm=parse_frontmatter(text) or {}
            heading=re.search(r'^#\s+(.*)$',text,re.M)
            fm.update(id=cid, task=task.name, _path=str(path),
                      title=fm.get('title') or (heading.group(1) if heading else cid))
            cases.append(fm)
    return cases


# The pyramid, bottom-up, with the words the board shows. Read from test-plan.md's `level`
# column (contract.PLAN_LEVELS) through case -> automation-manifest `plan_row` -> plan row.
# Until 0.3.0 this was decided by `"ui" in test_name`, which put three frontend component
# tests under "API autotests" (TP2-2290) — a classification nobody had recorded.
LEVEL_LABELS = {
    "unit": "Unit autotests",
    "component": "Component autotests",
    "api": "API autotests",
    "integration": "Integration autotests",
    "e2e-ui": "UI autotests (e2e)",
}
LEVEL_NOTES = {
    "unit": "pyramid base: a function or class in isolation",
    "component": "one component or module, its collaborators stubbed",
    "api": "a service through its own interface",
    "integration": "two or more parts together",
    "e2e-ui": "through the user interface",
}
LEVEL_NONE = "level not recorded"


def plan_levels(d: Path) -> dict:
    """TS-n -> level, from the story's test-plan.md."""
    try:
        return {r["ts"]: str(r.get("level") or "").strip().lower()
                for r in C.parse_plan(C.artifact(d, "test-plan.md"))}
    except Exception:
        return {}


_LEVEL_GLOBS: dict = {}  # set in main() once the project root is resolved


def project_config(root) -> dict:
    """<root>/qa-factory/config.json as a dict, `{}` when it is absent, unreadable or not an object: the one
    place the dashboard reads the project's config (`level_globs` and the story card both ask here)."""
    try:
        cfg = json.loads((Path(root) / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))   # BOM as the pass reads it
    except (OSError, ValueError, TypeError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def level_globs(root: Path) -> dict:
    """`run.levels` from the project config: level -> path patterns.

    For the tests the factory did not write — a project's own regression suite carries no
    case and no plan row, so nothing links it to a level. Onboarding records the layers it
    finds; what matches nothing stays LEVEL_NONE rather than being guessed into a tier.
    It lives INSIDE `run` on purpose: readiness compares a config's top-level keys against
    the template, so a new top-level key would demand a re-onboarding of every install."""
    try:
        cfg = project_config(root)
        levels = ((cfg.get("run") or {}).get("levels") or {})
        return {str(k).strip().lower(): [str(v) for v in (vs if isinstance(vs, list) else [vs])]
                for k, vs in levels.items() if str(k).strip().lower() in LEVEL_LABELS}
    except Exception:
        return {}


def level_for(case: str, tid: str, case_levels: dict, globs: dict) -> str:
    """The recorded level of one result row, or LEVEL_NONE. Never a guess from the name."""
    lv = str(case_levels.get(str(case or "").strip()) or "").strip().lower()
    if lv in LEVEL_LABELS:
        return lv
    path = str(tid or "").split("::")[0].replace("\\", "/").strip()
    matches = {name for name, patterns in globs.items() for pat in patterns
               if fnmatch.fnmatch(path, str(pat).replace("\\", "/"))
               or fnmatch.fnmatch(path, str(pat).replace("\\", "/").rstrip("/") + "/*")}
    return next(iter(matches)) if len(matches) == 1 else LEVEL_NONE


# --- the story projection: one row per instance the story actually owns -----------------
# Built on TP1-15045, where the board read 54 "checks" (39 result rows mixed with 14
# never-run plan rows), 0 of 3 failures triaged, every level "not recorded" and every test
# named by its pytest node id. Each join below is the one the records already carry.

DEAD_ROW_NOTE = "SUPERSEDED DUPLICATE"


def is_dead_manifest_row(entry) -> bool:
    """A manifest row a later window replaced. It stays in the file (a fragment may not
    delete a row) with its note marked, so every reader must skip it explicitly — nine of
    the 34 rows on TP1-15045, which is the difference between 34 and 25 instances."""
    if not isinstance(entry, dict):
        return True
    return any(str(entry.get(field) or "").strip().startswith(DEAD_ROW_NOTE)
               for field in ("note", "critic_note"))


def live_manifest_entries(manifest) -> list:
    return [e for e in C.manifest_tests(manifest) if not is_dead_manifest_row(e)]


def is_stale_unresolved(row) -> bool:
    """An unresolved row kept only as a label after the block it named was cleared."""
    return str((row or {}).get("detail") or "").strip().upper().startswith("STALE")


_TERMINAL = ("passed", "pass", "failed", "fail", "error")


def run_rows_by_alias(report: dict) -> dict:
    """Every spelling a current result answers to -> that result.

    A terminal row wins over a `partial` one for the same instance: the report keeps both
    (an early ambiguous attempt and the settled one), and reading whichever came first
    reported a green instance as unfinished."""
    out: dict = {}
    for row in report.get("current_results", report.get("results")) or []:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("test_id") or row.get("test") or "").strip()
        keys = [str(row.get("instance_id") or "").strip(), tid,
                tid.split("::")[-1] if "::" in tid else ""]
        better = C.result_status(row) in _TERMINAL
        for key in keys:
            if not key:
                continue
            prior = out.get(key)
            if prior is None or (better and C.result_status(prior) not in _TERMINAL):
                out[key] = row
    return out


def result_status_of(row) -> str:
    return C.result_status(row or {})


def match_run_row(entry: dict, by_alias: dict, cfg=None):
    """`cfg`: the config a caller looping over many entries resolved once (B-013); None resolves per call, as before."""
    keys = list(C.instance_id_aliases(entry, cfg))
    for field in ("report_test_id", "selector", "test", "marker"):
        value = str(entry.get(field) or "").strip()
        if value:
            keys.append(value)
            if "::" in value:
                keys.append(value.split("::")[-1])
    for key in keys:
        row = by_alias.get(str(key))
        if row is not None:
            return row
    return None


def instance_level(entry: dict, run_row, case: str, case_levels: dict, globs: dict) -> str:
    """The level, from the three places it is actually recorded, in order of directness:
    the run's own `profile_id`, the case's plan row, then the project's `run.levels` globs
    matched against the FILE PATH (the dotted module path never matches `tests/**`)."""
    profile = str((run_row or {}).get("profile_id") or "").strip().lower()
    if profile in LEVEL_LABELS:
        return profile
    recorded = str((run_row or {}).get("level") or "").strip().lower()
    if recorded in LEVEL_LABELS:
        return recorded
    lv = str(case_levels.get(str(case or "").strip()) or "").strip().lower()
    if lv in LEVEL_LABELS:
        return lv
    path = str(entry.get("file") or "").replace("\\", "/").strip()
    if not path:
        path = str((run_row or {}).get("file") or "").replace("\\", "/").strip()
    best, best_len = LEVEL_NONE, -1
    for name, patterns in (globs or {}).items():
        for pat in patterns:
            pattern = str(pat).replace("\\", "/")
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.rstrip("/") + "/*"):
                if len(pattern) > best_len:
                    best, best_len = name, len(pattern)
    return best


def bugs_by_case(bugs: list) -> dict:
    """case id -> the bug records that name it in `found_by` (one bug may name several)."""
    out: dict = {}
    for b in bugs or []:
        for case in C.case_ids(b.get("found_by")) or C.case_ids(b.get("case")):
            out.setdefault(case, []).append(b)
    return out


_LEVELS_NOTE_SHOWN = False   # the "proof levels unavailable" note is printed once per process


def instance_basis(entry: dict, run_row, task_root=None, manifest=None) -> str:
    """One short line of why this row's result can be believed: the critic's verdict in its own
    words, and for an approving verdict how sure the check is (D-0010/D-0012, FR-35).

    With the task root the level is `proof_level.reached` (the receipts, validated against the
    test's bytes); a projection without one reads the level the row's own `probe` block carries."""
    import ledger as L
    import proof_level as PL
    status = C.result_status(run_row or {})
    reason = str((run_row or {}).get("reason") or "").strip()
    if status in ("failed", "fail", "error") or str(entry.get("status") or "") == "red":
        return reason[:160] or "recorded red, no message captured"
    verdict = L.verdict_of(entry)
    try:
        words = PL.review_words(verdict)
        if verdict not in ("approved", "approved_with_fixes"):
            return words
        if task_root:
            return words + " · " + L.proof_shown(entry, manifest, Path(task_root))[1]
        level = PL.level_of(entry.get("probe") or {})
        return words + " · " + PL.words(level)
    except PL.LevelsUnavailable as exc:
        # The dashboard never crashes over the proof-level vocabulary (P1): the row says what it can
        # and the operator is told once, on stderr, how to get the levels back.
        global _LEVELS_NOTE_SHOWN
        if not _LEVELS_NOTE_SHOWN:
            _LEVELS_NOTE_SHOWN = True
            print(f"dashboard: proof levels are not shown - {exc}", file=sys.stderr)
        return f"critic verdict: {verdict or 'not recorded'} (proof level not shown)"


def story_projection(task: dict, titles: dict, globs: dict, bugs: list, manual: list) -> dict:
    """Everything the story expand shows, joined once: instances, their level, result,
    triage verdict and bug, plus the rows that never ran and why."""
    manifest = task.get("manifest") or {}
    report = task.get("report") or {}
    by_alias = run_rows_by_alias(report)
    # t-323 A2 (critic t-322 B-F1): the triage is read through `contract.bind_triage`, the one binding the ledger, gate B,
    # S7 and the traceability table read - a row `x[chromium]` is the verdict of the run report's `x` here too
    triage_rows = C.triage_rows(task.get("triage_doc") or {})
    run_failures = C.triage_failures(report)[0]
    case_levels = task.get("case_levels") or {}
    bug_map = bugs_by_case(bugs)
    entries = live_manifest_entries(manifest)
    if not entries:
        # No manifest (a story imported before one was written, or a project that automates
        # outside the factory): the run report's own rows are then the only statement about
        # what ran, and dropping them would report a story that ran as a story with no tests.
        entries = [dict(row, selector=C.result_id(row))
                   for row in report.get("current_results", report.get("results")) or []
                   if isinstance(row, dict)]
    rows = []
    for entry in entries:
        run_row = match_run_row(entry, by_alias)
        status = C.result_status(run_row or {})
        if status not in _TERMINAL:
            # `partial` is the report's word for "this attempt did not settle it". B-310 (d): the manifest's `green` is what
            # the automator wrote BEFORE the run - it never becomes `passed` here (FR-18: a manifest word is no execution).
            # A row the run observed red (`case_stamp.is_red_row`, the one reader: a `partial` whose `raw_status` is red) is
            # `failed`; the manifest's own `red` stays `failed`; any other row keeps its own word, or `not recorded`.
            import case_stamp as CS   # lazy: the stamp is the module that hosts the red-row rule (it imports no dashboard)
            if CS.is_red_row(run_row) or str(entry.get("status") or "") == "red":
                status = "failed"
            else:
                status = status or "not recorded"
        instance = C.test_instance_id(entry)
        attempt = str((run_row or {}).get("attempt_id") or "").strip()
        triage = C.triage_row_for(run_failures, triage_rows,
                                  [instance, str(entry.get("selector") or ""), str((run_row or {}).get("test_id") or ""),
                                   str((run_row or {}).get("instance_id") or "")], attempt,
                                  C.result_status(run_row or {}))
        cases = C.manifest_test_links(entry)
        case = cases[0] if cases else ""
        verdict = str((triage or {}).get("verdict") or "")
        bug_records = [b for c in cases for b in bug_map.get(c, [])]
        red = status in ("failed", "fail", "error")
        green = status in ("passed", "pass")
        if red and not verdict and bug_records:
            # A bug record IS the triage verdict, written down: the analyst's row may live
            # in the bug file rather than triage.json when the failure was filed at S8.
            verdict = "APP_BUG"
        node = str((run_row or {}).get("test_id") or entry.get("selector") or instance)
        rows.append({
            "case": case, "cases": cases, "instance": instance,
            "title": titles.get(case) or C.function_name(instance) or instance,
            "node": node, "level": instance_level(entry, run_row, case, case_levels, globs),
            "status": status,
            "state": (("env" if verdict == "ENV_ISSUE" else "open" if verdict == C.TRIAGE_MISREAD_VERDICT else "bug")
                      if red else "pass" if green else "open"),
            "verdict": verdict, "triage": triage or {},
            "bugs": [str(b.get("id") or "") for b in bug_records if red],
            "basis": instance_basis(entry, run_row, task.get("artifact_path"), manifest),
            "shape": str(entry.get("shape") or ""),
        })
    rows.sort(key=lambda r: (r["level"], r["case"], r["node"]))
    unresolved = [u for u in C.manifest_unresolved(manifest)
                  if isinstance(u, dict) and not is_stale_unresolved(u)]
    handed = [u for u in unresolved if str(u.get("reason") or "").startswith("handed_to_person")]
    design = [u for u in unresolved if str(u.get("reason") or "").split(":")[0]
              in ("impossible", "deferred_by_decision")]
    return {"rows": rows, "handed": handed, "design": design, "manual": manual,
            "deferred": [u for u in design if str(u.get("reason") or "").startswith("deferred")],
            "unreachable": [u for u in design if str(u.get("reason") or "").startswith("impossible")]}


# The factory's own vocabulary for "why this case has no green run"
# (automation-manifest.json unresolved[].reason), in the words a reader needs.
UNRESOLVED_WORDS = {
    "pending_implementation": "awaiting implementation",
    "blocked_by_env": "blocked by the environment",
    "impossible": "cannot be verified",
    "deferred_by_decision": "deferred by a decision at the gate",
}


def feature_key(raw) -> str:
    """The parent ticket's KEY alone, from whatever shape the tracker returned.

    A tracker may answer `TP1-1847`, `TP1-1847 "Attachments"` or
    `{"id": ..., "title": ...}`. Grouped verbatim, those are three features instead of
    one. Two stories of the same feature must land in the same group or the fold is
    decoration."""
    if isinstance(raw, dict):
        raw = raw.get("id") or raw.get("key") or ""
    return str(raw or "").strip().split()[0] if str(raw or "").strip() else ""


def ledger_path(root: Path, name: str) -> Path:
    """A project ledger (obligations.md, factory-backlog.md) at its canonical path.

    Canon is `qa-factory/<name>` — what the templates say, what `s0.md` reads and what the
    roles are told to write. This file and audit A16 read `qa-factory/state/<name>` until
    0.3.0, so the banner counted open obligations in a file nothing writes. The legacy path
    is still accepted for projects that already have one there."""
    live = root / "qa-factory" / name
    if live.exists():
        return live
    legacy = root / "qa-factory" / "state" / name
    return legacy if legacy.exists() else live


def is_archived_task(d: Path) -> bool:
    """`pipeline.json`'s `archived` flag — set by a person through qa-doctor, never a role.

    Until 0.3.0 S9 set it on its own inference ("the feature's last sibling closed"), which
    is why the factory went looking for sibling tickets at all. It now means only "the human
    asked to stop showing this", so it can hide an unfinished story — stage_guard --stories
    names those separately rather than letting the flag silence them."""
    try:
        return bool(json.loads((d / "pipeline.json").read_text(encoding="utf-8", errors="replace")).get("archived"))
    except Exception:
        return False


def parse_taskruns(root: Path, include_archive: bool = False) -> list:
    """Actual runs per task: current run-report.json of every artifacts/<task>/ folder."""
    out = []
    art = artifact_root(root=root)
    if not art.exists():
        return out
    # A closed feature is marked by `"archived": true` in its own pipeline.json, not by a
    # moved folder (moving one breaks the register lookup every TC-*.md depends on — see
    # validate_artifacts.register_path_for). Folders under archive/ or _archive/ are still
    # read, for projects archived before that change.
    # A folder whose name starts with "_" is the factory's own scratch space, never a story:
    # on TP1-15045 `artifacts/_selftest` rendered as a task of the project, with its own
    # traffic light and lifecycle row, beside the one story the person actually asked for.
    candidates = [(d, is_archived_task(d), "") for d in sorted_paths(art.iterdir())
                  if d.is_dir() and not d.name.startswith("_")
                  and d.name not in ("requirements", "releases", "archive")]
    for legacy in ("archive", "_archive"):
        if include_archive and (art / legacy).exists():
            for rr0 in sorted_paths((art / legacy).rglob("run-report.json")):
                d2 = rr0.parent
                candidates.append((d2, True, d2.parent.name if d2.parent.name != legacy else ""))
    for d, archived, feat_hint in candidates:
        rr = C.artifact(d, "run-report.json")
        planned_only = not rr.exists()
        try:
            rep = json.loads(rr.read_text(encoding="utf-8", errors="replace")) if not planned_only else {}
        except Exception:
            # A malformed report is still a visible task; hiding it falsely reports no work.
            rep, planned_only = {}, True
        mtests, munresolved, mcase_levels, manifest_entries = set(), {}, {}, []
        mj: dict = {}
        mp = C.artifact(d, "automation-manifest.json")
        if mp.exists():
            try:
                mj = json.loads(mp.read_text(encoding="utf-8", errors="replace")) or {}
                manifest_entries = C.manifest_tests(mj)
                mtests = {str(e.get("test_id") or e.get("test") or "").strip()
                          for e in manifest_entries} - {""}
                # Why a case has no green run, as the FACTORY recorded it. Without this
                # join a story written ahead of its implementation shows only skips with
                # no reason (TP2-2290) while "pending_implementation" sits right
                # here, in unresolved[], unread.
                munresolved = {str(u.get("case") or "").strip(): str(u.get("reason") or "")
                               for u in (mj.get("unresolved") or []) if isinstance(u, dict)}
                munresolved.pop("", None)
                # The level the PLAN recorded for this case, carried here through the
                # manifest's plan_row. Every link already exists; nothing new is authored.
                ts_level = plan_levels(d)
                for e in (mj.get("tests") or []):
                    if not isinstance(e, dict):
                        continue
                    lv = ts_level.get(str(e.get("plan_row") or "").strip(), "")
                    if str(e.get("case") or "").strip() and lv:
                        mcase_levels[str(e["case"]).strip()] = lv
                # The manifest of TP1-15045 carried no plan_row on any of its 34 rows,
                # so the map above stayed empty and a handed case read "—"; the case file's
                # own `Plan row:` reaches the same plan column.
                try:
                    for key, lv in C.case_levels(d).items():
                        mcase_levels.setdefault(str(key), lv)
                except Exception:
                    pass
            except Exception:
                mtests, munresolved, mcase_levels, manifest_entries, mj = set(), {}, {}, [], {}
        tri, triage_doc = [], {}
        tp = C.artifact(d, "triage.json")
        if tp.exists():
            try:
                triage_doc = json.loads(tp.read_text(encoding="utf-8", errors="replace")) or {}
                tri = triage_doc.get("triage") or []
            except Exception:
                tri, triage_doc = [], {}
        feat = feat_hint
        if not feat:
            pp = d / "pipeline.json"
            if not pp.exists():  # pre-0.3.0 layout
                pp = root / "qa-factory" / "state" / d.name / "pipeline.json"
            try:
                pj = json.loads(pp.read_text(encoding="utf-8", errors="replace")) if pp.exists() else {}
                feat = feature_key(pj.get("parent_feature") or pj.get("parent"))
            except Exception:
                feat = ""
        lifecycle = C.load_json(d / "state/controller.json")
        pinned_cases = C.case_index(d)
        structured_plan = C.load_json(d / "work/test-plan.json")
        from check_delivery import case_version_reasons, lifecycle_reasons
        case_lifecycle_issues = case_version_reasons(d) + lifecycle_reasons(d)
        from coverage_contract import coverage_projection
        coverage = coverage_projection(d, rep)
        ledger = C.load_json(C.artifact(d, "ledger.json"))
        from delivery_summary import build as delivery_projection
        out.append({"task": d.name, "lifecycle": lifecycle, "planned_cases": pinned_cases,
                    "delivery_summary": delivery_projection(d, ledger), "ledger": ledger,
                    "coverage": coverage, "manual_evidence": ledger.get("manual_evidence", {}), "artifact_path": str(d.resolve()),
                    "execution_jobs": [C.load_json(p) for p in sorted_paths((d / "state/execution-jobs").glob("*.json"))],
                    "environment_jobs": [C.load_json(p) for p in sorted_paths((d / "state/environment-jobs").glob("*.json"))],
                    "structured_plan": structured_plan, "report": rep, "manifest_tests": mtests,
                    "unresolved": munresolved, "case_levels": mcase_levels,
                    "manifest_entries": manifest_entries, "triage": tri, "feature": feat,
                    "manifest": mj, "triage_doc": triage_doc,
                    "pipeline": C.load_json(d / "pipeline.json"),
                    "traceability": C.load_json(C.artifact(d, C.TRACE_FILE)),
                    "planned_only": planned_only, "case_lifecycle_issues": case_lifecycle_issues,
                    "projection_stale": any((d / "state" / name).exists() for name in
                                            ("projection-stale.json", "environment-projection-stale.json",
                                             "manifest-projection-stale.json")),
                    "archived": archived})
    return out


def delivery_summary_html(taskruns):
    delivery_rows = []
    comparison_rows = []
    for task in taskruns:
        summary = task.get('delivery_summary') or {}
        if not summary:
            continue
        counts = summary.get('counts') or {}
        cells = ''.join('<td>' + esc('unknown' if counts.get(key) is None else str(counts.get(key, 0))) + '</td>' for key in
                        ('planned', 'executed', 'planned_manual', 'executed_manual', 'verified',
                         'failed', 'unverified', 'env_blocked', 'deferred'))
        delivery_rows.append('<tr><td>' + esc(task['task']) + '</td>' + cells + '</tr>')
        for gap in summary.get('comparison_gaps') or []:
            comparison_rows.append('<tr><td>' + esc(task['task']) + '</td><td>' +
                                   esc(str(gap.get('case_id', 'unidentified'))) + '</td><td>awaiting_before</td><td>' +
                                   esc(str(gap.get('reason', 'unverified comparison'))) + '</td></tr>')
    if delivery_rows:
        return ('<section><h2>Recorded verification</h2><p>The report and dashboard use the same delivery projection. '
                'Rows and instances are separate units; no cross-unit completion ratio is implied. An unverified result is not a pass.'
                '</p><table><tr><th>Task</th><th>Planned rows</th><th>Executed instances</th>'
                '<th>Manual cases planned</th><th>Manual attempts executed</th><th>Verified rows</th>'
                '<th>Failed rows</th><th>Unverified rows</th><th>Environment blocked rows</th><th>Deferred rows</th></tr>'
                + ''.join(delivery_rows) + '</table>'
                + ('<h3>Before/after comparisons</h3><p>Current after-run outcomes remain independent. '
                   'A missing before capture leaves only the comparison unverified.</p><table><tr><th>Task</th><th>Case</th>'
                   '<th>State</th><th>Gap</th></tr>' + ''.join(comparison_rows) + '</table><p>Where can the before state be checked '
                   '(stand and revision), or will you perform the comparison yourself, including in production?</p>'
                   if comparison_rows else '') + '</section>')
    return ''


PILL_CLASS = {"pass": "p-ok", "bug": "p-bug", "env": "p-env", "wait": "p-wait",
              "open": "p-grey", "none": "p-grey"}
RESULT_WORD = {"pass": "pass", "bug": "fail", "env": "fail", "wait": "wait"}
# Where a row lands in the traffic light and in the pyramid. "open" is a row that has no
# terminal result at all (blocked, skipped, never run) — never counted as a pass.
STATE_INDEX = {"pass": 0, "env": 1, "open": 1, "bug": 2}
INSTANCE_TH = ("<tr><th>case</th><th>what we verify</th><th>level</th><th>result</th>"
               "<th>triage</th><th>basis / tail</th></tr>")
PERSON_TH = ("<tr><th>case</th><th>what we verify</th><th>level</th><th>result</th>"
             "<th>why with you</th><th>what to do</th></tr>")
NO_OWNER = "Nobody assigned, no trigger recorded — assign an owner or record the condition."


def case_cell(title, node) -> str:
    """The case as a person reads it; the pytest node id only on hover, in an overlay
    positioned out of flow so the tooltip never changes the table's height. Until 0.7.12 the
    node id WAS the name, and all 53 rows of TP1-15045 read as function names."""
    nid = esc(node)
    return (f"<span class='case' title='{nid}'><span class='t'>{esc(title)}</span>"
            f"<span class='id'>{nid}</span></span>")


def pill(text, kind) -> str:
    return f"<span class='pill {PILL_CLASS.get(kind, 'p-grey')}'>{esc(text)}</span>"


def instance_row_html(r) -> str:
    verdict = str(r.get("verdict") or "")
    cls = "warn" if verdict == "APP_BUG" else "skip" if verdict else ""
    tri = f"<span class='{cls}'>{esc(verdict)}</span>" if verdict else "—"
    if r.get("bugs"):
        tri += " &rarr; " + esc(", ".join(b for b in r["bugs"] if b))
    return (f"<tr data-case-id='{esc(r['case'])}' data-result='{esc(r['status'])}'>"
            f"<td style='white-space:nowrap'>{esc(r['case'] or '—')}</td>"
            f"<td>{case_cell(r['title'], r['node'])}</td>"
            f"<td class='lv'>{esc(r['level'])}</td>"
            f"<td>{pill(RESULT_WORD.get(r['state']) or r['status'], r['state'])}</td>"
            f"<td>{tri}</td><td>{esc(r['basis'])}</td></tr>")


def person_row_html(case, title, node, level, why, what) -> str:
    return (f"<tr data-case-id='{esc(case)}' data-result='wait'>"
            f"<td style='white-space:nowrap'>{esc(case or '—')}</td>"
            f"<td>{case_cell(title, node)}</td><td class='lv'>{esc(level)}</td>"
            f"<td>{pill('wait', 'wait')}</td><td>{esc(why)}</td><td>{esc(what)}</td></tr>")


def level_group_html(summary, rows, open_=None) -> str:
    """A level stays collapsed only when everything inside it is green."""
    if not rows:
        return ""
    is_open = all(r.get("state") == "pass" for r in rows) is False if open_ is None else open_
    body = "<table>" + INSTANCE_TH + "".join(instance_row_html(r) for r in rows) + "</table>"
    return f"<details class='lvl'{' open' if is_open else ''}><summary>{summary}</summary>{body}</details>"


def load_bugs(root) -> tuple:
    """(bug records, where they were read from). Two homes exist: the project-level
    qa-factory/bugs/ and, since the bug reporter writes into the story, artifacts/<task>/bugs/
    (TP1-13797 filed BUG-1 there and the page said 0 bugs). Both are read. Two files are
    ONE record only when file name, task and title all match (a copy filed in both places);
    BUG-1 of two tasks, or two BUG-1 with different titles, are different bugs and both are
    kept. A record whose task or title cannot be read is never merged: a project-level file
    names its task only in its own front matter, a per-task one also by its folder."""
    root = Path(root)
    bugs, seen = [], set()   # seen: (file name, task, title) of the project-level records
    sources = {"project": 0, "tasks": {}, "merged": 0}
    home = root / "qa-factory" / "bugs"
    if home.exists():
        for f in sorted_paths(home.glob("*BUG-*.md")):
            fm = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace")) or {}
            if fm:
                bugs.append(fm)
                task, title = str(fm.get("task") or "").strip(), str(fm.get("title") or "").strip()
                if task and title:   # a record whose task or title cannot be read is never merged
                    seen.add((f.name, task, title))
                sources["project"] += 1
    try:
        art = artifact_root(root=root)
        folders = sorted_paths(d for d in art.iterdir() if d.is_dir()) if art.exists() else []
    except Exception:
        folders = []
    for d in folders:
        for f in sorted_paths((d / "bugs").glob("*BUG-*.md")) if (d / "bugs").is_dir() else []:
            fm = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace")) or {}
            if fm:
                fm.setdefault("task", d.name)
                title = str(fm.get("title") or "").strip()
                if title and (f.name, str(fm["task"]).strip(), title) in seen:
                    sources["merged"] += 1
                    continue   # the same record filed in both places
                bugs.append(fm)
                sources["tasks"][d.name] = sources["tasks"].get(d.name, 0) + 1
    return bugs, sources


def bug_sources_note(sources, shown=None) -> str:
    """Which locations the bug records were read from (an empty one is named too)."""
    per_task = ", ".join(f"{t} {n}" for t, n in sorted(sources["tasks"].items())) or "none"
    text = (f"Bugs read from qa-factory/bugs/ ({sources['project']} file(s)) and artifacts/&lt;task&gt;/bugs/ "
            f"({sum(sources['tasks'].values())} file(s): {esc(per_task)}); a copy in both places (same name, task and title) counts once"
            f" ({sources['merged']} merged).")
    if shown is not None:
        text += f" Shown in this view: {shown}."
    return f"<p class='nd'>{text}</p>"


def _bug_step(data, story_root, draft=False) -> str:
    """The step of one bug on the board, through THE one reader (`bug_records.confirmation_of`, HF8-16, AR-13). The board
    reads a record without its path, so `task` here is an id, not a root: the caller passes the story's ROOT as
    `story_root`. No root: a `reproduced_by_factory` that nothing can check reads `unconfirmed` (the error goes down, I5),
    and every other word is the contract's as it was. `draft=True` (the caller holds a DRAFT): a draft with no word is `unconfirmed`."""
    import bug_records as BR
    if story_root is None:
        if draft and not str((data or {}).get("confirmation") or "").strip():
            return "unconfirmed"
        word = C.bug_confirmation(data)
        return "unconfirmed" if word == BR.REPRODUCED else word
    return BR.confirmation_of(story_root, data, draft=draft)[0]


def story_bug_rows(bugs, drafts, story_cases, task=None, story_root=None) -> list:
    """The bug records this story produced: filed records first, then drafts nothing filed.

    A record read from artifacts/<task>/bugs/ carries its `task` (load_bugs): it belongs to that
    story whatever `found_by` names — the bug reporter writes a role there, not a case id — and
    to no other. A record with no task is joined through its cases, as before.

    `story_root` (HF8-16): the story's folder, for the check of a `reproduced_by_factory` word (`_bug_step`)."""
    import bug_records as BR   # the one reader of a draft's cases (t-2187, AR-13)
    out, filed = [], set()
    for b in bugs or []:
        cases = C.case_ids(b.get("found_by")) or C.case_ids(b.get("case"))
        if task and b.get("task"):
            if str(b["task"]) != task:
                continue
        elif story_cases and not (set(cases) & story_cases):
            continue
        filed.update(cases)
        out.append({"id": str(b.get("id") or "?"), "title": str(b.get("title") or ""),
                    "severity": str(b.get("severity") or "not recorded"),
                    "cases": ", ".join(cases) or "—",
                    "confirmation": _bug_step(b, story_root),
                    "requirement": str(b.get("violates") or "").replace("requirement:", ""),
                    "where": str(b.get("where") or b.get("area") or "—")})
    for d in drafts or []:
        cases = C.case_ids(" ".join(BR.draft_cases(d)))   # `case`, `cases` and every manifestation's case (5.18)
        if (story_cases and not (set(cases) & story_cases)) or set(cases) <= filed:
            continue
        out.append({"id": str(d.get("draft_id") or d.get("id") or "draft"),
                    "title": str(d.get("title") or ""), "severity": "draft — not filed",
                    "cases": ", ".join(cases) or "—", "confirmation": _bug_step(d, story_root, draft=True),
                    "requirement": "", "where": "work/bug-drafts"})
    return out


def ready_chip(ledger) -> tuple:
    """`(text, css class)` of the delivery verdict on a story's card (t-305 N8, pure): the three words with their own
    class (`yes` ok, `after_checks` amber, `no` red), `not recorded` (grey) for a story whose ledger holds neither the word
    nor the bool, and `unknown (<what it says>)` in the warning class for a word that disagrees with its bool or is not
    one - never one word painted as another (FR-41). Read through `delivery_verdict.word_of`, so the string "no" is never
    read as ready."""
    import delivery_verdict as DV
    if not isinstance(ledger, dict) or (ledger.get("delivery_ready") is None and ledger.get("delivery_verdict") is None):
        return "not recorded", "nd"
    word = DV.word_of(ledger)
    if word in DV.WORDS:
        return word, {"yes": "ok", "after_checks": "skip", "no": "warn"}[word]
    said = ledger.get("delivery_verdict") if ledger.get("delivery_verdict") is not None else ledger.get("delivery_ready")
    return f"unknown ({said})", "warn"


def awaiting_label(pipeline, now=None) -> str:
    """The label of a story held for code on its card (t-2181 PC-5, t-2277 PC-5): the words of the hold's `cause` (the table
    `awaiting_words` of `references/delivery-verdict-kinds.json`, read through `check_delivery.awaiting_words` - one place for the
    words, AR-13) and its age in whole days since `awaiting.since`, e.g. `waiting for a fix, 3 days`. `""` for a story that is not
    held. The age is printed only when `since` parses as an ISO date (a day count nobody can read is not invented, FR-41). `now`
    is a `datetime` (tests); default the clock."""
    import check_delivery as CD
    import contract as C
    from datetime import datetime
    hold = C.awaiting(pipeline if isinstance(pipeline, dict) else {})
    if hold["state"] == "none":
        return ""
    label = CD.awaiting_words(hold)["label"]
    try:
        since = datetime.fromisoformat(str(hold.get("since") or "")[:19])
        days = max(0, ((now or datetime.now()) - since).days)
        return f"{label}, {days} day" + ("" if days == 1 else "s")
    except ValueError:
        return label


def _left_count(ledger) -> int:
    """How many checks the ledger leaves with the person: the typed `left_items` that count, never a recount."""
    import delivery_verdict as DV
    return DV.count_items((ledger or {}).get("left_items") or [])


def bug_confirmation_split(rows) -> str:
    """"1 confirmed · 3 unconfirmed" for the story's head line.

    A board that says "bugs: 4" is the board TP1-15045 had: two of those four were the
    tests' own defects, nobody had reproduced them, and the number was read as a yield."""
    unconfirmed = sum(1 for r in rows or []
                      if str(r.get("confirmation") or "") == "unconfirmed")
    reproduced = sum(1 for r in rows or [] if str(r.get("confirmation") or "") == "reproduced_by_factory")
    confirmed = len(rows or []) - unconfirmed - reproduced
    parts = ([f"{confirmed} confirmed"] if confirmed else []) + \
            ([f"{reproduced} reproduced by the factory"] if reproduced else []) + \
            ([f"{unconfirmed} unconfirmed"] if unconfirmed else [])
    return " &middot; ".join(parts) or "0"


def pyramid_rows(agg: dict) -> list:
    """The tiers, top-down: the human lanes first, then the code levels from the tip of the
    pyramid to its base. A tier with nothing in it is left out rather than drawn empty."""
    rows = [("Human checks", agg.get("MH")), ("Functional testing (agent)", agg.get("MA"))]
    rows += [(LEVEL_LABELS[name], agg.get(name)) for name in reversed(list(LEVEL_LABELS))]
    rows.append((LEVEL_NONE, agg.get(LEVEL_NONE)))
    out = [(label, counts) for label, counts in rows if counts and any(counts)]
    return out or [("Human checks", [0, 0, 0])]


def left_with_person(task: dict, proj: dict, env_rows: list, titles: dict) -> list:
    """What the story still wants from a person, in that person's words. The traceability
    appendix is the canon once it exists; until it does the same facts are read from the
    manifest's unresolved rows, the planned manual checks and the undecided stand blocks."""
    trace = (task.get("traceability") or {}).get("rows")
    if isinstance(trace, list) and trace:
        return [f"{row.get('case')}: {row.get('what') or row.get('basis') or ''}".strip(": ")
                for row in trace if isinstance(row, dict)
                and row.get("result") in ("wait", "blocked", "not run")][:12]
    out = []
    for u in proj.get("handed") or []:
        case = str(u.get("case") or "")
        out.append(f"{case}: {str(u.get('remedy') or u.get('detail') or 'run it where the access is')[:110]}")
    for m in proj.get("manual") or []:
        out.append(f"{m['case']}: check by hand — {m['title'][:90]}")
    if env_rows:
        out.append(", ".join(sorted({r["case"] for r in env_rows})) + ": a decision on the stand")
    for u in proj.get("design") or []:
        out.append(f"{u.get('case')}: accept as {'unreachable' if str(u.get('reason','')).startswith('impossible') else 'deferred'}")
    return out


def story_bugs_table(rows) -> str:
    # `Confirmed` is its own column, never a footnote: a reader counts the rows, and an
    # unconfirmed row is a draft nobody has reproduced (TP1-15045).
    # the step between the two (HF8-16): the factory saw it fail again, no person has confirmed it - amber (`skip`), never the
    # green of a bug a person stood behind
    cls = {"unconfirmed": "warn", "reproduced_by_factory": "skip"}
    body = "".join(f"<tr><td>{esc(r['id'])}</td><td>{esc(r['title'])}</td>"
                   f"<td class='skip'>{esc(r['severity'])}</td>"
                   f"<td class='{cls.get(str(r.get('confirmation') or ''), 'ok')}'>"
                   f"{esc('reproduced by the factory' if str(r.get('confirmation') or '') == 'reproduced_by_factory' else str(r.get('confirmation') or 'confirmed_by_person').replace('_', ' '))}</td>"
                   f"<td>{esc(r['cases'])}{(' · ' + esc(r['requirement'])) if r['requirement'] else ''}</td>"
                   f"<td>{esc(r['where'])}</td></tr>" for r in rows)
    return ("<table><tr><th>ID</th><th>Title</th><th>Severity</th><th>Confirmed</th>"
            "<th>Cases · R</th><th>Where</th></tr>" + body + "</table>")


def test_runs_line(task) -> str:
    """The story's test-run count, in the retro's own words (SC2-37, AR-19): `retro_numbers.test_run_sentence` over
    `retro_numbers.test_run_counts`, the one reader. "" when the task row names no folder."""
    root = task.get("artifact_path") if isinstance(task, dict) else None
    if not root:
        return ""
    from retro_numbers import test_run_counts, test_run_sentence   # lazy, as the file's other retro_numbers reads
    return test_run_sentence(test_run_counts(Path(root)))


def tab_automation(_board, taskruns, cases, ob_counts=None, archived_hidden=0, ob_list=None,
                   testing_html="", obligations_html="", bugs=None):
    # Open task obligations (state/obligations.md) — the first section of the "Testing" tab:
    # task obligations live here, not in the shared banner above the tabs (only signals stay there).
    out = [obligations_html] if obligations_html else []
    delivery_html = delivery_summary_html(taskruns)
    if delivery_html:
        out.append(delivery_html)
    lifecycle_rows = []
    for task in taskruns:
        state = task.get("lifecycle") or {}
        if not state:
            continue
        active = [d for d in state.get("dispatches", {}).values() if d.get("status") == "running"]
        stopped = [d for d in state.get("dispatches", {}).values() if d.get("status") in {"paused", "blocked", "incomplete"}]
        current = (active or stopped or [{}])[-1]
        next_action = state.get("next_action") or {}
        gaps = [d.get("reason") for d in state.get("dispatches", {}).values() if d.get("unresolved") or d.get("status") in {"blocked", "incomplete"}]
        if current.get("no_progress_warning"):
            gaps.append("Repeated handoff without new evidence: diagnose the loop; discovery remains allowed")
        if current.get("budget_warnings"):
            gaps.append("Discovery advisory: " + ", ".join(current["budget_warnings"]))
        for source in state.get("source_gaps", []):
            gaps.append("Source " + str(source.get("ref")) + ": " + str(source.get("status")) +
                        " (" + str(source.get("reason") or source.get("relevance") or "needs inspection") + ")")
        if state.get("source_completeness") and not state["source_completeness"].get("complete"):
            gaps.append("Source inspection incomplete; see source inventory")
        if state.get("source_integrity") and not state["source_integrity"].get("valid"):
            gaps.append("Source files changed or missing; refresh affected evidence")
        lifecycle_rows.append("<tr><td>" + esc(task["task"]) + "</td><td>" + esc(state.get("revision", "unknown"))
                              + "</td><td>" + esc(current.get("stage", "—")) + "</td><td>"
                              + esc(current.get("status", "awaiting next action")) + "</td><td>"
                              + esc(current.get("id", "—")) + "</td><td>" + esc(next_action.get("action", "unknown"))
                              + "</td><td>" + esc("; ".join(str(g) for g in gaps if g) or "—") + "</td></tr>")
    if lifecycle_rows:
        out.append("<section><h2>Task lifecycle</h2><table><tr><th>task</th><th>revision</th><th>stage</th><th>status</th><th>dispatch</th><th>next action</th><th>gaps</th></tr>"
                   + "".join(lifecycle_rows) + "</table></section>")
    # "Orchestrator continuation" (lease owner, generation, window model requests) was
    # removed after the 15045 reading: it answered a question about the factory's internals
    # that no reader of this board ever asks, and the same next action is in "Task lifecycle".
    root_rows = []
    for task in taskruns:
        for group in (task.get('delivery_summary') or {}).get('root_causes', []):
            details = ''.join('<li>' + esc(str(r.get('code'))) + ': ' + esc(str(r.get('detail'))) + '</li>'
                              for r in group.get('details', []))
            first = (group.get('details') or [{}])[0]
            label = str(first.get('code') or 'delivery finding') + (
                ' · ' + str(first.get('entity')) if first.get('entity') else '')
            root_rows.append('<details data-root-id="' + esc(str(group['root_id'])) + '"><summary>'
                             + esc(task['task']) + ': ' + esc(label) + ' · ' + esc(len(group.get('details') or [])) + ' symptom(s)'
                             + '</summary><ul>' + details + '</ul></details>')
    if root_rows:
        out.append('<section><h2>Delivery blockers and related findings</h2>' + ''.join(root_rows) + '</section>')
    # Behaviour coverage, grouped BY THE GAP: on TP1-15045 one gap sentence was printed
    # fourteen times, once per obligation, and the reader had to notice they were one fact.
    gap_groups: dict = {}
    for task in taskruns:
        for ob in task.get("coverage", {}).get("obligations", []):
            gap = "verified" if ob["verified"] else (str(ob["gap"]).strip() or "gap not named")
            gap_groups.setdefault(gap, []).append((task["task"], ob["obligation_id"]))
    if gap_groups:
        gap_rows = "".join(
            f"<tr><td>{esc(gap)}</td><td>{len(items)} — {esc(', '.join(o for _t, o in items[:3]))}"
            + (f" … {esc(items[-1][1])}" if len(items) > 3 else "") + "</td>"
            f"<td>{esc(', '.join(sorted({t2 for t2, _o in items})))}</td></tr>"
            for gap, items in sorted(gap_groups.items(), key=lambda kv: -len(kv[1])))
        out.append("<section><h2>Behavior coverage — by gap</h2>"
                   "<table><tr><th>gap</th><th>obligations</th><th>task</th></tr>"
                   + gap_rows + "</table></section>")
    manual_rows, retire_rows = [], []
    import grammar as phase_words   # the one table of the manual-evidence phase words (the ledger prints the same)
    for task in taskruns:
        task_root = Path(task.get("artifact_path") or ".").resolve()
        for row in task.get("manual_evidence", {}).get("rows", []):
            links = []
            for ref in row.get("evidence_refs", []):
                path = (task_root / ref.get("path", "")).resolve()
                if path.is_file() and path.is_relative_to(task_root / "evidence"):
                    links.append('<a href="' + esc(path.as_uri()) + '">' + esc(phase_words.manual_phase_word(ref.get("phase"))) + '</a>')
            manual_rows.append("<tr><td>" + esc(task["task"]) + "</td><td>" + esc(row.get("case"))
                               + "</td><td>" + esc(row.get("result")) + "</td><td>" + " · ".join(links) + "</td></tr>")
        plan = task.get("structured_plan") or {}
        for action in plan.get("lifecycle_actions", []) if isinstance(plan, dict) else []:
            retire_rows.append("<tr>" + "".join("<td>" + esc(value) + "</td>" for value in (
                task["task"], action.get("action_id"), action.get("kind"), action.get("reason"))) + "</tr>")
    if manual_rows:
        out.append("<section><h2>Manual evidence</h2><table><tr><th>task</th><th>case</th><th>outcome</th><th>proof</th></tr>" + "".join(manual_rows) + "</table></section>")
    if retire_rows:
        out.append("<section><h2>Case lifecycle proposals</h2><table><tr><th>task</th><th>action</th><th>kind</th><th>reason</th></tr>" + "".join(retire_rows) + "</table></section>")
    # "Execution jobs" was removed: a job row states that the runner was asked to run
    # something, never what it proved, and every outcome it could carry is already a row of
    # the story's own tables.
    environment_rows = []
    for task in taskruns:
        for job in task.get("environment_jobs") or []:
            if not isinstance(job, dict):
                continue
            steps = job.get("steps") or []
            last_step = steps[-1] if steps and isinstance(steps[-1], dict) else {}
            elapsed = job.get("elapsed_seconds", last_step.get("elapsed_seconds", "unknown"))
            progress = job.get("current_step") or (
                str(len(steps)) + " step(s) recorded" if steps else "not recorded")
            log_refs = [last_step.get(key) for key in ("stdout_log", "stderr_log") if last_step.get(key)]
            environment_rows.append("<tr>" + "".join("<td>" + esc(value) + "</td>" for value in (
                task["task"], job.get("job_id", "unknown"), job.get("phase", "unknown"),
                job.get("status", "unknown"), progress, elapsed,
                " · ".join(str(ref) for ref in log_refs) or "—")) + "</tr>")
    if environment_rows:
        out.append("<section><h2>Environment preparation jobs</h2><p>This is job progress only; an exit status does not establish environment, test, or product readiness.</p>"
                   "<table><tr><th>task</th><th>job</th><th>phase</th><th>status</th><th>progress</th><th>elapsed seconds</th><th>log reference</th></tr>"
                   + "".join(environment_rows) + "</table></section>")
    stale = [task["task"] for task in taskruns if task.get("projection_stale")]
    if stale:
        out.append("<section class='alert'><h2>Projection stale</h2><p>"
                   + esc(", ".join(stale))
                   + " — facts are durable, but this view needs a code-only rebuild before it can claim current state.</p></section>")
    lifecycle_gaps = [(task["task"], task.get("case_lifecycle_issues") or []) for task in taskruns
                      if task.get("case_lifecycle_issues")]
    if lifecycle_gaps:
        out.append("<section class='alert'><h2>Case-version proof gaps</h2><ul>" + "".join(
            f"<li><b>{esc(task)}</b>: {esc('; '.join(issues))}</li>" for task, issues in lifecycle_gaps)
            + "</ul></section>")
    # "Approved scope awaiting execution" was removed: a story before its first run now
    # renders its own expand with every planned case in it, so the same rows were printed
    # twice, once as a promise and once as a fact.
    # 1. Per story: the instances the story owns, joined once by story_projection and
    #    grouped by the level the records recorded. A level stays collapsed only when all of
    #    it is green; the environment blocks, the rows left with the person and the rows
    #    nobody will run get their own groups so no coverage illusion can hide in a total.
    if taskruns:
        titles_by_task: dict = {}
        manual_by_task: dict = {}
        for c in cases:
            titles_by_task.setdefault(str(c.get("task") or ""), {})[str(c.get("id"))] = str(c.get("title") or c.get("id") or "")
            if c.get("channel") == "manual-human":
                manual_by_task.setdefault(str(c.get("task") or ""), []).append(c)
        agg: dict = {}
        ring = {"pass": 0, "env": 0, "bug": 0, "open": 0}
        not_run = {"handed": 0, "manual": 0, "unreachable": 0, "deferred": 0}
        feat_groups: dict = {}
        for t in taskruns:
            task = t["task"]
            titles = titles_by_task.get(task, {})
            manual_rows = []
            for c in manual_by_task.get(task, []):
                path_c = str(c.get("_path", ""))
                hit = next(((tsk, ripe_i, trg) for _t2, tsk, ripe_i, det, trg in (ob_list or [])
                            if path_c and path_c in det), None)
                manual_rows.append({"case": str(c.get("id")), "title": str(c.get("title") or c.get("id")),
                                    "owner": str(c.get("owner") or ""), "trigger": (hit[2] if hit else "")})
            proj = story_projection(t, titles, _LEVEL_GLOBS, bugs or [], manual_rows)
            rows = proj["rows"]
            for r in rows:
                agg.setdefault(r["level"], [0, 0, 0])[STATE_INDEX[r["state"]]] += 1
                ring[r["state"]] += 1
            if manual_rows:
                agg.setdefault("MH", [0, 0, 0])[1] += len(manual_rows)
            not_run["handed"] += len(proj["handed"])
            not_run["manual"] += len(manual_rows)
            not_run["unreachable"] += len(proj["unreachable"])
            not_run["deferred"] += len(proj["deferred"])
            # manual-agent lane: the story's own functional checks, as the run report recorded them
            rep = t["report"]
            ma_rows = []
            for m in rep.get("current_manual_checks", rep.get("manual_checks")) or []:
                res = str(m.get("result", "?"))
                state = "pass" if res in ("pass", "passed") else "bug" if res in ("fail", "failed") else "open"
                ma_rows.append({"case": str(m.get("case") or m.get("case_id") or ""),
                                "title": str(m.get("check") or ""), "node": str(m.get("check") or ""),
                                "level": "manual-agent", "status": res, "state": state, "verdict": "",
                                "bugs": [], "basis": str(m.get("result_note") or m.get("evidence_ref") or "")[:160]})
            for m_rd in ma_rows:
                agg.setdefault("MA", [0, 0, 0])[STATE_INDEX[m_rd["state"]]] += 1
                ring[m_rd["state"]] += 1

            runs_txt = test_runs_line(t)
            # --- the story's own blocks ---
            executed = [r for r in rows if r["state"] != "env"]
            env_rows = [r for r in rows if r["state"] == "env"]
            n_fail = sum(1 for r in rows if r["state"] in ("bug", "env"))
            n_triaged = sum(1 for r in rows if r["state"] in ("bug", "env") and r.get("verdict"))
            n_open = sum(1 for r in rows if r["state"] == "open")
            verdict_counts: dict = {}
            for r in rows:
                if r.get("verdict"):
                    verdict_counts[r["verdict"]] = verdict_counts.get(r["verdict"], 0) + 1
            story_cases = {c for r in rows for c in r["cases"]} | {m["case"] for m in manual_rows}
            import bug_records as BR   # the one reader of the draft folder (G1-9)
            drafts = [C.load_json(p) for p in BR.draft_paths(Path(t.get("artifact_path") or "."))]
            bug_rows = story_bug_rows(bugs or [], drafts, story_cases, task,
                                      Path(t["artifact_path"]) if t.get("artifact_path") else None)
            ledger = t.get("ledger") or {}
            # t-305 N8: the verdict word through THE reader, never the truthiness of a field (the string "no" is not ready)
            ready_txt, ready_cls = ready_chip(ledger)
            gate_b = ((t.get("pipeline") or {}).get("gates") or {}).get("B") or {}
            # The person's own words, not the gate's action code: "approve delivery" says
            # nothing about a draft MR opened "for review, gaps tracked as obligations".
            words = " ".join(str(gate_b.get("authorization_source") or "").split())
            mr_txt = (words[:90] + ("…" if len(words) > 90 else "")) if words else \
                str(gate_b.get("action") or "not recorded").replace("_", " ")
            tri_cls = "ok" if n_fail and n_triaged == n_fail else "warn"
            cats = " &middot; ".join(f"{esc(v)}: {n}" for v, n in sorted(verdict_counts.items()))
            head = (f"<b>{esc(task)}</b> &mdash; {len(rows)} instances"
                    + (f" &middot; <span class='{tri_cls}'>failures {n_fail}, triaged {n_triaged}/{n_fail}"
                       + (f" ({cats})" if cats else "") + "</span>" if n_fail else "")
                    + f" &middot; delivery_ready: <span class='{ready_cls}'>{esc(ready_txt)}</span>"
                    + (f" &middot; {_left_count(ledger)} left with you" if ready_txt == "after_checks" else "")
                    + (f" &middot; <span class='warn'>{esc(held)}</span>" if (held := awaiting_label(t.get("pipeline"))) else "")
                    + f" &middot; MR: {esc(mr_txt)} &middot; bugs: {bug_confirmation_split(bug_rows)}"
                    + " <span class='chip'>hover a row for the autotest id</span>")

            story_ring = donut([(sum(1 for r in rows if r["state"] == "pass"), "#2dd4a0"),
                                (sum(1 for r in rows if r["state"] in ("env", "open")), "#FDB022"),
                                (sum(1 for r in rows if r["state"] == "bug"), "#F9303C")],
                               str(len(rows)), "instances", size=110, thick=16)
            story_agg: dict = {}
            for r in rows:
                story_agg.setdefault(r["level"], [0, 0, 0])[STATE_INDEX[r["state"]]] += 1
            for m_rd in ma_rows:
                story_agg.setdefault("MA", [0, 0, 0])[STATE_INDEX[m_rd["state"]]] += 1
            if manual_rows:
                story_agg["MH"] = [0, len(manual_rows), 0]
            story_pyr = pyramid_svg(pyramid_rows(story_agg), width=300, bar_h=22, gap=8)
            left = left_with_person(t, proj, env_rows, titles)
            mini = (f"<div class='wcard'><h3>The story's traffic light</h3>{story_ring}</div>"
                    f"<div class='wcard'><h3>The story's pyramid</h3>{story_pyr}</div>"
                    + (f"<div class='wcard'><h3>Left with the person &mdash; {len(left)}</h3><ul class='left'>"
                       + "".join(f"<li>{esc(x)}</li>" for x in left) + "</ul></div>" if left else ""))

            body = f"<div class='wcards mini'>{mini}</div>"
            if runs_txt:
                body += f"<p class='runs'><b>Test runs:</b> {esc(runs_txt)}</p>"
            if bug_rows:
                body += (f"<details class='lvl' open><summary>Bugs of this story &mdash; "
                         f"{bug_confirmation_split(bug_rows)}</summary>"
                         + story_bugs_table(bug_rows) + "</details>")
            for name in list(LEVEL_LABELS) + [LEVEL_NONE]:
                lv_rows = [r for r in executed if r["level"] == name]
                if not lv_rows:
                    continue
                n_ok = sum(1 for r in lv_rows if r["state"] == "pass")
                n_bad = len(lv_rows) - n_ok
                label = LEVEL_LABELS.get(name, name)
                body += level_group_html(
                    f"Level &mdash; {esc(label)} &mdash; {len(lv_rows)}: <span class='ok'>{n_ok} passed</span>"
                    + (f" &middot; <span class='warn'>{n_bad} failed</span>" if n_bad else ""), lv_rows)
            if ma_rows:
                n_ok = sum(1 for r in ma_rows if r["state"] == "pass")
                body += level_group_html(f"Functional testing (agent) &mdash; {len(ma_rows)}: "
                                         f"<span class='ok'>{n_ok} passed</span>", ma_rows)
            if env_rows:
                decided = C.stand_gap_decisions(t.get("pipeline") or {})
                words = "; ".join(str(v) for v in decided.values() if v)[:160]
                body += level_group_html(
                    f"Blocked by the stand &mdash; {len(env_rows)} &middot; <span class='skip'>ENV_ISSUE</span> &middot; "
                    "<span class='warn'>functionality NOT verified</span> &middot; "
                    + (f"recorded: {esc(words)}" if words else "<b>decision not recorded</b>"),
                    env_rows, open_=True)
            person_rows = ""
            for u in proj["handed"]:
                cid = str(u.get("case") or "")
                part = str(u.get("partition") or "")
                person_rows += person_row_html(
                    cid, titles.get(cid) or cid,
                    (f"partition {part} — no test written" if part else "no test written"),
                    (t.get("case_levels") or {}).get(cid) or "—",
                    "handed at S5" + (f" · {part}" if part else ""),
                    str(u.get("remedy") or u.get("detail") or "")[:200])
            for m in manual_rows:
                what = m["trigger"] or (f"owner: {m['owner']}" if m["owner"] else NO_OWNER)
                person_rows += person_row_html(m["case"], m["title"], "manual check — not automated",
                                               "manual-human", "planned manual at gate A", what)
            n_person = len(proj["handed"]) + len(manual_rows)
            if person_rows:
                body += (f"<details class='lvl' open><summary>With the person &mdash; {n_person}: "
                         f"<span style='color:#8fb5ff'>{n_person} wait</span> &middot; "
                         f"{len(proj['handed'])} handed tests &middot; {len(manual_rows)} planned manual "
                         "&middot; the factory is not waiting for the result</summary>"
                         f"<table>{PERSON_TH}{person_rows}</table></details>")
            design_rows = ""
            for u in proj["design"]:
                cid = str(u.get("case") or "")
                reason = str(u.get("reason") or "")
                word = "unreachable" if reason.startswith("impossible") else "deferred"
                design_rows += (f"<tr data-case-id='{esc(cid)}' data-result='{word}'>"
                                f"<td style='white-space:nowrap'>{esc(cid)}</td>"
                                f"<td>{esc(titles.get(cid) or cid)}</td>"
                                f"<td class='lv'>{esc((t.get('case_levels') or {}).get(cid) or '—')}</td>"
                                f"<td>{pill(word, 'none')}</td><td>—</td>"
                                f"<td>{esc(str(u.get('detail') or '')[:200])}</td></tr>")
            if design_rows:
                body += (f"<details class='lvl' open><summary>Not run by design &mdash; {len(proj['design'])}</summary>"
                         f"<table>{INSTANCE_TH}{design_rows}</table></details>")

            attn = bool(n_fail or n_open or person_rows)
            gkey = (t.get("feature") or "", bool(t.get("archived")))
            grp = feat_groups.setdefault(gkey, {"tasks": [], "attn": False})
            grp["tasks"].append(f"<details class='taskd'{' open' if attn else ''}>"
                                f"<summary>{head}</summary>{body}</details>")
            grp["attn"] = grp["attn"] or attn

        grouped = ""
        for gkey in sorted(feat_groups, key=lambda k: (k[1], k[0] or "￿")):
            grp = feat_groups[gkey]
            feat, arch = gkey
            fname = f"Feature {feat}" if feat else "No feature"
            badge = " <span class='skip'>[ARCHIVE]</span>" if arch else ""
            grouped += (f"<details class='feat'{' open' if grp['attn'] else ''}><summary><b>{esc(fname)}</b>{badge}"
                        f" &mdash; stories: {len(grp['tasks'])}</summary>" + "".join(grp["tasks"]) + "</details>")
        blocks = grouped
        if archived_hidden:
            blocks += (f"<p class='nd'>Tasks hidden in the archive: {archived_hidden} — raise the old picture "
                       "(an incident review on an old feature): factory_dashboard.py --include-archive</p>")
        total = ring["pass"] + ring["env"] + ring["bug"] + ring["open"]
        ring_svg = donut([(ring["pass"], "#2dd4a0"), (ring["env"] + ring["open"], "#FDB022"),
                          (ring["bug"], "#F9303C")], str(total), "instances")
        leg = (f"<div class='wleg'><span class='ok'>&#9679; {ring['pass']} green</span> &middot; "
               f"<span class='skip'>&#9679; {ring['env'] + ring['open']} yellow "
               f"({ring['env']} stand, {ring['open']} without a result)</span> &middot; "
               f"<span class='warn'>&#9679; {ring['bug']} red (bugs)</span><br>executed instances only; not run: "
               f"{not_run['handed']} handed &middot; {not_run['manual']} manual &middot; "
               f"{not_run['unreachable']} unreachable &middot; {not_run['deferred']} deferred</div>")
        pyr = pyramid_svg(pyramid_rows(agg))
        w3 = ""
        if ob_counts:
            rows3 = sorted(((t2, v[0], v[1]) for t2, v in ob_counts.items()), key=lambda x: -(x[1] + x[2]))
            w3 = (f"<div class='wcard'><h3>Remaining checks</h3>{bars_svg(rows3)}"
                  "<div class='wleg'><span style='color:#2297F6'>&#9679; Waiting for condition</span> &middot; "
                  "<span class='skip'>&#9679; Ready to perform</span></div></div>")
        operational_html = "".join(out)
        out = []
        out.append("<section><h2>The picture at a glance</h2><div class='wcards'>"
                   f"<div class='wcard'><h3>Test traffic light</h3>{ring_svg}{leg}</div>"
                   f"<div class='wcard'><h3>Test pyramid</h3>{pyr}"
                   "<div class='wleg nd'>tier width — how many tests the level holds; colors — their state</div></div>"
                   + w3 + "</div></section>")
        if testing_html:
            out.append(testing_html)
        out.append("<section><h2>Tests by task (pyramid)</h2>"
                   "<p class='nd'>A level stays collapsed only when everything inside is green. Each row shows the "
                   "case as a person reads it; the autotest id appears on hover. Triage names the verdict on each "
                   "red row. Sources: run report, automation manifest, triage, case registry, bug files.</p>"
                   + blocks + "</section>")
        if operational_html:
            out.append("<details class='formulas'><summary>Delivery, jobs, obligations and lifecycle evidence</summary>" + operational_html + "</details>")
    if not taskruns and testing_html:
        out.append(testing_html)
    return "".join(out)


def estimate_prices(records, answers) -> tuple:
    """(cost_lookup, floor_tasks, notes, ranges) of the estimate precedents, ALL from the price
    answers: a task's figure is its price, never the metric projection's own sum. `ranges` holds the
    tasks whose two records differ ({task: (low, high)}): they have no single figure, so they stay out
    of the $-band widgets and their cell prints the range. A task whose usage or price is incomplete is a
    floor. A task with no record says so, never $0.00. `notes` are the answers' own sentences."""
    lookup, floor, notes, ranges = {}, set(), [], {}
    for record in records or []:
        task = record.get("task")
        if not task or task in lookup or task in ranges or task in floor:
            continue
        answer = (answers or {}).get(task)
        if answer is None or answer.get("price_low_usd") is None:
            note = price_note(task, answer or {"finding": ""})
            if note not in notes:
                notes.append(note)
            continue
        low, high, status = answer["price_low_usd"], answer["price_high_usd"], answer.get("status")
        if status == TP.DIFFERS:
            ranges[task] = (low, high)
        else:
            lookup[task] = round(high, 2)
            if status == TP.INCOMPLETE:
                floor.add(task)
        if status != TP.AGREES:
            note = price_note(task, answer)
            if note not in notes:
                notes.append(note)
    return lookup, floor, notes, ranges


def tab_estimates(records, ob_list, cost_lookup, signals, sonnet_lookup=None, floor_tasks=(), floor_notes=(),
                  price_ranges=None):
    """The "Estimates" block — lives on the "Cost" tab (operator's decision 09-02: the separate
    tab is removed, estimates are tracked by cost; the size $-bands are SIZE_COST_BANDS from the
    configured size bands). Widgets and precedents use the same recorded cost;
    the legacy optional lookup argument is ignored and never reprices another model."""
    price_ranges = price_ranges or {}
    out = []
    est_note = (f"The source is {RP.rel_text('estimation-ledger.jsonl')} "
                "(one line = one precedent, written at S9); the formula canon is "
                "suite 4 in references/metrics-contract.md.")
    if not records:
        out.append("<section><h2>Estimates (by cost)</h2><p class='nd'>No precedents yet; the first one "
                   "is written at S9 of the first story. The band will be the size's $-band from the "
                   "Hyperfactory tokenomics, the dot the recorded cost.</p></section>")
        out.append(formulas_block("estimates", note=est_note))
        return "".join(out)

    recs_sorted = sorted(records, key=lambda r: str(r.get("ts") or ""), reverse=True)
    if signals:
        out.append("".join(f"<p class='warn'>&#9888; {esc(m)}</p>" for m in signals))

    # --- widget 1: the actual cost's hit inside the size $-band ---
    # `complete_cost` demands complete usage AND complete prices for every request of the
    # task; on TP1-15045 four roles never reported usage, so it was None and both widgets
    # stood empty. The known subtotal is used instead and is marked a floor wherever it shows.
    lookup = cost_lookup
    # A journaled story whose driver record is known is not a floor: the record is lower than the cost
    # files' figure, so "can only be higher" would contradict it. Its figure is shown without the
    # mark, with the record and the gap beside it (the notes), so the notes stand on their own.
    hack_note = ((" Costs marked a floor (" + ", ".join(sorted(floor_tasks)) + ") are known subtotals: "
                  "usage or prices are incomplete, so the real figure can only be higher.") if floor_tasks else ""
                 ) + (
        (" Costs with a range (" + ", ".join(sorted(price_ranges)) + ") have no single figure: the two records of "
         "their price differ, so they are not placed in the $-band widgets.") if price_ranges else ""
        # the price answers' own sentences (what the price stands on, the finding, or "no session has a record")
        ) + "".join(" " + note for note in floor_notes)
    n_in = n_above = n_below = 0
    by_size_costs: dict = defaultdict(list)
    for r in records:
        size = ((r.get("forecast") or {}).get("size_final") or (r.get("forecast") or {}).get("size_initial")
                or (r.get("forecast") or {}).get("size"))
        cost = lookup.get(r.get("task"))
        if size not in SIZE_COST_BANDS or cost is None:
            continue
        by_size_costs[size].append(cost)
        lo, hi = SIZE_COST_BANDS[size]
        if cost > hi:
            n_above += 1
        elif cost < lo:
            n_below += 1
        else:
            n_in += 1
    total_d = n_in + n_above + n_below
    pct = f"{round(100 * n_in / total_d)}%" if total_d else "—"
    donut1 = donut([(n_in, "#2dd4a0"), (n_above, "#F9303C"), (n_below, "#FDB022")],
                   pct, f"{n_in} of {total_d} tasks", size=140, thick=20)
    leg1 = ("<div class='wleg'><span class='ok'>&#9679; inside the $-band</span> &middot; "
            "<span class='warn'>&#9679; costlier</span> &middot; <span class='skip'>&#9679; cheaper</span>"
            f"<span class='nd'>{esc(hack_note)}</span></div>")
    donut1_html = donut1 if total_d else "<span class='nd'>no data (no task costs in the cost loop)</span>"
    w1 = f"<div class='wcard'><h3>$-band hit rate</h3>{donut1_html}{leg1 if total_d else ''}</div>"

    # --- widget 2: $-band vs fact (a dumbbell by cost) ---
    drows = [(size, SIZE_COST_BANDS[size][0], SIZE_COST_BANDS[size][1], round(_median(by_size_costs[size]), 1))
             for size in SIZE_ORDER if by_size_costs.get(size)]
    dumbbell_max = max([SIZE_COST_BANDS[s][1] for s, _lo, _hi, _f in drows] + [f for _s, _lo, _hi, f in drows] + [COST_SCALE_MAX])
    # the dumbbell is a wide card (flex 2): the sizes land as XS…XL rows and the width must fit
    # all five; the separate "obligations at closing" widget was removed by the operator's
    # decision 09-02 — the tails are visible as a column in the precedents table and as the
    # catalog's carry-over metric.
    w2 = (f"<div class='wcard' style='flex:2 1 0'><h3>$-band vs fact (median)</h3>"
          f"{dumbbell_svg(drows, width=640, scale_max=dumbbell_max)}"
          "<div class='wleg nd'>the band is the size's $-band (the Hyperfactory tokenomics, captured 09-02); "
          f"the dot is the median cost of that size's tasks from the cost loop.{esc(hack_note)}</div></div>")

    out.append(f"<section><h2>Estimates at a glance</h2><div class='wcards'>{w1}{w2}</div></section>")

    # --- precedents table ---
    prows = ""
    for r in recs_sorted:
        task = str(r.get("task") or "?")
        date_short = str(r.get("ts") or "")[:10] or "—"
        _, _, tail_n = task_tail_flags(task, ob_list)
        cost_actual = cost_lookup.get(task)
        forecast = r.get("forecast") or {}
        size = forecast.get("size_final") or forecast.get("size_initial") or forecast.get("size")
        band = SIZE_COST_BANDS.get(size)
        cost_tier = f"${band[0]}–{band[1]}" if band else str(forecast.get("cost_tier") or "—")
        fact = ((fmt_usd(cost_actual) + (" (floor)" if task in floor_tasks else "")) if cost_actual is not None
                else pair_text(*price_ranges[task]) if task in price_ranges else "—")
        days = (r.get("actual") or {}).get("calendar_days")
        reest = str(forecast.get("size_reason") or r.get("re_estimation")
                    or (r.get("delta") or {}).get("size_change") or "none recorded")
        prows += ("<tr>"
                  f"<td>{esc(task)}</td><td>{esc(date_short)}</td>"
                  f"<td>{size_arrow(r)}{size_unit_mark(forecast)}</td><td>{scenario_cell(r)}</td>"
                  f"<td>{esc(cost_tier)} → {esc(fact)}</td>"
                  f"<td>{esc(days) if days is not None else '—'}</td>"
                  f"<td>{esc(reest)}</td>"
                  f"<td>{drivers_cell(r)}</td>"
                  f"<td>{tail_n or ''}</td></tr>")
    out.append("<section><h2>Precedents</h2>"
               "<table class='tight1 est-tight'><tr><th>task</th><th>date</th><th>size forecast→fact</th>"
               "<th>scenarios range→fact</th><th>cost forecast→fact</th><th>days</th><th>re-estimation</th>"
               "<th>drivers</th><th>obligations</th></tr>"
               f"{prows}</table></section>")

    # --- revision matrix ---
    matrix = revision_matrix([r for r in records if r.get('completed')])
    if matrix:
        mrows = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{n}</td></tr>"
                        for (a, b), n in sorted(matrix.items(), key=lambda kv: -kv[1]))
        out.append(f"<section><h2>Revision matrix</h2><table><tr><th>from</th><th>to</th><th>count</th></tr>{mrows}</table></section>")
    else:
        out.append("<section><h2>Revision matrix</h2><p class='nd'>There were no revisions.</p></section>")

    # --- Pareto of divergence causes ---
    dcounts = driver_counts([r for r in records if r.get('completed')])
    if dcounts:
        # A table instead of SVG bars: the full driver text, capitalized, wraps inside the
        # cell — SVG labels clipped on long phrasings (operator decision 2026-09-02).
        top7 = sorted(dcounts.items(), key=lambda kv: -kv[1])[:7]
        maxn = top7[0][1] or 1
        prows = "".join(f"<tr><td>{esc(label[:1].upper() + label[1:])}</td><td>{n}</td>"
                        f"<td><div class='bar' style='width:{round(220 * n / maxn)}px'></div></td></tr>"
                        for label, n in top7)
        out.append("<section><h2>Divergence causes (Pareto)</h2>"
                   f"<table><tr><th>driver</th><th>precedents</th><th></th></tr>{prows}</table></section>")
    else:
        out.append("<section><h2>Divergence causes (Pareto)</h2><p class='nd'>Drivers are not filled in in any precedent.</p></section>")

    out.append(formulas_block("estimates", note=est_note))
    return "".join(out)


def _has_factory_activity(s):
    """A session counts as factory work when `has_factory_activity` says so explicitly, or —
    for a file written before that field existed — when its own `by_activity` already shows
    a doctor/onboarding/story type (the identical rule cost_capture.py uses to COMPUTE the
    field it would have written). `by_activity` itself missing entirely means NO signal at
    all is available (not even the old-format shape cost_capture.py has always written) —
    that stays the old conservative default, True, so a story already in flight is never
    refused because an artifact lacks a field. A session whose `by_activity` IS present but
    names no doctor/onboarding/story type at all — session 79152e1f, cwd merely inside the
    project, $149 that used to render as "Unclassified" — is no longer miscounted as factory
    just because `has_factory_activity` itself is absent."""
    v = s.get('has_factory_activity')
    if v is not None:
        return bool(v)
    by_activity = s.get('by_activity')
    if not isinstance(by_activity, dict):
        return True
    return any(isinstance(a, dict) and a.get('type') in ('doctor', 'onboarding', 'story')
               for a in by_activity.values())


def split_project_sessions(sessions, root=None):
    """(this project's sessions, the ones captured here that belong elsewhere).

    A cost file sits in this project's state/cost because the hook ran here; the transcript
    path says which directory the session was actually opened in. On TP1-15045 that
    difference was eight sessions and $2,873.95 of factory development summed into a story
    that cost $258. A session whose host keeps no project folder (Codex) keeps the older
    rule — whether the session recorded any factory activity at all."""
    from cost_capture import project_slug, session_belongs_to, session_project_slug
    own = project_slug(root) if root else ""
    if not any(session_belongs_to(s, own) == "this" for s in sessions):
        # The folder was copied away from the path it was captured at (an incident review on
        # a copy): the deepest transcript directory present IS that path, and everything
        # shorter is one of its parents.
        own = max((session_project_slug(s) for s in sessions), key=len, default="")
    inside, outside = [], []
    for s in sessions:
        place = session_belongs_to(s, own)
        (inside if (place == "this" or (place == "unknown" and _has_factory_activity(s))) else outside).append(s)
    return inside, outside


def session_marks(sessions, cost_cfg, stale=None) -> dict:
    """{session: {"state": live | open | settled | unknown | final, "reason", "final_rule", "open_h"}} of THIS
    render, ONE call per render (`main`), handed on as `marks` (the state of a session is never stored: a stored
    "still being written" would outlive the writing). `sessions` are the project's own (a parent's transcript is not
    read, I-93); `cost_cfg` the `cost` block of the config; `stale` the pass's outcomes (`stale_outcomes`).
    A file that says `complete` is `final` (`final_rule` = its `usage_final.rule`, None when it carries none), with
    no file read. A `provisional` one asks `session_verdict` (the one reader of "has it ended"): `live` and `open`
    are information, `settled` (ended, but this render did not recompute it) and `unknown` are findings. Any other
    value (Codex `partial`, `unsupported`, no value) is `unknown` with its word. `open_h` is the open limit in hours."""
    import cost_capture as CC
    idle_s, open_s = CC.final_limits(cost_cfg)
    open_h = open_s / 3600
    out = {}
    for s in sessions:
        key, value = session_key(s), s.get("usage_completeness")
        if value == "complete":
            final = s.get("usage_final")
            rule = final.get("rule") if isinstance(final, dict) and final.get("rule") in ("settled", "timed_out") else None
            out[key] = {"state": "final", "reason": "usage final", "final_rule": rule, "open_h": open_h}
        elif value == "provisional":
            try:
                state, reason, _rule = CC.session_verdict(s.get("transcript"), idle_s, open_s)
            except Exception as error:  # noqa: BLE001 - a page is never lost to one transcript: it is a finding
                state, reason = "unknown", f"the end of the session could not be told ({type(error).__name__})"
            if state == "settled":
                reason = str((stale or {}).get(key) or "ended; not recomputed in this render")
            out[key] = {"state": state, "reason": reason, "final_rule": None, "open_h": open_h}
        else:
            out[key] = {"state": "unknown", "reason": f"usage {value}", "final_rule": None, "open_h": open_h}
    return out


def _info_sessions(v: dict, marks) -> tuple:
    """`(finding_ids, information_lines)` for the sessions of one "By task" row. Without `marks` every provisional
    session is a finding and nothing is information - today's behaviour byte for byte. With them: a `live` or `open`
    session is information ("still being written", "stopped mid-turn"), a `final` one that ended mid-turn
    (`timed_out`) is information too (the figure is final and says how), everything else provisional - `settled`
    and not recomputed, `unknown`, no mark at all - is a finding (an unknown is never information, FR-41).
    The `agreed` sessions of the price answer leave the count FIRST (t-182), then the marks divide what is left."""
    ids = set(v.get("provisional_sessions") or ())
    answer = v.get("price")
    if isinstance(answer, dict) and answer.get("status") == TP.AGREES:
        ids -= {r.get("session") for r in answer.get("sessions") or []
                if isinstance(r, dict) and r.get("verdict") == TP.V_AGREES}
    if marks is None:
        return ids, []
    state = lambda sid: (marks.get(sid) or {}).get("state")          # noqa: E731
    live = sorted(sid for sid in ids if state(sid) == "live")
    opened = sorted(sid for sid in ids if state(sid) == "open")
    timed = sorted(sid for sid in (v.get("session_ids") or ())
                   if state(sid) == "final" and marks[sid].get("final_rule") == "timed_out")
    hours = next((marks[sid].get("open_h") for sid in opened + timed if marks[sid].get("open_h")), None)
    shown = f"{hours:g}" if isinstance(hours, (int, float)) else "the open limit of"
    lines = []
    if live:
        lines.append(f"{len(live)} session{'s' if len(live) != 1 else ''} still being written")
    if opened:
        lines.append(f"{len(opened)} session{'s' if len(opened) != 1 else ''} stopped mid-turn; final after {shown} h")
    if timed:
        lines.append(f"{len(timed)} session{'s' if len(timed) != 1 else ''} ended mid-turn; usage final after {shown} h")
    return {sid for sid in ids if state(sid) not in ("live", "open")}, lines


def provisional_count(v: dict, marks=None) -> int:
    """How many sessions of a "By task" row still stand on usage the capture marked provisional. With `marks`
    (`session_marks`) only the FINDINGS are counted: a session still being written is information (`_info_sessions`).

    When the price answer says the two records AGREE (`v["price"]`, status `agrees`), a session whose
    records agree is NOT provisional any more: the CLI's own charge is the final figure of the session, so
    a transcripts figure that agrees with it is complete. Reading the capture's marker there said "the two
    records agree; incomplete - 19 sessions provisional" on the recaptured cmp1 beside a retro that said the
    price was complete (t-182): the price function's status is the word on whether a price is complete, and
    the page follows it. The marker still counts for the sessions of that story the records did not compare
    (one record only), and for every other status (differs, not cross-checked, incomplete) and for a row with
    no answer, where it is the only word there is."""
    return len(_info_sessions(v, marks)[0])


def task_completeness(v: dict, marks=None) -> tuple:
    """(text, css class, is_a_factory_finding) for one "By task" row. With `marks`, a session still being written
    (or stopped mid-turn, or ended mid-turn and final) is information, not a finding: the cell says so in the
    `skip` class and the row is no finding. The finding part comes first, information after it ("; ")."""
    roles = sorted(v.get("incomplete_agents") or [])
    provisional = provisional_count(v, marks)
    info = _info_sessions(v, marks)[1]
    if roles or provisional:
        parts = []
        if roles:
            parts.append(f"{len(roles)} role{'s' if len(roles) != 1 else ''} without usage")
        if provisional:
            parts.append(f"{provisional} session{'s' if provisional != 1 else ''} provisional")
        return "incomplete — " + ", ".join(parts) + "".join("; " + line for line in info), "warn", True
    if v.get("unpriced_tokens") and v.get("priced"):
        return "+ unpriced usage" + "".join("; " + line for line in info), "warn", False
    if v.get("ok") is False:
        return "sums do not reconcile" + "".join("; " + line for line in info), "warn", True
    if info:
        # the generic "not reconciled" is only the other face of the sessions that are not finished
        # class `skip` whatever `ok` says: the words are information only, and no "reconciled ✓" stands beside them
        return "; ".join(info), "skip", False
    if v.get("ok") is True:
        return "reconciled ✓", "ok", False
    return "not reconciled — prices incomplete", "warn", False


def cost_findings_from_tasks(by_task: dict, marks=None) -> list:
    """One plain line per task whose cost cannot be completed or reconciled. This is a defect
    of the factory's own capture, so it is named as one — on the Cost tab and in the Factory
    tab's donut — instead of a grey "Unknown" the reader has to interpret."""
    out = []
    for task, v in sorted(by_task.items()):
        _text, _cls, is_finding = task_completeness(v, marks)
        if not is_finding:
            continue
        roles = sorted(v.get("incomplete_agents") or [])
        provisional = provisional_count(v, marks)
        out.append(
            f"Factory finding — cost incomplete for {task}: "
            + (f"usage never arrived from {', '.join(roles)}; " if roles else "")
            # of the sessions that have a cost file: a session the journal names with no file has no usage
            # status to be provisional, and is counted in the price row, not here
            + (f"{provisional} of {v.get('files', v['sessions'])} sessions provisional; " if provisional else "")
            + "the figure is a floor and reconciliation is not possible. Owner: factory (cost capture).")
    return out


def cost_capture_findings(sessions, root=None, task_of=None, prices=None, driver=None, marks=None) -> list:
    """The Factory tab's cost-capture findings, from the same grouping the Cost tab draws (`task_of`
    is the render's one binding, so a story's sessions are one task here as they are there; `prices` the
    render's price answers, so the rows it reads are the ones By task draws; `marks` the render's one
    `session_marks`: the same list of findings on both tabs, FR-10)."""
    inside, _outside = split_project_sessions(sessions, root)
    if not inside:
        return []
    if prices:
        return cost_findings_from_tasks(task_groups(inside, [], prices, task_of or {}, driver or {})["by_task"], marks)
    from dashboard_cost_groups import group as group_cost
    by_task, _days = group_cost(inside, task_of)
    return cost_findings_from_tasks(by_task, marks)


NO_TASK = "(no task)"
_TOKEN_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


# The driver journal's reader lives in driver_journal.py (one reader for the dashboard, the retro
# and the metrics); the names stay importable from here (`D.parse_driver_runs`, `D.root_charged`, `D.WHY_FALLS`,
# `D.WHY_SEVERAL_JOURNALS`, `D.WHY_PER_CALL_ROOT`) because tests reach them through this module. `driver_role`,
# `driver_charged` and `WHY_NO_TOTAL` were re-exported here too with no reader anywhere (B-309 z): they are
# `driver_journal`'s own.
from driver_journal import (parse_driver_runs, root_charged,  # noqa: E402,F401
                            WHY_FALLS, WHY_SEVERAL_JOURNALS, WHY_PER_CALL_ROOT)

import driver_journal as DJ  # noqa: E402  — agent_label, pair_records: the ONE labeller and the pair records
from hooklib import sorted_paths  # noqa: E402

# Who the orchestrator is: the capture's orchestrator stream of a session no journal names, and the
# conductor's sessions of a driver run (owner, 30.09: orchestrator = conductor + code; the driver's
# code spends no model money). A ticket or data-fetching call is the SCOUT's (`agent_label`), never here.
ORCH_ROLES = ("orchestrator", "conductor")


def session_key(s) -> str:
    """One stable identity for a cost file: its session id, else the path it was read from
    (main() stamps `_source_file` on a file that carries no id), else the object itself. An
    enumerate index is NOT an identity: the same file sits at different positions in the lists
    the view splits, and a share keyed by position was applied to the wrong file ($6.00 for $2.50)."""
    return str(s.get("session_id") or s.get("_source_file") or f"anonymous-{id(s)}")


def _tagged_tasks(doc) -> set:
    """The ONE reader of the task names a cost file literally carries: the keys of its `by_task` (a dict, whose
    value is a dict) and the strings of its `tasks` (a list; a string is never split into characters), minus
    "(no task)" and the empty string. Case-sensitive, literal: a tag is a claim of the file, never evidence."""
    if not isinstance(doc, dict):
        return set()
    by_task = doc.get("by_task") if isinstance(doc.get("by_task"), dict) else {}
    tasks = doc.get("tasks") if isinstance(doc.get("tasks"), list) else []
    named = [t for t, v in by_task.items() if isinstance(v, dict)] + tasks
    return {t for t in named if isinstance(t, str) and t and t != NO_TASK}


UNBOUND_IDS_SHOWN = 5


def unbound_sessions(sessions, task, scopes, task_of) -> list:
    """The sorted ids of the sessions of `sessions` (this project's) that TAG `task` in their cost file and that
    nothing binds to it: no journal names them (`task_of`: a session of another task's journal is that task's,
    never unbound) and no row of theirs is in the task's price (`scopes[task]`, claim_scopes). Such a session is
    not in the price (a tag is not evidence of spend, FR-24); its money is counted elsewhere on the page and the
    row of the task names it. Error direction: it may fail to name a tagged session (a file with no session id
    cannot be located, so it is left out); it never names a session a journal binds, nor one the price counts."""
    counted = (scopes or {}).get(task) or {}
    return sorted({doc["session_id"] for doc in sessions
                   if isinstance(doc.get("session_id"), str) and doc["session_id"]
                   and task in _tagged_tasks(doc) and doc["session_id"] not in (task_of or {})
                   and doc["session_id"] not in counted})


def unbound_words(n) -> str:
    """The words every surface of one task uses for its unbound sessions (the cell, the story card): one wording."""
    return f"unbound: {n} session{'s' if n != 1 else ''} (not in this price)"


def unbound_note(task, ids, labels) -> str:
    """The sentence under By task for one task's unbound sessions: what they are, why they are not in the price,
    where their money is counted (the final labels of the rows that hold them), ids capped at UNBOUND_IDS_SHOWN."""
    n = len(ids)
    shown = ", ".join(ids[:UNBOUND_IDS_SHOWN]) + (f", and {n - UNBOUND_IDS_SHOWN} more" if n > UNBOUND_IDS_SHOWN else "")
    return (f"{task}: unbound: {n} session{'s' if n != 1 else ''} tag{'s' if n == 1 else ''} this task in "
            f"{'its' if n == 1 else 'their'} cost file, but no driver journal names "
            f"{'it' if n == 1 else 'them'} and no story activity or chat binding of the task binds "
            f"{'it' if n == 1 else 'them'}, so {'it is' if n == 1 else 'they are'} not in its price; "
            f"{'its' if n == 1 else 'their'} money is counted under {', '.join(labels) or 'other rows of this table'} ({shown}).")


def untimed_words(n) -> str:
    return f"{n} session{'s' if n != 1 else ''} untimed"


def time_cell(v) -> str:
    """The time cell of a By task row. A row with a timed session prints the time and, when some sessions of it
    have none, says how many (never a partial sum as the whole); a row whose sessions are all untimed says
    "unknown"; "—" means no time was read for the row's sessions (a row may hold sessions and still print it:
    the activity path with no `active_s`, an unbound legacy session) and is not named by the total."""
    untimed = len(v.get("untimed_sessions") or ())
    if v["timed"]:
        return fmt_dur(v["active"]) + (f" ({untimed} of {v['sessions']} sessions untimed)" if untimed else "")
    return "unknown" if untimed else "—"


def total_time_cell(rows) -> str:
    """The time of the 'All stories and activities' row: the sum of the timed rows, naming only the sessions
    listed in `untimed_sessions` (FR-41: not a plain partial sum); a row holding sessions that print "—" is
    not named here."""
    untimed = sum(len(v.get("untimed_sessions") or ()) for v in rows)
    total = sum(v["active"] for v in rows if v["timed"])
    if total:
        return fmt_dur(total) + (f" ({untimed_words(untimed)})" if untimed else "")
    return "unknown" if untimed else "—"


def task_binding(driver) -> dict:
    """The ONE session -> task binding of a render, from the driver journal (`parse_driver_runs`):
    a session a journal names belongs whole to that journal's task. `main` computes it once and
    hands it to every section that groups by task; an empty journal is an empty binding, and an
    empty binding changes nothing anywhere (dashboard_cost_groups.group)."""
    return {sid: entry["task"] for sid, entry in (driver or {}).items()
            if isinstance(entry, dict) and isinstance(entry.get("task"), str) and entry["task"]}


def multi_journal_note(sid, n, entry) -> str:
    """One session named by several task journals is one process, counted under ONE task: say which
    (E4), wherever the session is shown."""
    return f"session {sid} is named by {n} task journals" + _multi_journal_tail(entry)


def _multi_journal_tail(entry) -> str:
    """"; counted under T" (+ the no-timestamps reason): what every line about a session of two journals
    ends with, so By task and By agent say the same thing in the same words."""
    entry = entry if isinstance(entry, dict) else {}
    text = f"; counted under {entry['task']}" if entry.get("task") else ""
    if entry.get("no_timestamps"):
        text += " (no timestamps in its rows in any of them, so the first task name in alphabetical order)"
    return text


# ================================================================ the price of a task (t-137 Q5, t-111 P2)
# ONE answer per task: `task_price` is called once per task in main() and every money surface of a
# story reads THAT answer: By task and its check label, the story card, By agent, the estimates
# floor and its note, the spend card, the task view. Nothing here prices a story on its own, and no
# section reads the valuations a cost file carries from capture (main() re-prices every file at read
# time, `reprice_documents`). While the two records differ the price is a RANGE (P18): never one
# figure with a caption.

CENT = Decimal("0.01")
NO_RECORD = "no session of this task has a record"
# Labels group() leaves for work that belongs to no story. Any other label of the part of the ledger no
# price counts is a task name a tag carries and no evidence binds: it is listed apart, never in a price.
FIXED_LABELS = frozenset({"Unclassified", "Doctor", "Onboarding", "Environment-Maintenance", "Collect"})
TAG_ONLY = " - tagged only, not counted in its price"
STATUS_WORDS = {TP.AGREES: "the two records agree", TP.DIFFERS: "the two records differ",
                TP.NOT_CROSS_CHECKED: "not cross-checked", TP.INCOMPLETE: "incomplete"}
SINGLE_SOURCE_WORDS = TP.SINGLE_SOURCE_WORDS   # information, not a finding


def _cents(value) -> int:
    """A figure in whole cents, rounded half up ONCE: two sums are equal when their cents are."""
    return int(Decimal(repr(float(value))).quantize(CENT, rounding=ROUND_HALF_UP) * 100)


def money(value) -> str:
    """$x.xx, rounded half up at display (the rounding `task_price`'s own sentences use)."""
    if value is None:
        return "—"
    return "$" + format(Decimal(repr(float(value))).quantize(CENT, rounding=ROUND_HALF_UP), ",")


def pair_text(low, high, to_the_cent=False) -> str:
    """One figure when the pair is one figure, "from $low to $high" when it is a range. Two ends that
    read the same at the cent are printed to four decimals, so a story's range never reads as a single
    figure; `to_the_cent` (a row of By agent, like the retro's table by agent) prints one figure then, so
    a row whose records differ by a hundredth of a cent does not read as a range of nothing."""
    if low is None or high is None:
        return "—"
    if abs(high - low) < 1e-9 or (to_the_cent and money(low) == money(high)):
        return money(low)
    if money(low) != money(high):
        return f"from {money(low)} to {money(high)}"
    return f"from ${low:,.4f} to ${high:,.4f}"


def status_words(answer) -> str:
    """The price status in plain words. A price at the project's own rates whose records agree says
    where they agree (at the catalogue's list rates, the rates the CLI's charge is at), so "the two
    records agree" never stands beside a figure that is not the one they agree on."""
    status = answer.get("status")
    if status == TP.AGREES and TP.project_rates_applied(answer):
        return "the two records agree at the catalogue's list rates; the price is at the project's own rates"
    if status == TP.NOT_CROSS_CHECKED and answer.get("single_source") is True:
        return SINGLE_SOURCE_WORDS   # absent field = not a single source (a failed answer carries none)
    return STATUS_WORDS.get(status, status)


def answer_text(answer) -> str:
    return pair_text(answer.get("price_low_usd"), answer.get("price_high_usd"))


def price_note(task, answer) -> str:
    """What a story's price stands on, in plain words: the figure or the range, its status, what was
    compared, then the function's own finding. A task with no record says so, never "$0.00"."""
    finding = str(answer.get("finding") or "").strip()
    if answer.get("price_low_usd") is None:
        if answer.get("sessions"):
            # sessions the evidence names exist, and neither record prices any of them: no figure, and why
            return f"{task}: no figure is known; the price is incomplete. " + finding
        rest = finding.replace("No session of this task has a record.", "").strip()
        return f"{task}: {NO_RECORD}." + (" " + rest if rest else "")
    status = answer.get("status")
    figure = answer_text(answer)
    head = (f"{task}: {figure} is what is known; the price is incomplete." if status == TP.INCOMPLETE
            else f"{task}: {figure} ({status_words(answer)}).")
    compared = str(answer.get("compared") or "").strip()
    return " ".join(p for p in (head, f"Compared: {compared}." if compared else "", finding) if p)


def price_notes(answers, only=()) -> list:
    """The notes (unescaped) of every answer that has a price, and of the tasks in `only` that have none."""
    return [price_note(task, answer) for task, answer in sorted((answers or {}).items())
            if answer.get("price_low_usd") is not None or answer.get("sessions") or task in set(only or ())]


def _failed_answer(task, exc) -> dict:
    """An answer for a task whose price could not be computed: no figure, the reason in words (FR-41)."""
    return {"status": TP.INCOMPLETE, "sessions": [], "by_agent": [], "totals": {}, "differ": [], "one_record": [],
            "unknown": [], "in_progress": [], "catalogue_revision": None, "compared": "nothing was compared",
            "rows_without_session": 0, "rate_overrides": [],
            "finding": (f"The price of {task} could not be computed ({type(exc).__name__}): no figure is shown "
                        "for it. This is a defect of the factory's measurement.")}


def _unpriced_stub(doc) -> dict:
    """What stands in for a cost file that could not be re-priced: its identity and nothing priced, so
    every section counts it as "no priced usage" and never reads the money it was captured with."""
    stub = {k: doc[k] for k in ("session_id", "_source_file", "transcript") if isinstance(doc.get(k), str)}
    stub.update(usage_completeness="provisional", usage_status="not priced", pricing_coverage="none",
                by_model={}, by_task={}, priced_subtotal_usd=None, total_cost_usd=None, external_calls=[],
                reprice_failed=True)
    return stub


def reprice_documents(loaded, cost_cfg, catalogue) -> tuple:
    """(sessions, info): every cost file of the root re-priced ONCE at read time by
    `cost_capture.revalue_document`: the catalogue's rates, a project's `rate_overrides` as the price
    base exactly as `task_price` does. Figures captured before the re-pricing were pinned at the
    project's own table; they stay on disk and are never read here. A file that cannot be re-priced
    (`revalue_document` raised) becomes an unpriced stub, never a crash and never its pinned money
    (`info["unreadable"]`); a file with no request ledger has no usage to re-price from, so it is kept
    as captured and counted (`info["no_ledger"]`): the page says both."""
    import cost_capture as CC
    sessions = []
    info = {"revision": (catalogue or {}).get("catalogue_revision"), "unreadable": [], "no_ledger": [],
            "overrides": []}
    for doc in loaded:
        rows = doc.get("requests")
        if not isinstance(rows, list) or not rows:
            info["no_ledger"].append(session_key(doc))
            sessions.append(doc)
            continue
        try:
            sessions.append(CC.revalue_document(doc, cost_cfg, catalogue))
        except Exception:
            info["unreadable"].append(session_key(doc))
            sessions.append(_unpriced_stub(doc))
    return sessions, info


def reprice_note(info) -> str:
    """The one paragraph of the Cost tab that names the catalogue revision and says what was re-priced."""
    if not info:
        return ""
    text = (f"Prices on this tab are the catalogue's (revision {info.get('revision') or 'not reported'}), applied at read "
            "time to the usage stored with each request. Figures captured before this re-pricing were pinned at the "
            "project's own price table: they are re-priced here and never rewritten on disk.")
    if info.get("overrides"):
        text += (" Priced at the project's own rate (the project's own price table): " + ", ".join(info["overrides"]) +
                 ". Outside the stories' rows the transcripts column shows that same figure.")
    if info.get("no_ledger"):
        n = len(info["no_ledger"])
        text += (f" {TP._plural(n, 'cost file holds', 'cost files hold')} no per-request ledger, so there is no usage to "
                 "re-price from: their figures are the ones pinned at capture.")
    if info.get("unreadable"):
        n = len(info["unreadable"])
        text += (f" {TP._plural(n, 'cost file', 'cost files')} could not be re-priced (" + ", ".join(info["unreadable"][:5]) +
                 (", and more" if n > 5 else "") +
                 f") and {'is' if n == 1 else 'are'} counted as having no priced usage.")
    return text


def price_task_ids(sessions, task_of, extra=()) -> set:
    """The tasks a render asks the price function about: the journals' tasks, the tasks story activities
    and chat bindings of the cost files name, and `extra` (the task view's tasks, the estimates'). The
    function itself decides by evidence what belongs to each; a task it finds nothing for has no price."""
    found = {t for t in (task_of or {}).values() if isinstance(t, str) and t}
    for s in sessions:
        activities = s.get("by_activity") if isinstance(s.get("by_activity"), dict) else {}
        for a in activities.values():
            if isinstance(a, dict) and a.get("type") == "story" and isinstance(a.get("task"), str) and a["task"]:
                found.add(a["task"])
        for b in s.get("chat_bindings") if isinstance(s.get("chat_bindings"), list) else []:
            if isinstance(b, dict) and isinstance(b.get("task"), str) and b["task"]:
                found.add(b["task"])
    found |= {t for t in extra if isinstance(t, str) and t}
    found.discard(NO_TASK)
    return found


def price_answers(root, tasks, sessions, driver, spread, catalogue=None, cost_cfg=None) -> dict:
    """{task: the `task_price` answer}: ONE call per task, made once per render (by `main`). `sessions`
    are the cost files already loaded, `driver, spread` the journal's reader result. A task whose price
    cannot be computed gets an answer with no figure and the reason: a page never stops for it."""
    docs = {session_key(s): s for s in sessions if isinstance(s, dict)}
    answers = {}
    for task in sorted(tasks):
        try:
            answers[task] = TP.task_price(root, task, sessions=docs, driver=(driver or {}, spread or {}),
                                          catalogue=catalogue or None, cfg=cost_cfg or {})
        except Exception as exc:
            answers[task] = _failed_answer(task, exc)
    return answers


def price_factors(answers) -> tuple:
    """({session: factor}, on_project_rates) of the render's price answers (`task_price.session_factors`: the
    one place the scaling lives): what puts a session's CLI charge (at the catalogue's list rates) on the rate
    base of the price it belongs to. Only answers priced at the project's own rates have factors; without
    any, the dict is empty and the page is what it was. A story priced at the project's own rates has its price
    on them, and the money that stands beside it on the Factory tab (the orchestrator's share "$3.07 of $17.42"
    under "$26.14", the banner, a marathon dispatch's cost) must be on the same base or the page has two rates
    for one story (t-182). A session with no factor keeps the CLI's own figure."""
    factors, on_project = {}, False
    for answer in (answers or {}).values():
        if TP.project_rates_applied(answer):
            on_project = True
            factors.update({sid: float(f) for sid, f in TP.session_factors(answer)[0].items()})
    return factors, on_project


# The part of each cost file a price counts. A session the journal names is the price's WHOLE; any
# other session contributes the request rows its story activity (or chat binding) binds to the task.
# `task_price` does not hand those rows out, so they are asked of the function's own rule.
def claim_scopes(answers, docs, driver) -> dict:
    """{task: {session: None (the whole session) | [request indexes]}} of the sessions each price counts."""
    scopes = {}
    for task, answer in (answers or {}).items():
        per = {}
        for row in answer.get("sessions") or []:
            sid = row.get("session")
            entry = (driver or {}).get(sid)
            if isinstance(entry, dict) and entry.get("task") == task:
                per[sid] = None
                continue
            doc = docs.get(sid)
            if doc is None:
                continue
            act, chat, _contested = TP._own_requests(doc, task)
            if act | chat:
                per[sid] = sorted(act | chat)
        scopes[task] = per
    return scopes


def _keyed_rows(doc, indexes=None) -> dict:
    """A copy of a cost file holding only the request rows at `indexes` (None: all of them), every row
    carrying a request_key so that two parts of one session never collide when they are grouped."""
    rows = doc.get("requests") if isinstance(doc.get("requests"), list) else []
    sid = session_key(doc)
    picked = []
    for i in (range(len(rows)) if indexes is None else indexes):
        row = rows[i]
        if isinstance(row, dict) and not row.get("request_key"):
            row = dict(row, request_key=f"{sid}#{i}")
        picked.append(row)
    return dict(doc, requests=picked)


def unclaimed_sessions(sessions, scopes) -> list:
    """The cost files of `sessions` with every request row some price counts taken out (a session a
    price counts whole is gone): the part of the ledger no story's price holds, which keeps its own
    labels. Nothing is counted twice and nothing is dropped."""
    claimed = {}
    for per in scopes.values():
        for sid, idx in per.items():
            if idx is None:
                claimed[sid] = None
            elif sid not in claimed:
                claimed[sid] = set(idx)
            elif claimed[sid] is not None:
                claimed[sid] |= set(idx)
    rest = []
    for doc in sessions:
        sid = session_key(doc)
        if sid not in claimed:
            rest.append(doc)
        elif claimed[sid] is not None:
            rows = doc.get("requests") if isinstance(doc.get("requests"), list) else []
            keep = [i for i in range(len(rows)) if i not in claimed[sid]]
            if keep:
                rest.append(_keyed_rows(doc, keep))
    return rest


def _blank_task_row() -> dict:
    from dashboard_cost_groups import blank_row
    return blank_row(ok=None)


def task_groups(sessions, shared, answers, task_of, driver, stray_apart=True) -> dict:
    """The By task rows and everything the Cost tab needs to partition a ledger, from ONE place.

    With no price answers (`answers` empty: a caller that never asked) the rows are
    `dashboard_cost_groups.group`'s, as before. With answers, each task that has a price is one row
    drawn from the requests its price counts (sessions, tokens, time) with the price as its money;
    the rest of the ledger keeps group()'s labels, and a label that is a task name nobody's evidence
    binds becomes "<task> - tagged only, not counted in its price". Returns by_task, days (by request
    day, from the whole ledger), scopes (claim_scopes), rest (unclaimed_sessions) and docs."""
    from dashboard_cost_groups import group as group_cost, NOT_LAUNCHED, attach_rowless_gaps
    docs = {session_key(s): s for s in list(sessions) + list(shared or [])}
    # the sessions a journal names are timed whole (their machine time, once), never by activity time
    journal_sessions = set(task_of) if isinstance(task_of, dict) else set()
    if not answers:
        by_task, days = group_cost(sessions, task_of, stray_apart=stray_apart, whole_time=journal_sessions)
        return {"by_task": by_task, "days": days, "scopes": {}, "rest": list(sessions), "docs": docs}
    scopes = claim_scopes(answers, docs, driver)
    rest = unclaimed_sessions(sessions, scopes)
    # The parts below split one document's rows between rows of a price and the rest, so a role's gap that
    # has no rows is not attached by the parts (`rowless_gaps=False`): it is attached ONCE per document,
    # after all of them, to the part that holds the rows of the activity it ran in (`held_*`).
    held_rest, held_mine, whole_docs = {}, {}, {}
    rest_tasks, _ = group_cost(rest, task_of, rowless_gaps=False, held=held_rest, whole_time=journal_sessions)
    _unused, days = group_cost(sessions, task_of)
    by_task = {}

    def rest_key(label):
        return label if label in FIXED_LABELS or label.endswith(NOT_LAUNCHED) else label + TAG_ONLY
    for label, value in rest_tasks.items():
        by_task[rest_key(label)] = value
    for task, answer in answers.items():
        priced = answer.get("price_low_usd") is not None
        if not priced and not answer.get("sessions"):
            continue       # nothing of this task is known: no row (the notes say so), never a $0.00 row
        counted = [docs[sid] if idx is None else _keyed_rows(docs[sid], idx)
                   for sid, idx in (scopes.get(task) or {}).items() if sid in docs]
        # only the sessions the price counts WHOLE (a journal names them) are timed whole; an orchestrator session
        # counted in part keeps the activity time of its part
        whole = {sid for sid, idx in (scopes.get(task) or {}).items() if idx is None}
        mine, _d = group_cost(counted, {session_key(d): task for d in counted}, rowless_gaps=False,
                              held=held_mine, whole_time=whole) if counted else ({}, {})
        whole_docs.update({d.get("session_id"): docs[session_key(d)] for d in counted if d.get("session_id")})
        row = dict(mine.get(task) or _blank_task_row())
        # a journal session with no cost file has no time: it is untimed, named (FR-41)
        row["untimed_sessions"] = set(row.get("untimed_sessions") or ()) | {
            r.get("session") for r in answer.get("sessions") or []
            if isinstance(r.get("session"), str) and r["session"] not in docs}
        # a task whose sessions exist but which no record prices keeps its row (its sessions and tokens are
        # real) with no figure: "no priced usage", the reason in the price note
        row.update(files=row["sessions"], sessions=len(answer.get("sessions") or []), price=answer, priced=priced,
                   price_low=answer.get("price_low_usd"), price_high=answer.get("price_high_usd"),
                   cost=answer.get("price_high_usd") or 0.0)
        by_task[task] = row
    whole_docs.update({d.get("session_id"): docs[session_key(d)] for d in rest
                       if d.get("session_id") and session_key(d) in docs})
    holders = {key: list(labels) for key, labels in held_mine.items()}
    for key, labels in held_rest.items():
        seen_keys = holders.setdefault(key, [])
        seen_keys.extend(k for k in (rest_key(label) for label in labels) if k not in seen_keys)
    price_rows = {t for t, r in by_task.items() if isinstance(r, dict) and r.get("price") is not None}
    attach_rowless_gaps(by_task, whole_docs.values(), holders, price_rows, task_of)
    return {"by_task": by_task, "days": days, "scopes": scopes, "rest": rest, "docs": docs}


def journal_records(driver, charged, task=None, factors=None) -> list:
    """One record per (session, dispatch) of every session the journal names (R8): {session, dispatch,
    role, turns, cost, mixed, bound}. `role` is `agent_label` of the pair's rows (a role, `conductor`, the
    scout for a ticket or data-fetching call), `turns` the sum of the rows' `num_turns`, `cost` the sum of
    the pair's row increments (`driver_journal.pair_records`), None (unknown, never $0) for every pair of
    a session the root rule refuses (`charged[session]` is None: its totals fall, are per call, or
    several journals hold it) and for a pair with an unusable increment. `task` keeps one task's sessions.
    `factors` ({session: factor}, `price_factors`) puts a pair's cost on the rate base of the price its story
    has, when the project prices at its own rates (the CLI's charge is at the catalogue's list rates)."""
    out = []
    for sid, entry in (driver or {}).items():
        if not isinstance(entry, dict) or not isinstance(entry.get("rows"), list):
            continue
        if task is not None and entry.get("task") != task:
            continue
        rows = entry["rows"]
        groups: dict = {}
        for row in rows:
            groups.setdefault(DJ.pair_key(row), []).append(row)
        known = (charged or {}).get(sid) is not None
        for pair in DJ.pair_records(sid, rows):
            cost = pair["cost"] if known else None
            if cost is not None and factors and sid in factors:
                cost = cost * factors[sid]
            out.append({"session": sid, "dispatch": pair["dispatch"], "role": DJ.agent_label(groups[pair["dispatch"]]),
                        "turns": pair["turns"], "cost": cost,
                        "mixed": pair["mixed"], "bound": True})
    return out


def _plus(total, value):
    return total if value is None else (total or 0.0) + float(value)


def agent_table(sessions, shared, answers, scopes, rest, driver, charged) -> tuple:
    """(rows, info) of "By agent". The money of every story's rows is its price answer's own rows
    (`by_agent`: the transcripts at catalogue rates, the CLI's charge, the price pair), so the rows
    add up to the price by the function's own check; the part of the ledger no price counts
    (`rest`) is priced as captured and re-priced at read. Counts are the per-(session, dispatch)
    records of the journal (R8, R10) and group_by_agent's for the rest: calls = dispatches, turns = their
    turns summed, max = the longest one, tokens = the sessions' own. info: driver (sessions a journal
    names), plain (other sessions), mixed, b_unknown, differing."""
    from dashboard_cost_groups import by_agent as group_by_agent
    docs = {session_key(s): s for s in list(sessions) + list(shared or [])}
    rows: dict = {}
    info = {"driver": 0, "plain": 0, "mixed": 0, "b_unknown": 0, "differing": 0}

    def row(label):
        return rows.setdefault(label, dict(calls=0, turns=0, max_turns=0, tokens=0, a=None, b=None, lo=None,
                                           hi=None, differing=0, b_unknown=0, remote_calls=0))
    for answer in (answers or {}).values():
        for a in answer.get("by_agent") or []:
            r = row(a["agent"])
            r["a"], r["b"] = _plus(r["a"], a.get("a_usd")), _plus(r["b"], a.get("b_usd"))
            r["lo"], r["hi"] = _plus(r["lo"], a.get("price_low_usd")), _plus(r["hi"], a.get("price_high_usd"))
            r["differing"] += a.get("differing_sessions") or 0
            r["b_unknown"] += a.get("b_unknown") or 0
            r["remote_calls"] += a.get("remote_calls") or 0
    bound = set()
    for rec in journal_records(driver, charged):
        if driver[rec["session"]].get("task") not in (answers or {}):
            continue
        r = row(rec["role"])
        r["calls"] += 1
        r["turns"] += rec["turns"]
        r["max_turns"] = max(r["max_turns"], rec["turns"])
        info["mixed"] += 1 if rec["mixed"] else 0
        bound.add(rec["session"])
    for sid in bound:
        if sid in docs:
            row(DJ.agent_label(driver[sid]["rows"]))["tokens"] += _session_tokens(docs[sid])
    segments = [_keyed_rows(docs[sid], idx) for per in (scopes or {}).values()
                for sid, idx in per.items() if idx is not None and sid in docs]
    counted = segments + list(rest)
    for label, v in (group_by_agent(counted) if counted else {}).items():
        r = row(label)
        r["calls"] += v["calls"]
        r["turns"] += v["turns"]
        r["max_turns"] = max(r["max_turns"], v["max_turns"])
        r["tokens"] += v["tokens"]
    for label, v in (group_by_agent(list(rest)) if rest else {}).items():
        if v["priced"]:
            r = row(label)
            r["a"], r["lo"], r["hi"] = _plus(r["a"], v["cost"]), _plus(r["lo"], v["cost"]), _plus(r["hi"], v["cost"])
    info["driver"] = len(bound)
    info["plain"] = len({session_key(d) for d in counted})
    info["b_unknown"] = sum(r["b_unknown"] for r in rows.values())
    info["differing"] = sum(r["differing"] for r in rows.values())
    return rows, info


def journal_binding_note(task_of, driver, spread, view=None, stray=False) -> str:
    """The By task note about where its sessions came from (R6, E4), in plain words: only when a
    driver journal binds a session (a root with none is drawn exactly as before), escaped. The note
    about the "not launched by the driver" label is printed only when the table has such a row
    (`stray`): a label that is not on the page is not explained."""
    if not task_of:
        return ""
    text = (" The driver's journal names the sessions it launched: each one is counted whole under the task whose "
            "journal names it, whatever task its cost file tags. A session that more than one task's journal names "
            "is counted under the task whose journal names it first.")
    if stray:
        text += (" A session a cost file tags to a task whose journal does not name it, and that no story activity "
                 "of that task binds, is listed apart as '<task> - not launched by the driver'.")
    multi = [multi_journal_note(sid, n, (driver or {}).get(sid)) for sid, n in sorted((spread or {}).items()) if n > 1]
    if multi:
        text += " " + "; ".join(multi) + "."
    return esc(text)


def select_task_sessions(sessions, tasks, driver=None, task_of=None) -> dict:
    """Split a root's sessions for a per-task view — nothing is dropped without a trace.

    whole: the session belongs to the task (its driver-runs row sits under it, or the cost
    file names only it); shared: the cost file also names other buckets, so only the task's
    `by_task` share is counted (`shares`); other: the session belongs to another task;
    not_attributed: nothing names a task — listed with its cost, never added. A driver-runs
    row is stronger evidence than the cost file's tagging: the driver launched that process
    for that story, and its turns before the first task tag are still the story's. `task_of` is
    the render's one binding (task_binding); without it the binding is read from `driver`."""
    driver, wanted = driver or {}, set(tasks)
    task_of = task_of if task_of is not None else task_binding(driver)
    out = {"whole": [], "shared": [], "shares": {}, "other": 0, "not_attributed": []}
    for s in sessions:
        sid = session_key(s)
        by_task = s.get("by_task") if isinstance(s.get("by_task"), dict) else {}
        names = _tagged_tasks(s)
        row_task = task_of.get(sid)
        hit = names & wanted
        if row_task in wanted:
            out["whole"].append(s)
        elif row_task:
            out["other"] += 1
        elif hit and any(t in by_task for t in hit) and len(by_task) > 1:
            parts = [by_task[t] for t in hit if t in by_task and isinstance(by_task[t], dict)]
            out["shared"].append(s)
            out["shares"][sid] = {"tokens": sum(p.get("tokens") or 0 for p in parts),
                                  "requests": sum(p.get("requests") or 0 for p in parts),
                                  "cost": (None if any(p.get("cost") is None for p in parts)
                                           else sum(p["cost"] for p in parts))}
        elif hit:
            out["whole"].append(s)
        elif names:
            out["other"] += 1
        else:
            out["not_attributed"].append(s)
    return out


def _session_tokens(s) -> int:
    return sum(sum(v.get(k, 0) or 0 for k in _TOKEN_KEYS) for v in (s.get("by_model") or {}).values())


def task_view_section(view: dict) -> str:
    """What the per-task view kept, counted by share, left out, and could not attribute."""
    # No dollar figure here: the task's money is its price (By task, the story card, By agent), and a second
    # figure for the shared sessions, taken from the tags of their cost files, would contradict it.
    lines = [f"Sessions of the task counted whole: {len(view['whole'])}.",
             f"Sessions shared with other tasks, of which only the requests this task's evidence binds are counted: "
             f"{len(view['shared'])}.",
             f"Sessions of other tasks, not shown: {view['other']}."]
    rows = "".join(f"<tr><td>{esc(session_key(s))}</td><td>{fmt_tok(_session_tokens(s))}</td>"
                   f"<td class='money'>{fmt_usd(s['priced_subtotal_usd']) if s.get('priced_subtotal_usd') is not None else '—'}</td></tr>"
                   for s in view["not_attributed"])
    table = (f"<h3>Not attributed to {esc(', '.join(view['tasks']))}</h3>"
             "<p class='nd'>No task is named by these sessions' cost file or by a driver-runs row. Listed with their "
             "cost, never added to the totals of this view.</p>"
             f"<table><tr><th>session</th><th>tokens</th><th>cost</th></tr>{rows}</table>") if rows else ""
    return ("<section><h2>Task view: " + esc(", ".join(view["tasks"])) + "</h2><p class='nd'>"
            + esc(" ".join(lines)) + "</p>" + table + "</section>")


def by_agent_note(sessions, info, driver, spread, answers=None) -> str:
    """Where the "By agent" rows came from, said out loud (FR-27) — and whose money it is (FR-25)."""
    status = Counter(str(s.get("usage_status") or "not recorded") for s in sessions)
    bits = ", ".join(f"{k} x{n}" for k, n in sorted(status.items()))
    text = (f" Cost and tokens: the cost files in state/cost (usage_status: {esc(bits)}); priced from state/cost "
            f"({esc('+'.join(sorted(status)))}), re-priced at read time at the catalogue's rates.")
    if driver:
        text += (f" Roles: artifacts/&lt;task&gt;/state/driver-runs.jsonl for {info['driver']} of {info['driver'] + info['plain']} sessions "
                 "(calls = dispatches: a session resumed for the same dispatch is one call; turns = the rows' "
                 f"num_turns summed; max = the longest single dispatch); {TP._plural(info['plain'], 'session', 'sessions')} "
                 f"with no such row {'keeps' if info['plain'] == 1 else 'keep'} the capture's own attribution.")
        multi = sorted(sid for sid, n in spread.items() if n > 1)
        if multi:
            # one clause per session, the session named once (it used to say "session X appears under 2 tasks
            # (session X is named by 2 task journals; counted under T)": the same fact twice in one line)
            text += " " + esc("; ".join(f"session {sid} appears under {spread[sid]} tasks"
                                        + _multi_journal_tail(driver.get(sid)) for sid in multi)) + "."
        if info["mixed"]:
            text += f" {info['mixed']} dispatch(es) carry role rows of different roles: the first role is kept."
    else:
        text += " Roles: the capture's own attribution (orchestrator and subagents); no driver-runs journal under this root."
    if answers:
        text += (" Two records of the same money stand in two columns: the transcripts column prices the usage stored "
                 "in each session's cost file at the catalogue's rates, and the CLI's column is what the CLI itself "
                 "charged, from the driver's journal. The price column is the price of the work: a range where the "
                 "two records differ, and a row marked 'differs' holds a session whose two records differ.")
        if info["b_unknown"]:
            text += (f" No CLI charge is known for {info['b_unknown']} session(s) (a dash where a row has none): "
                     "their price comes from the transcripts alone.")
    return text


def stale_outcomes(results) -> dict:
    """{session: why} of the recapture pass's outcomes that did NOT recompute a file (`skipped`,
    `not_recomputed`, `busy`: anything but `recomputed`), the pass's own reason first and the reason
    the file was flagged stale after it. A reason that names a door (`--recapture --session <id>`)
    keeps it: the text is the pass's, not this page's."""
    out = {}
    for r in results if isinstance(results, list) else []:
        # `kept` (a file of an older logic shown as recorded: a parent's, a live session's) is no alarm, as `recomputed`
        if not isinstance(r, dict) or not r.get("session_id") or r.get("status") in ("recomputed", "kept"):
            continue
        why = str(r.get("reason") or "no reason recorded")
        if r.get("stale_reason") and r["stale_reason"] != why:
            why += f" (flagged because: {r['stale_reason']})"
        out[r["session_id"]] = _Outcome(f"{str(r.get('status') or 'not recomputed').replace('_', ' ')} - {why}",
                                        r.get("code"))
    return out


class _Outcome(str):
    """The text of one pass outcome, carrying the machine `code` of its refusal (`live`, `size`, `parent`): a reader
    that must tell a live session's refusal from a door (`stale_files`) reads `.code`, not the wording. A plain str
    (a test's, an older caller's) has no code and is never taken for a live refusal."""

    def __new__(cls, text, code=None):
        value = super().__new__(cls, text)
        value.code = code
        return value


def stale_files(sessions, stale=None, marks=None) -> list:
    """(session, status, why) of every cost file whose figure is not the latest capture of its transcript:
    a file that carries `recapture_status` with a status other than `recomputed` (the capture wrote why it
    was left as it was), and a session the pass of THIS render skipped (`stale_outcomes`). Sorted by session.
    With `marks`: the pass's refusal of a session that is `live` ("still live") is not listed - the session is
    still being written, its own capture follows, and the page says so as information; a lock-give-up marker or
    a file's own `recapture_status` is listed as before (B-d)."""
    found = {}
    for s in sessions:
        status = s.get("recapture_status")
        if isinstance(status, dict) and status.get("status") != "recomputed":
            found[session_key(s)] = (str(status.get("status") or "no status recorded").replace("_", " "),
                                     str(status.get("reason") or "no reason recorded"))
    for s in sessions:
        key = session_key(s)
        if marks is not None and (marks.get(key) or {}).get("state") == "live" \
                and getattr(stale.get(key) if stale else None, "code", None) == "live":
            continue
        if key not in found and key in (stale or {}):
            status, _sep, why = str(stale[key]).partition(" - ")
            found[key] = (status, why or "no reason recorded")
    return [(sid, status, why) for sid, (status, why) in sorted(found.items())]


def tab_cost(sessions, _board=None, project_root_path=None, driver=None, spread=None, view=None,
             task_of=None, prices=None, reprice=None, charged=None, stale=None, marks=None):
    """`marks` is `session_marks`' answer, made ONCE per render by `main` and handed here and to
    `cost_capture_findings`: this function never works it out (a page that did would disagree with the other tab).
    `driver`/`spread` come from parse_driver_runs; `view` (select_task_sessions + "tasks")
    is the per-task view: `sessions` are then the whole-task ones and view["shared"] the ones whose
    other requests belong to other tasks (only what this task's evidence binds is counted). `task_of` is
    the render's one session -> task binding (read from `driver` when a caller gives none).

    `prices` is the render's ONE set of price answers ({task: task_price answer}, `price_answers`, made
    once by `main`): every money surface of a story on this tab reads it. `reprice` (`reprice_documents`'
    info) makes the tab say what was re-priced. A caller that hands neither, no journal and no task view gets
    today's draw (the sessions as given, no answer); one that hands a journal or a task view and no `prices`
    gets the answers computed here from the sessions (and the shared ones of the view) and the journal it
    handed. `charged` is `root_charged(driver)[0]`."""
    driver = driver or {}
    task_of = task_of if task_of is not None else task_binding(driver)
    if charged is None:
        charged = root_charged(driver)[0]
    if prices is None and (driver or view):
        inside, _outside = split_project_sessions(list(sessions) + list((view or {}).get("shared") or []),
                                                  project_root_path)
        prices = price_answers(project_root_path, price_task_ids(inside, task_of, (view or {}).get("tasks") or ()),
                               inside, driver, spread or {})
    return (task_view_section(view) if view else "") + _tab_cost(
        sessions, _board, project_root_path, driver, spread or {}, view, task_of, prices or {}, reprice, charged, stale,
        marks)


def price_notes_html(answers, only=()) -> str:
    """The price notes of `answers` as paragraphs (see price_notes); "" when there is none."""
    return "".join(f"<p class='nd'>{esc(note)}</p>" for note in price_notes(answers, only))


def _shown_answers(prices, view) -> dict:
    """The price answers this render draws: all of them, or only the asked-for tasks' in a task view."""
    if not prices:
        return {}
    if view:
        return {t: a for t, a in prices.items() if t in set(view.get("tasks") or ())}
    return dict(prices)


def _tab_cost(sessions, _board, project_root_path, driver, spread, view, task_of=None, prices=None,
              reprice=None, charged=None, stale=None, marks=None):
    out = []
    answers = _shown_answers(prices, view)
    asked = tuple((view or {}).get("tasks") or ())
    if not sessions:
        out.append("<section><p class='nd'>state/cost/ is empty — files are written by the Stop hook cost_capture.py during working sessions (check cost capture and usage availability in doctor)."
                   "</p>" + price_notes_html(answers, asked) + "</section>")
        out.append(formulas_block("cost"))
        return "".join(out)
    sessions, outside_sessions = split_project_sessions(sessions, project_root_path)
    if not sessions:
        out.append("<section><h2>Sessions of parent directories — not this project</h2>"
                   f"<p class='nd'>{len(outside_sessions)} captured session(s), none of them this project's "
                   "work. Shown, never summed.</p>"
                   + price_notes_html(answers, asked)
                   + "</section>")
        out.append(formulas_block("cost"))
        return "".join(out)
    tot_tok = tot_cost = wait = inter = 0
    priced = False
    orch_tok = 0
    by_model: dict = defaultdict(lambda: dict(requests=0, input=0, output=0, cache_read=0,
                                              cache_write_5m=0, cache_write_1h=0, cost=0.0, priced=False,
                                              coverage=set(), missing=set()))
    by_day: dict = defaultdict(lambda: dict(sessions=0, tokens=0, cost=0.0, priced=False, wait=0))
    tools: dict = defaultdict(int)
    recon_fail = 0
    external_calls = {}
    for s in sessions:
        for call in s.get("external_calls") or []:
            if isinstance(call, dict) and call.get("external_call_id"):
                external_calls[call["external_call_id"]] = call
        stoks = sum(sum(v[k] for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"))
                    for v in (s.get("by_model") or {}).values())
        otoks = sum(sum(v[k] for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"))
                    for v in ((s.get("orchestrator") or {}).get("by_model") or {}).values())
        # In a driver run every role is its own session, so the capture files ALL of it under
        # `orchestrator` (100%). The orchestrator was replaced by the conductor + code (owner,
        # 30.09): for a session the driver journal names, the share is the conductor's; the ticket call
        # and any other data-fetching call is the scout's (`agent_label`), never the orchestrator's.
        entry = driver.get(session_key(s))
        if entry:
            otoks = stoks if DJ.agent_label(entry["rows"]) == DJ.CONDUCTOR_LABEL else 0
        tot_tok += stoks
        orch_tok += otoks
        if s.get("priced_subtotal_usd") is not None and s.get("pricing_coverage") in {"complete", "partial"}:
            tot_cost += s["priced_subtotal_usd"]
            priced = True
        wait += s.get("human_wait_s") or 0
        inter += s.get("interactions") or 0
        if not (s.get("reconciliation") or {}).get("match", True):
            recon_fail += 1
        for m, v in (s.get("by_model") or {}).items():
            d = by_model[m]
            for k in ("requests", "input", "output", "cache_read", "cache_write_5m", "cache_write_1h"):
                d[k] += v.get(k, 0)
            if v.get("cost") is not None:
                d["cost"] += v["cost"]
                d["priced"] = True
            valuation = v.get("valuation") or {}
            if v.get('cost') is None and valuation.get('pricing_coverage') == 'partial':
                d['cost'] += float(valuation.get('subtotal_usd',0)); d['priced'] = True
            d["coverage"].add(valuation.get("pricing_coverage", "none"))
            d["missing"].update(valuation.get("missing_rate_categories") or [])
        from metrics_projection import timestamp
        ended = timestamp(s.get("ended"))
        day = ended.date().isoformat() if ended else "?"
        dd = by_day[day]
        dd["sessions"] += 1
        dd["tokens"] += stoks
        dd["wait"] += s.get("human_wait_s") or 0
        if s.get("total_cost_usd") is not None:
            dd["cost"] += s["total_cost_usd"]
            dd["priced"] = True
        for t, n in (s.get("tools") or {}).items():
            tools[t] += n

    share = f"{100 * orch_tok / tot_tok:.0f}%" if tot_tok else "—"
    unknown_usage = any(s.get("pricing_coverage") != "complete" for s in sessions)
    provisional_usage = any(s.get("usage_completeness") != "complete" for s in sessions)
    wait_known = all(s.get('human_wait_s') is not None for s in sessions)
    tariff_unconfirmed = any(((s.get("tariff_confirmation") or "unconfirmed") != "confirmed") for s in sessions)
    recon_unknown = unknown_usage or provisional_usage or any((s.get('reconciliation') or {}).get('match') is None for s in sessions)
    unknown_external = [x for x in external_calls.values()
                        if x.get("usage_status") != "available" or x.get("cost_usd") is None]
    if unknown_external:
        warnings = "".join(f"<li>External cost unknown: {esc(x.get('consumer_agent','unknown consumer'))} via "
                           f"{esc(x.get('invocation_method','unknown method'))}. Total is incomplete."
                           f" Task: {esc(x.get('task') or 'unattributed')}.</li>" for x in unknown_external)
        out.append(f"<section class='alert'><h2>Incomplete external cost</h2><ul>{warnings}</ul></section>")
    from dashboard_cost_groups import NOT_LAUNCHED
    from metric_signals import hot_cache_share
    task_of = task_of or {}
    charged = charged or {}
    shared = list((view or {}).get("shared") or [])
    answers_mode = bool(answers)
    # ONE partition of the ledger for By task, the story card, By agent and the spend card: each story
    # that has a price is one row drawn from the requests that price counts, with the price as its money;
    # what no price counts keeps group()'s labels (the binding moves a session between labels and never
    # changes a dollar, R4). Without answers it is group()'s, as before.
    groups = task_groups(sessions, shared, answers, task_of, driver, stray_apart=not view)
    by_task, request_days = groups["by_task"], groups["days"]
    # The sessions that only TAG a priced task (no journal, no story activity of it binds them): not in its price,
    # named on its row with where their money is counted - the final labels of the rows that hold them (E9).
    unbound = {}
    for task, row in by_task.items():
        if isinstance(row, dict) and row.get("price") is not None:
            ids = unbound_sessions(sessions, task, groups["scopes"], task_of)
            if ids:
                unbound[task] = (ids, sorted({label for label, other in by_task.items() if label != task
                                              and isinstance(other, dict) and set(ids) & set(other["session_ids"])}))
    # The findings are worked out HERE, before the cards: the two notes below read the same list the finding block
    # prints, and a note that points at "the finding above" must know whether there is one (FR-10, E6).
    findings = cost_findings_from_tasks(by_task, marks)
    unfinished = [s for s in sessions if s.get("usage_completeness") != "complete"]
    writing = [s for s in unfinished if marks is not None and (marks.get(session_key(s)) or {}).get("state") in ("live", "open")]
    provisional_finding = len(unfinished) > len(writing)
    recon_note = ("not possible — see the cost-capture finding above" if recon_unknown and findings
                  else f"not yet possible: {len(writing)} session{'s' if len(writing) != 1 else ''} not finished (see By task)"
                  if recon_unknown and writing and not provisional_finding and not unknown_usage
                  else "not possible: see By task for what is not complete" if recon_unknown
                  else "sums reconcile ✓" if not recon_fail else f"mismatch in {recon_fail} sessions!")
    usage_note = ("provisional usage" if provisional_finding
                  else f"final measured usage, except {len(writing)} session{'s' if len(writing) != 1 else ''} not finished"
                  if writing else "final measured usage")
    # The money of every row as a PAIR (low, high): a story's price, else what group() summed.
    total_low = total_high = 0.0
    any_money = False
    for v in by_task.values():
        if v.get("price") and v["priced"]:
            low, high = v["price_low"], v["price_high"]
        elif v["priced"]:
            low = high = v["cost"]
        else:
            continue
        total_low, total_high, any_money = total_low + low, total_high + high, True
    story_card = ""
    # A story is a task name that is a ticket key of THIS project's tracker (`adapter_forms`): `TP1-15045` on
    # Jira, `123` on GitHub issues; `orchestrator` and `(no task)` are never one.
    cfg = project_config(project_root_path) if project_root_path else {}
    story = max(((k, v) for k, v in by_task.items() if AF.is_key(str(k), cfg)),
                key=lambda kv: kv[1]["cost"], default=None)
    if story:
        answer = story[1].get("price")
        # Where the story stands (t-310): the same dict the driver prints as `[progress]`, drawn here. It gets
        # the price this card prints, in BOTH branches, so the page holds one price (t-323 B3, critic t-322 A-F3:
        # with no price answers the card printed `group()`'s sum while the block worked out `task_price` on its own
        # - two prices on one page, P18/FR-10). A card that prints a figure from a price answer passes that
        # answer; one that prints `group()`'s sum passes it as a recorded-only figure (one source, nothing to
        # cross-check); one that prints no figure passes a recorded-only price with no figure, and the block says
        # "recorded only" with no number.
        # A story with no records of its own on this root (a cost-only root) has no block, and a record that
        # cannot be read is a block that says so.
        if answer and story[1]["priced"]:
            printed = answer if isinstance(answer, dict) else {"status": "not_cross_checked"}
        elif story[1]["priced"]:
            printed = {"price_low_usd": story[1]["cost"], "price_high_usd": story[1]["cost"], "status": "not_cross_checked"}
        else:
            printed = {"status": "not_cross_checked"}
        where = ""
        try:
            task_dir = artifact_root(root=Path(project_root_path)) / str(story[0]) if project_root_path else None
            if task_dir and ((task_dir / "state" / "controller.json").is_file() or (task_dir / "pipeline.json").is_file()):
                import story_progress
                where = story_progress.render_html(story_progress.progress(task_dir, price=printed))
        except Exception as exc:
            where = f"<div class='progress nd'>where the story stands: not available ({esc(type(exc).__name__)})</div>"
        # The tariff label of the story's Codex calls (CX1-15 F-3): the driver priced them itself, from default tariffs,
        # and the card says so beside the figure. "" for a story with no Codex row - nothing is added to it.
        from retro_numbers import codex_tariff_label
        codex_label = codex_tariff_label(row for entry in (driver or {}).values()
                                         if isinstance(entry, dict) and entry.get("task") == story[0]
                                         for row in entry.get("rows") or [])
        if answer and story[1]["priced"]:
            # the price as the function gives it: a range while the two records differ, with its finding
            sub = f"{story[1]['sessions']} sessions · {fmt_tok(story[1]['tokens'])} tokens · {status_words(answer)}"
            if answer["status"] in (TP.DIFFERS, TP.INCOMPLETE) and answer.get("finding"):
                sub += " · " + answer["finding"]
            if answer.get("external_forms_line"):
                sub += " · " + answer["external_forms_line"]
            if codex_label:
                sub += " · " + codex_label
            if story[0] in unbound:
                sub += " · " + unbound_words(len(unbound[story[0]][0]))
            story_card = card(story[0], esc(answer_text(answer)), esc(sub), "#FDB022", chart=where)
        else:
            story_card = card(story[0], fmt_usd(story[1]["cost"]) if story[1]["priced"] else fmt_tok(story[1]["tokens"]),
                              f"{story[1]['sessions']} sessions · {fmt_tok(story[1]['tokens'])} tokens"
                              + (f" · {codex_label}" if codex_label else ""), "#FDB022", chart=where)
    spend_forms = TP.external_forms_line(sessions)   # the line under the spend figure: which agent forms it counted calls for
    spend_text = ((pair_text(total_low, total_high) if any_money else None) if answers_mode
                  else (fmt_usd(tot_cost) if priced else None))
    out.append("<div class='cards'>"
               + card("factory spend, known subtotal (floor)" if unknown_usage else "factory spend, this project",
                      spend_text or fmt_tok(tot_tok) + " tok.",
                      usage_note + ("; missing exact model/category prices" if unknown_usage else "; exact prices")
                      + ("; public reference/override — tariff unconfirmed" if tariff_unconfirmed else "; tariffs confirmed")
                      + (f"; {esc(spend_forms)}" if spend_forms else ""), "#FDB022")
               + story_card
               + card("tokens, this project's sessions", fmt_tok(tot_tok), "in+out+cache, whole sessions", "#C084FC")
               + card("orchestrator token share", share, "orchestrator IS INCLUDED in the count", "#2297F6")
               + card("human wait", fmt_dur(wait) if wait_known else "Unknown", f"{inter} recorded interactions", "#2dd4a0")
               + card("sum reconciliation", "?" if recon_unknown else "✓" if not recon_fail else "✗", recon_note, "#FDB022" if recon_unknown else "#2dd4a0" if not recon_fail else "#F9303C")
               + "</div>")
    # The catalogue revision, named once, and what was re-priced (E15/P8): figures captured before the
    # re-pricing were pinned at the project's table and are re-priced at read.
    if reprice or answers_mode:
        info = dict(reprice or {})
        info.setdefault("revision", next((a.get("catalogue_revision") for a in answers.values()
                                          if a.get("catalogue_revision")), None))
        info["overrides"] = sorted(set(info.get("overrides") or ())
                                   | {m for a in answers.values() for m in a.get("rate_overrides") or []})
        out.append(f"<p class='nd'>{esc(reprice_note(info))}</p>")

    if any((s.get('attribution_provenance') or {}).get('recovery') for s in sessions):
        out.append("<p class='nd'>Historical attribution recovered from reviewed activity tool calls. Original activity receipts are missing; gaps remain Unclassified. Recorded usage is provisional.</p>")
    if all(isinstance(s.get('requests'), list) for s in sessions):
        by_day = request_days

    # "By agent": this project's sessions only, request-level (same universe of dollars as
    # "By task" — see dashboard_cost_groups.by_agent for why the OLD per-stream aggregate
    # fields used to disagree with it), so the two totals match by construction.
    by_agent, agent_info = agent_table(sessions, shared, answers, groups["scopes"], groups["rest"], driver, charged)
    nf_tokens = sum(sum(sum(v.get(k, 0) or 0 for k in ('input','output','cache_read','cache_write_5m','cache_write_1h'))
                        for v in (s.get('by_model') or {}).values()) for s in outside_sessions)
    nf_priced = any(s.get('priced_subtotal_usd') is not None for s in outside_sessions)
    nf_cost = sum(s.get('priced_subtotal_usd') or 0 for s in outside_sessions if s.get('priced_subtotal_usd') is not None)

    # Every file that was NOT recomputed is listed, whatever the reason (a gone transcript, a live or huge one, a
    # busy writer, a marker left by a capture that gave up): its figure is the last capture, it may be LOWER than
    # what the session cost, and the reason (with the door it names) is the capture's own.
    not_recomputed = stale_files(sessions, stale, marks)
    if not_recomputed:
        rows = "".join(f"<li>{esc(sid)}: not recomputed ({esc(status)}) — {esc(why)}. Its figure is the last capture "
                       "and may be lower than what the session cost.</li>" for sid, status, why in not_recomputed)
        out.append(f"<section class='alert'><h2>Stale cost files</h2><ul>{rows}</ul></section>")

    composition = {key:sum(v.get(key,0) for v in by_model.values()) for key in ('input','output','cache_read','cache_write_5m','cache_write_1h')}
    composition_colors = ('#2297F6','#C084FC','#2dd4a0','#FDB022','#F9303C')
    comp_total = sum(composition.values())
    hot_share = hot_cache_share(composition)
    headline = f"{hot_share:.1f}%" if hot_share is not None else "—"
    legend = "".join(f"<div><span style='color:{c}'>&#9679;</span> {esc(k.replace('_',' '))} — {fmt_tok(v)} — "
                     f"{(100*v/comp_total):.1f}%</div>" if comp_total else ""
                     for (k, v), c in zip(composition.items(), composition_colors))
    out.append("<section><h2>Token composition</h2><div class='wcards'>"
        f"<div class='wcard' style='max-width:33%'><h3>Hot cache share: {headline}</h3>"
        + donut(list(zip(composition.values(), composition_colors)), headline, 'hot cache')
        + f"<div class='wleg'>{legend}</div>"
        "<p class='nd'>cache_read / (cache_read + cache_write_5m + cache_write_1h + input); output is never served from cache.</p>"
        "</div></div></section>")

    def task_row(t, v):
        text, cls, is_finding = task_completeness(v, marks)
        answer = v.get("price")
        if answer:
            # the price answer's own status leads the completeness cell and is the word on whether the price
            # is complete; what the capture still flags that the answer does not say (roles without usage,
            # sessions no record cross-checked that are still provisional, a capture sum that does not
            # reconcile) follows it. The capture's own "reconciled" / "not reconciled - prices incomplete"
            # are the capture's verdict on its own sums and say nothing the status does not (t-182: the
            # cell read "the two records agree; incomplete - 19 sessions provisional" beside a retro that
            # said the price was complete).
            words = status_words(answer)
            extra = "" if text in ("reconciled ✓", "not reconciled — prices incomplete") else text
            # Warn only for a finding, a status that is a problem, or a capture flag that is itself `warn`; an
            # information extra (class skip: a session still being written) never makes the cell warn, and the
            # information "single source" never hides a real gap, which stays warn and is named in the text.
            status = answer["status"]
            if is_finding or status in (TP.DIFFERS, TP.INCOMPLETE) or (extra and cls == "warn"):
                cls = "warn"
            elif status == TP.NOT_CROSS_CHECKED and answer.get("single_source") is True:
                cls = "info"
            elif status == TP.AGREES:
                cls = "ok"
            elif status == TP.NOT_CROSS_CHECKED:
                cls = "skip"
            else:
                cls = "warn"
            text = words + ("; " + extra if extra else "")
            if t in unbound:
                text += "; " + unbound_words(len(unbound[t][0]))
                cls = "warn"
            cell = pair_text(v["price_low"], v["price_high"]) if v["priced"] else "no priced usage"
        else:
            cell = fmt_usd(v["cost"]) if v["priced"] else "no priced usage"
        return (f"<tr><td>{esc(t)}</td><td>{v['sessions']}</td><td>{esc(time_cell(v))}</td>"
                f"<td>{fmt_tok(v['tokens'])}</td>"
                f"<td class='money'>{esc(cell)}</td>"
                f"<td class='{cls}'>{esc(text)}</td></tr>")
    trows = "".join(task_row(t, v) for t, v in sorted(by_task.items(), key=lambda kv: -kv[1]["cost"]))
    tsum = sum(v["cost"] for v in by_task.values() if v["priced"])
    tdur_cell = total_time_cell(by_task.values())
    unbound_notes = "".join(f"<p class='nd'>{esc(unbound_note(t, ids, labels))}</p>"
                            for t, (ids, labels) in sorted(unbound.items()))
    # The check row is the sum of the sessions' transcripts. It is the same figure as the total above while
    # every row is the transcripts' own; once a row is a price that holds the CLI's charge or a remote
    # receipt, the row says which sum it is instead of pretending to be a check (compared at cents).
    sessions_sum_agrees = (not answers_mode or (any_money and priced and _cents(total_low) == _cents(tot_cost)
                                                and _cents(total_high) == _cents(tot_cost)))
    task_check_label = ("Sum of sessions (check)" if sessions_sum_agrees else
                        "Sum of the sessions' transcripts (check; the total above also holds the CLI's charge and remote receipts)")
    total_cell = pair_text(total_low, total_high) if answers_mode and any_money else (
        fmt_usd(round(tsum, 2)) if priced else "—")
    # An incomplete or unreconcilable task cost is a defect of the factory's own capture, not
    # a grey "Unknown" the reader is left to interpret. Rendered here and counted into the
    # Factory tab's donut; nothing is written to factory-backlog.md by a render.
    if findings:
        out.insert(0, "<section class='alert'><h2>Factory findings — cost capture</h2><ul>"
                   + "".join(f"<li>{esc(f)}</li>" for f in findings) + "</ul></section>")
    tag_note = (" A task name that a cost file carries with no story activity of that task and no journal binding the "
                f"session to it is listed apart as '<task>{TAG_ONLY}': a tag is never evidence of spend."
                if any(str(k).endswith(TAG_ONLY) for k in by_task) else "")
    # The tolerance of the check, in words, ONCE on the page and whatever the records say: it is a property
    # of the check and not of a gap (an exact agreement is the case where a reader most needs to know how
    # close "agree" means). One source: the price function's constant.
    tolerance_note = (f" A story's two records are compared session by session, and a session agrees when they differ "
                      f"by no more than {TP.tolerance_words()}." if answers_mode else "")
    out.append("<section><h2>By task</h2><p class='nd'>This project's sessions only — a session belongs to the project when its transcript's project directory is this project. Each story accumulates its own usage across sessions; doctor, onboarding and unclassified usage stay separate. Amounts are estimated known subtotals, not subscription charges."
               + esc(tolerance_note)
               + journal_binding_note(task_of, driver, spread, view,
                                      any(str(k).endswith(NOT_LAUNCHED) for k in by_task)) + esc(tag_note) + "</p>"
               f"<table><tr><th>task</th><th>sessions</th><th>time</th><th>tokens</th><th>estimated known USD</th><th>completeness</th></tr>{trows}"
               f"<tr class='total'><td>All stories and activities</td><td></td><td>{esc(tdur_cell)}</td><td></td><td class='money'>{esc(total_cell)}</td><td></td></tr>"
               f"<tr class='total'><td>{esc(task_check_label)}</td><td></td><td></td><td></td><td class='money'>{fmt_usd(round(tot_cost, 2)) if priced else '—'}</td><td></td></tr></table>"
               + price_notes_html(answers, asked) + unbound_notes + "</section>")
    if outside_sessions:
        dirs = sorted({s2 for s2 in (__import__('cost_capture').session_project_slug(s) for s in outside_sessions) if s2})
        out.append(f"<section><h2>Sessions of parent directories — not this project</h2>"
                   f"<p class='nd'>{len(outside_sessions)} session(s) whose transcript lives "
                   + (f"in {esc(', '.join(dirs))}" if dirs else "outside this project's transcript folder")
                   + f", written into this project's cost folder. Shown, never summed: {fmt_tok(nf_tokens)} tokens"
                   + (f" · {fmt_usd(round(nf_cost, 2))}" if nf_priced else "") + ".</p></section>")

    def turns_cell(v: dict) -> str:
        """Total turns; if a single dispatch of the role crossed the cap, show the maximum too."""
        over = v["max_turns"] > MARATHON_TURNS
        extra = f' (max {v["max_turns"]})' if over else ""
        cls = " class='warn'" if over else ""
        ttl = f' title="the role\'s longest dispatch: {v["max_turns"]} turns against a cap of {MARATHON_TURNS}"' if over else ""
        return f"<td{cls}{ttl}>{v['turns']}{extra}</td>"


    def agent_note_cell(v: dict) -> str:
        """Marks a row that holds a session whose two records differ, and a remote call with no receipt."""
        bits = []
        if v["differing"]:
            bits.append(f"differs: {TP._plural(v['differing'], 'session', 'sessions')}")
        if v["remote_calls"]:
            bits.append(f"{TP._plural(v['remote_calls'], 'remote call', 'remote calls')} left no receipt: cost unknown")
        return f"<td class='{'warn' if v['differing'] else 'nd'}'>{esc('; '.join(bits))}</td>"

    col_a = sum(v["a"] for v in by_agent.values() if v["a"] is not None)
    col_b = sum(v["b"] for v in by_agent.values() if v["b"] is not None)
    rows_low = sum(v["lo"] for v in by_agent.values() if v["lo"] is not None)
    rows_high = sum(v["hi"] for v in by_agent.values() if v["hi"] is not None)
    rows_known = any(v["lo"] is not None for v in by_agent.values())
    # The cents of every column are chosen so that the printed rows add up to the printed total under
    # them (largest remainder, `task_price.display_cents`): rows that each round correctly can sum a cent
    # away from that total, and the page says the rows "add up to the price".
    ordered = sorted(by_agent.items(), key=lambda kv: (-(kv[1]["hi"] or 0.0), kv[0]))
    low_c, high_c, a_c, b_c = TP.display_cents(
        [[v["lo"] for _a, v in ordered], [v["hi"] for _a, v in ordered],
         [v["a"] for _a, v in ordered], [v["b"] for _a, v in ordered]],
        [rows_low if rows_known else None, rows_high if rows_known else None,
         col_a if any(v["a"] is not None for v in by_agent.values()) else None,
         col_b if any(v["b"] is not None for v in by_agent.values()) else None], not_below={1: 0})

    def cents_money(cents) -> str:
        return "—" if cents is None else TP.usd_from_cents(cents)

    def cents_pair(low, high) -> str:
        if low is None or high is None:
            return "—"
        return cents_money(low) if low == high else f"from {cents_money(low)} to {cents_money(high)}"

    arows = "".join("<tr><td><b>" + esc(a) + "</b></td><td>" + str(v["calls"]) + "</td>"
                    + turns_cell(v)
                    + "<td>" + fmt_tok(v["tokens"]) + "</td>"
                    + f"<td class='money'>{cents_money(a_c[i])}</td><td class='money'>{cents_money(b_c[i])}</td>"
                    + f"<td class='money'>{esc(cents_pair(low_c[i], high_c[i]))}</td>"
                    + agent_note_cell(v) + "</tr>"
                    for i, (a, v) in enumerate(ordered))
    aturns = sum(v["turns"] for v in by_agent.values())
    # The rows must add up to the price, at cents (never a float ==). The reference is the price of the
    # work as By task states it (the total of its rows); with no answer it is the sessions' own sum.
    reference = (((total_low, total_high) if any_money else None) if answers_mode
                 else ((tot_cost, tot_cost) if priced else None))
    rows_match = (reference is None and not rows_known) or (
        reference is not None and rows_known and _cents(rows_low) == _cents(reference[0])
        and _cents(rows_high) == _cents(reference[1]))
    if answers_mode:
        lead = ("This project's sessions only. "
                + ("The rows add up to the price." if rows_match else
                   "The rows do NOT add up to the price: this is a defect of the factory's measurement."))
        check_label = "The rows add up to the price (check)" if rows_match else "The rows do NOT add up to the price"
        check_cell = pair_text(*reference) if reference else "—"
    else:
        lead = "This project's sessions only, so this total matches By task's \"All stories and activities\"."
        check_label = "Sum of sessions (check)"
        check_cell = fmt_usd(round(tot_cost, 2)) if priced else "—"
    out.append(f"<section><h2>By agent</h2><p class='nd'>{lead}"
               f"{by_agent_note(list(sessions) + shared, agent_info, driver, spread, answers)}</p>"
               "<table><tr><th>agent</th><th>calls</th><th>turns</th><th>tokens</th>"
               "<th>transcripts at catalogue rates</th><th>the CLI's charge</th><th>price</th><th>records</th></tr>"
               f"{arows}"
               f"<tr class='total'><td>Sum of orchestrator + agents</td><td></td><td>{aturns}</td><td></td>"
               f"<td class='money'>{money(col_a) if rows_known else '—'}</td>"
               f"<td class='money'>{money(col_b) if any(v['b'] is not None for v in by_agent.values()) else '—'}</td>"
               f"<td class='money'>{esc(pair_text(rows_low, rows_high)) if rows_known else '—'}</td><td></td></tr>"
               f"<tr class='total'><td>{esc(check_label)}</td><td></td><td></td><td></td><td></td><td></td>"
               f"<td class='money'>{esc(check_cell)}</td><td class='{'ok' if rows_match else 'warn'}'>{'✓' if rows_match else '✗'}</td></tr></table></section>")

    mrows = "".join(f"<tr><td>{esc(m)}</td><td>{v['requests']}</td><td>{fmt_tok(v['input'])}</td><td>{fmt_tok(v['output'])}</td>"
                    f"<td>{fmt_tok(v['cache_read'])}</td><td>{fmt_tok(v['cache_write_5m'] + v['cache_write_1h'])}</td>"
                    f"<td>{esc('partial: missing '+', '.join(sorted(v['missing'])) if 'partial' in v['coverage'] else 'complete' if v['coverage']=={'complete'} else 'no exact price')}</td>"
                    f"<td class='money'>{fmt_usd(round(v['cost'], 2)) if v['priced'] else 'no exact price'}</td></tr>"
                    for m, v in sorted(by_model.items(), key=lambda kv: -kv[1]["cost"]))
    out.append(f"<section><h2>By model</h2><p class='nd'>This project's sessions only.</p><table><tr><th>model</th><th>calls</th><th>in</th><th>out</th>"
               f"<th>cache read</th><th>cache write</th><th>pricing</th><th>known subtotal</th></tr>{mrows}</table></section>")

    if external_calls:
        erows="".join(f"<tr><td>{esc(x.get('consumer_agent','?'))}</td><td>{esc(x.get('invocation_method','?'))}</td>"
            f"<td>{esc(x.get('task') or 'unattributed')}</td><td>{esc(x.get('usage_status','pending'))}</td>"
            f"<td class='money'>{fmt_usd(x['cost_usd']) if x.get('usage_status')=='available' and x.get('cost_usd') is not None else 'unknown'}</td></tr>"
            for x in external_calls.values())
        out.append(f"<section><h2>External consumers</h2><table><tr><th>consumer</th><th>invocation</th><th>task</th><th>receipt</th><th>remote cost</th></tr>{erows}</table>"
                   "<p class='nd'>Remote receipts are separate from local wrapper usage and are not inferred from provider summaries.</p></section>")

    drows = "".join(f"<tr><td>{esc(d)}</td><td>{v['sessions']}</td><td>{fmt_tok(v['tokens'])}</td>"
                    f"<td class='money'>{fmt_usd(round(v['cost'], 2)) if v['priced'] else '—'}</td><td>{fmt_dur(v['wait']) if v.get('wait') is not None else 'Unknown'}</td></tr>"
                    for d, v in sorted(by_day.items(), reverse=True)[:21])
    out.append(f"<section><h2>By day</h2><p class='nd'>This project's sessions only.</p><table><tr><th>day</th><th>sessions</th><th>tokens</th><th>cost</th>"
               f"<th>human wait</th></tr>{drows}</table></section>")

    maxt = max(tools.values()) if tools else 1
    tlrows = "".join(f"<tr><td>{esc(t)}</td><td>{n}</td><td><div class='bar' style='width:{round(180 * n / maxt)}px'></div></td></tr>"
                     for t, n in sorted(tools.items(), key=lambda kv: -kv[1])[:12])
    out.append(f"<section><h2>Top tools</h2><p class='nd'>This project's sessions only.</p><table><tr><th>tool</th><th>calls</th><th></th></tr>{tlrows}</table></section>")

    # "Latency telemetry" (p50/p95 spans, stage wall clock) was removed after the 15045
    # reading: 43 of 76 run blocks recorded an end before their start and no dispatch carried
    # a window, so every number in it was either unknown or wrong. telemetry_capture.py keeps
    # collecting spans — nothing reads them into this page any more.

    return "".join(out)


def dispatch_turns(sessions, driver=None, charged=None, task=None, factors=None) -> list:
    """{role, turns, cost, session, bound} for every dispatch across the project's sessions.

    A marathon is a property of ONE dispatch, not of a role's total: "By agent" already sums
    the turns, and a role with 23 short dispatches is not the signal the cap is about.

    A session the driver's journal names is priced and counted from the JOURNAL, one record per
    (session, dispatch): a driver session's cost file is one collapsed row per model, so its request
    rows say nothing about turns (R8). Its cost is None (unknown, never $0) where the journal cannot
    tell (`journal_records`); a session the journal names but that has no cost file is still a record
    (the journal is its only record). Every other session keeps its capture's records (a stream of a
    session is a dispatch), cost $0.00 only when the stream really cost nothing.

    `task` narrows the records to one task's (the banner's per-story share): the journal's sessions bound
    to it, and the requests of the sessions no journal names that are tagged with it, when no journal names
    that task (FR-24: a session the journal does not name never joins a journaled story).

    `factors` (`price_factors`) puts the journal's records on the price's rate base (see `journal_records`);
    the capture's own records are already at the price base (the files are re-priced at read)."""
    driver = driver or {}
    if charged is None:
        charged = root_charged(driver)[0]
    journaled = {e.get("task") for e in driver.values() if isinstance(e, dict)}
    out: dict = {}
    for n, record in enumerate(journal_records(driver, charged, task, factors)):
        out[("journal", n)] = {"role": record["role"], "turns": record["turns"], "cost": record["cost"],
                               "session": record["session"], "bound": True}
    if task is not None and task in journaled:
        sessions = []
    for index, s in enumerate(sessions):
        sid = s.get("session_id") or f"legacy-{index}"
        if isinstance(s.get("session_id"), str) and s["session_id"] in driver:
            continue
        file_to_agent = {a.get("file"): a.get("agent", "?") for a in s.get("agents") or []
                         if isinstance(a, dict) and a.get("file")}
        requests = s.get("requests")
        if isinstance(requests, list):
            for row in requests:
                if task is not None and row.get("task") != task:
                    continue
                stream = row.get("stream") or "orchestrator"
                record = out.setdefault((sid, stream),
                                        {"role": file_to_agent.get(stream, stream), "turns": 0, "cost": 0.0,
                                         "session": sid, "bound": False})
                record["turns"] += 1
                valuation = row.get("valuation") or {}
                if valuation.get("pricing_coverage") in ("partial", "complete"):
                    record["cost"] += float(valuation.get("subtotal_usd", 0) or 0)
        elif task is None:
            for a in s.get("agents") or []:
                turns = sum(v.get("requests", 0) for v in (a.get("by_model") or {}).values())
                out[(sid, a.get("file") or a.get("agent"))] = {
                    "role": a.get("agent", "?"), "turns": turns, "cost": float(a.get("cost") or 0),
                    "session": sid, "bound": False}
    return sorted(out.values(), key=lambda d: -d["turns"])


def orchestrator_split(dispatches) -> dict:
    """The orchestrator's share of a set of dispatch records: the ONE computation behind the health
    card and the banner line (and, on a driver run, what the retro prints). Orchestrator = the capture's
    orchestrator stream of sessions no journal names + the conductor's records (the driver's code spends
    no model money). A record of unknown cost is left out of BOTH sums and counted (`unknown`): it is
    never $0 and never a guess. `driver_sessions` / `file_sessions` are how many sessions each kind of
    record priced (the denominator mixes the driver's record with the cost files', C9)."""
    known = [d for d in dispatches if d["cost"] is not None]
    orch = sum(d["cost"] for d in known if d["role"] in ORCH_ROLES)
    total = sum(d["cost"] for d in known)
    return {"orch": orch, "total": total, "unknown": len(dispatches) - len(known),
            "conductor": sum(1 for d in known if d["role"] == DJ.CONDUCTOR_LABEL and d["bound"]),
            "driver_sessions": len({d["session"] for d in known if d["bound"]}),
            "file_sessions": len({d["session"] for d in known if not d["bound"]}),
            "bound": any(d["bound"] for d in dispatches),
            "percent": round(100.0 * orch / total, 1) if total else None}


def gate_block_finding(notes) -> str:
    """The identity of one gate block: the finding it names, not the whole notes line.

    exit_gate writes "block 1/1; broken artifacts: N; first: <finding>", and N moves with
    artifacts that have nothing to do with the finding. Counting the raw line made 13 events
    on TP1-15045 look like 13 refusals when they were 6 findings, one of them re-blocked
    seven times after a waiver.

    The reader is `retro_numbers.gate_block_class` (F6-51, AR-13): the first finding only (cut at "; "), at most 60
    characters; a block with no text is `(no finding text)`, which the card counts as one class like any other.
    """
    from retro_numbers import gate_block_class   # lazy, as the file's other retro_numbers reads: the ONE reader of the class
    return gate_block_class(notes)


def retry_breakdown(by_reason) -> str:
    """`turn_budget 3 - awaiting_person 2`, largest first: what the repeats were spent on."""
    items = sorted((by_reason or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    return " &middot; ".join(f"{esc(name)} {esc(count)}" for name, count in items)


def retry_signal(f05) -> str:
    """One banner line when the factory does the same work twice often enough to be a finding.

    A count of repeats is not a metric; the cause is. The line names the causes and says whose
    they are: every one of them is a finding about the factory or an incident of the host, and
    none of them is something the person has to repair.
    """
    value = f05 if isinstance(f05, dict) else {}
    retries, total = value.get("retries"), value.get("dispatches")
    by_reason = value.get("by_reason") or {}
    if not retries or not total:
        return ""
    share = 100 * retries / total
    worst = max(by_reason.values(), default=0)
    if share <= RETRY_SHARE_PERCENT and worst < RETRY_REASON_COUNT:
        return ""
    named = ", ".join(f"{name} {count}" for name, count in
                      sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0])))
    return (f"the factory does work twice: {named} - {retries} of {total} dispatches "
            f"({share:.0f} %). Each cause is a finding about the factory (FB) or an incident "
            "of the host, to be fixed here; none of it is the person's work to repair.")


def orchestrator_shares(sessions, taskruns, limit_percent, driver=None, task_of=None, charged=None, factors=None) -> list:
    """One line per story whose orchestrator outgrew the limit — the retro's own sentence.

    The threshold, the share and the per-stage split all come from `retro_numbers`, because a
    banner that words the same finding differently from the retro teaches the reader that they
    are two different numbers. A story with no orchestrator receipts of its own contributes
    nothing here: the metric is missing for it, never a zero share (TP2-2553).

    The share is `orchestrator_split` of the story's dispatch records: the SAME records and the same
    arithmetic the Factory health card reads, so the banner, the card and the retro give one share on a
    driver run (R12). In a driver run (`driver`: parse_driver_runs) those records are the journal's, the
    orchestrator is the conductor + code, and the per-stage split is the conductor's driver record by stage;
    a session the journal names counts for ITS journal's task (`task_of`), and one it does not name counts
    for no journaled story (FR-24), only for the task its rows tag when no journal names that task.

    `factors` ({session: factor}, `price_factors`): the journal's money put on the rate base of the price when
    the project prices at its own rates, for the split AND the stage parts (they add up to the same total).
    """
    from retro_numbers import orchestrator_by_stage, orchestrator_finding
    driver = driver or {}
    if charged is None:
        charged = root_charged(driver)[0]
    task_of = task_of if task_of is not None else task_binding(driver)
    journaled = set(task_of.values())

    out = []
    for run in taskruns or []:
        task = str(run.get("task") or "")
        if not task:
            continue
        split = orchestrator_split(dispatch_turns([s for s in sessions or [] if isinstance(s, dict)],
                                                  driver, charged, task, factors))
        if not split["total"] or not split["orch"]:
            continue
        if task in journaled:
            by_stage = orchestrator_by_stage(task, [], run.get("pipeline") or {}, driver, factors)
        else:
            files = [(None, s) for s in sessions or [] if isinstance(s, dict)
                     and not (isinstance(s.get("session_id"), str) and s["session_id"] in driver)]
            by_stage = orchestrator_by_stage(task, files, run.get("pipeline") or {})
        line = orchestrator_finding({
            "story": {"usd": split["total"]},
            "orchestrator_share_percent": split["percent"],
            "orchestrator_share_limit_percent": limit_percent,
            "orchestrator_share_basis": {"total_usd": split["total"]},
            "orchestrator_by_stage": by_stage})
        if line:
            out.append(f"{task}: {line}")
    return out


def factory_health(sessions, journal_events, taskruns, est_records, snapshot=None,
                   share_limit=None, driver=None, charged=None, on_project_rates=False, factors=None) -> str:
    """The cards a person reads when asking "is the factory itself healthy?" — every counter
    with the one line that says what it was, because a counter without one reads as a rebuke.

    `snapshot` is the metric projection: F05 (retries), F02 (rejected handoffs) and F07
    (manifest bookkeeping) are read here and drawn nowhere else. Until 0.7.15 each of them
    also had a chart in "Quality and outcomes" one screen below, saying the same number in
    different words. A render without a snapshot simply leaves those cards out."""
    dispatches = dispatch_turns(sessions, driver, charged, None, factors)
    marathons =[d for d in dispatches if d["turns"] > MARATHON_TURNS]
    named = " &middot; ".join(f"{esc(d['role'])} ({d['turns']} turns, "
                              f"{fmt_usd(d['cost']) if d['cost'] is not None else 'cost unknown'})"
                              for d in marathons[:3])
    events: dict = defaultdict(list)
    for e in journal_events:
        events[str(e.get("event") or "")].append(e)
    gate_blocks = events.get("gate_block", [])
    recheck = len(events.get("gate_recheck_passed", []))
    repeated = defaultdict(int)
    for e in gate_blocks:
        repeated[gate_block_finding(e.get("notes"))] += 1
    worst = max(repeated.items(), key=lambda kv: kv[1], default=("", 0))
    still_open = max(len(repeated) - recheck, 0)
    incomplete = [d for t in taskruns or []
                  for d in ((t.get("lifecycle") or {}).get("dispatches") or {}).values()
                  if isinstance(d, dict) and d.get("status") in {"blocked", "paused", "incomplete", "halted"}]
    incomplete_note = "; ".join(sorted({str(d.get("reason") or d.get("status") or "") for d in incomplete}))[:200]
    split = orchestrator_split(dispatches)
    orch, total = split["orch"], split["total"]
    if split["bound"]:
        # A driver record is present: say what the orchestrator is here, and how each figure was priced.
        share_sub = (f"{fmt_usd(orch)} of {fmt_usd(total)} priced &middot; in a driver run the orchestrator is the "
                     "conductor plus the driver's code, and that code spends no model money"
                     f" &middot; priced by the driver's record: {split['driver_sessions']} session(s), by the cost files: "
                     f"{split['file_sessions']} session(s)"
                     + (f" &middot; {split['unknown']} dispatch(es) of unknown cost left out of both sums"
                        if split["unknown"] else "")
                     + (" &middot; no conductor record: the share is 0%" if total and not split["conductor"] and not orch
                        else "")
                     + (" &middot; the driver's charges are put on the project's own rates, the same rates as the price"
                        if on_project_rates else ""))
    else:
        share_sub = f"{fmt_usd(orch)} of {fmt_usd(total)} priced"
    rework_rounds = sum(int(((r.get("actual") or {}).get("rework_rounds") or 0)) for r in est_records or [])
    rework_cost = sum(float(((r.get("actual") or {}).get("rework_cost_usd") or 0)) for r in est_records or [])
    cards = [
        card("marathon dispatches (>%d turns)" % MARATHON_TURNS, len(marathons),
             named or "none — every dispatch stayed inside the cap",
             "#F9303C" if marathons else "#2dd4a0", tip=MARATHON_TIP),
        card("gate_block", len(gate_blocks),
             (f"unique {len(repeated)} &middot; {still_open} still open"
              + (f"; {worst[1]} of them are one finding re-blocked" if worst[1] > 1 else ""))
             if gate_blocks else "the exit gate stopped nothing",
             "#F9303C" if still_open else "#FDB022" if gate_blocks else "#2dd4a0", tip=GATE_BLOCK_TIP),
        card("unsafe_completion", len(events.get("unsafe_completion", [])),
             "handoffs that went past honest acceptance", "#2dd4a0", tip=UNSAFE_TIP),
        card("dispatches ended incomplete", len(incomplete),
             incomplete_note or "none recorded", "#F9303C" if incomplete else "#2dd4a0"),
        # A measured share that bounds nothing is a number, not a signal: on TP2-2553
        # this card read 48% for a week and no reader could tell whether that was normal.
        card("orchestrator share of the cost", f"{100 * orch / total:.0f}%" if total else "—",
             share_sub
             + (f" &middot; limit {share_limit:.0f} %" if isinstance(share_limit, (int, float)) else ""),
             "#F9303C" if total and isinstance(share_limit, (int, float))
             and 100 * orch / total > share_limit else "#2297F6", tip=ORCHESTRATOR_TIP),
        card("repair rounds", rework_rounds,
             fmt_usd(rework_cost) + " of the stories' recorded cost" if rework_cost else "no repair cost recorded",
             "#FDB022" if rework_rounds else "#2dd4a0"),
    ]
    metrics = {m.get("id"): m for m in (snapshot or {}).get("metrics", [])}

    def metric_value(mid):
        entry = metrics.get(mid) or {}
        return entry.get("value") if entry.get("status") in ("available", "partial") else None

    f05 = metric_value("F05") or {}
    if f05.get("retries") is not None and f05.get("dispatches"):
        warned = bool(retry_signal(f05))
        cards.append(card("retries", esc("%d of %d dispatches (%.0f %%)"
                                         % (f05["retries"], f05["dispatches"], f05.get("percent") or 0)),
                          retry_breakdown(f05.get("by_reason"))
                          or "no cause recorded on any of them",
                          "#FDB022" if warned else "#2dd4a0" if not f05["retries"] else "#2297F6",
                          tip=RETRY_TIP))
    f02 = metric_value("F02") or {}
    if f02.get("rejected"):
        cards.append(card("rejected handoffs", f02["rejected"],
                          retry_breakdown(f02.get("by_reason")) or "no reason recorded",
                          "#FDB022"))
    out = "<section><h2>Factory health</h2><div class='cards'>" + "".join(cards) + "</div>"
    # F07 used to be a widget of its own that repeated the case-version proof gaps already
    # listed on the Testing tab. One line is what it is worth, and it says whose it is.
    issues = sum(len(row.get("issues") or []) for row in (metric_value("F07") or [])
                 if isinstance(row, dict))
    if issues:
        out += (f"<p class='nd'>manifest bookkeeping: {esc(issues)} issue(s) - owner: factory, "
                "tracked with the <a href='#findings'>findings about the factory</a> (FB).</p>")
    return out + "</section>"


def tab_factory(root, cfg, dd_open, sessions, journal_events, journal_exists, next_actions=None,
                taskruns=None, est_records=None, render_findings=(), snapshot=None, driver=None, charged=None,
                on_project_rates=False, factors=None):
    """The "Factory" tab: the factory's own setup obligations (findings about the factory,
    deferred decisions), current findings and factory health (rejects,
    gate blocks, the orchestrator share). The FB-N/DD-N codes appear in the id column of the
    tables and as the bar labels of the "Age of the open ones" widget (the decode — the same
    tables below); no other labels or legends carry them."""
    fb_path = ledger_path(root, "factory-backlog.md")
    fb_all = []
    for cells in parse_factory_findings(fb_path):
        fid, essence, scope, witness, created, status, resolution = (list(cells) + [""] * 7)[:7]
        fb_all.append({"id": fid, "essence": essence, "scope": scope, "witness": witness,
                       "created": created, "status": status, "resolution": resolution,
                       "open": status.lower().startswith("open")})
    fb_open_list = [f for f in fb_all if f["open"]]
    fb_closed = len(fb_all) - len(fb_open_list)

    # --- widget 1: findings about the factory + deferred decisions, by scope/type ---
    scope_colors = [(word, SCOPE_COLOR.get(word, SCOPE_COLOR_OTHER)) for word in FINDING_SCOPES]
    scope_counts: dict = defaultdict(int)
    for f in fb_open_list:
        scope_counts[f["scope"]] += 1
    # Findings the render itself computed (a task whose cost cannot be reconciled) count as
    # local-urgent here and nowhere else: a render never writes to factory-backlog.md.
    scope_counts["local-urgent"] += len(render_findings)
    donut_items = [(scope_counts.get(s, 0), c) for s, c in scope_colors] + [(len(dd_open), "#C084FC")]
    total_tails = sum(n for n, _ in donut_items)
    donut1 = donut(donut_items, str(total_tails), "open", size=150, thick=22)
    legend1 = ("<div class='wleg'><span class='warn'>&#9679; local-urgent</span> · "
               "<span class='skip'>&#9679; local-calibration</span> · "
               "<span style='color:#2297F6'>&#9679; upstream-candidate</span> · "
               "<span style='color:#C084FC'>&#9679; deferred decisions</span></div>")
    w1 = f"<div class='wcard'><h3>Findings about the factory and deferred decisions</h3>{donut1}{legend1}</div>"
    if not fb_path.is_file():
        w1 = "<div class='wcard'><h3>Findings about the factory and deferred decisions</h3><p class='nd'>Unavailable: factory-backlog.md is missing.</p></div>"

    # --- widget 2: age of the open ones (weeks since created), oldest first, bars by id ---
    age_items = []
    for d in dd_open:
        w = age_weeks_of(d.get("created"))
        if w is not None:
            age_items.append((w, d.get("id") or "DD-?"))
    for f in fb_open_list:
        w = age_weeks_of(f["created"])
        if w is not None:
            age_items.append((w, f["id"] or "FB-?"))
    age_items.sort(key=lambda x: -x[0])
    w2_body = age_columns_svg([(fid, w) for w, fid in age_items])
    w2 = (f"<div class='wcard'><h3>Age of the open ones</h3>{w2_body}"
          "<div class='wleg nd'>weeks since the creation date, oldest on top; "
          "<span style='color:#2297F6'>&#9679;</span> findings &middot; <span style='color:#C084FC'>&#9679;</span> decisions</div></div>")
    actions = ([str(x) for x in (next_actions or [])] + [str(x) for x in render_findings]
               + [d['id']+': '+d['essence'] for d in dd_open if d.get('ripe')])
    w3 = "<div class='wcard'><h3>Next actions</h3>" + ("<ul>"+''.join('<li>'+esc(a)+'</li>' for a in actions)+"</ul>" if actions else "<p class='nd'>No recorded blocker or triggered decision.</p>") + "</div>"


    out = [f"<section><h2>The factory at a glance</h2><div class='wcards'>{w1}{w2}{w3}</div></section>"]

    # --- findings about the factory ---
    def scope_span(scope):
        if scope == "local-urgent":
            return f"<span class='warn'>{esc(scope)}</span>"
        if scope == "local-calibration":
            return f"<span class='skip'>{esc(scope)}</span>"
        if scope == "upstream-candidate":
            return f"<span style='color:#2297F6'>{esc(scope)}</span>"
        return esc(scope) if scope else "—"
    fb_rows_html = "".join(_fb_row_html(f, scope_span) for f in sorted(fb_open_list, key=lambda f: -(age_weeks_of(f["created"]) or 0)))
    fb_rows_html += "".join(
        f"<tr><td>—</td><td>{esc(text)}</td><td class='warn'>local-urgent</td><td>this render</td><td>0 wk</td></tr>"
        for text in render_findings)
    fb_header = (f"Findings about the factory: {len(fb_open_list) + len(render_findings)} open"
                 + (f" (+ {fb_closed} fixed)" if fb_closed else ""))
    if fb_open_list or render_findings:
        out.append(f"<section class='findings'><h2 id='findings'>{esc(fb_header)}</h2><table class='tight1'><tr><th>id</th><th>essence</th>"
                   f"<th>scope</th><th>created</th><th>age</th></tr>{fb_rows_html}</table></section>")
    else:
        out.append("<section class='findings'><h2 id='findings'>Findings about the factory</h2>" + ("<p class='ok'>No open findings about the factory.</p>" if fb_path.is_file() else "<p class='nd'>Unavailable: factory-backlog.md is missing.</p>") + "</section>")

    # --- deferred decisions: the full table (reuses the render that used to live in the header) ---
    dd_ripe = [d for d in dd_open if d["ripe"]]
    if dd_open:
        out.append(f"<details class='deferred'{' open' if dd_ripe else ''}><summary><span>"
                   f"Deferred factory decisions: {len(dd_open)}"
                   + (f" · ripe {len(dd_ripe)}" if dd_ripe else "") +
                   "</span><span class='src'>factory-backlog.md</span></summary>"
                   + deferred_decisions_table(dd_open) + "</details>")
    else:
        out.append("<section class='deferred'><h2>Deferred decisions</h2>" + ("<p class='ok'>No open deferred decisions.</p>" if fb_path.is_file() else "<p class='nd'>Unavailable: factory-backlog.md is missing.</p>") + "</section>")

    own_sessions, _elsewhere = split_project_sessions(sessions, root)
    from retro_numbers import share_limit_from_cfg
    out.append(factory_health(own_sessions, journal_events, taskruns or [], est_records or [],
                              snapshot, share_limit_from_cfg(cfg), driver, charged, on_project_rates, factors))
    # --- test suite upkeep: live counters + the flags of the last qa-maintainer report ---
    # Its one home: A08 used to draw the same numbers as a second "Test health" widget.
    out.append(maintenance_section(load_maintenance(root)))

    from host_capabilities import inspect as inspect_host
    from metrics_projection import _display_value
    out.append("<details class='formulas'><summary>Host mechanism receipts</summary>" + _display_value(inspect_host(root)) + "</details>")
    out.append("<p class='nd'>Refresh: accepted changes, execution evidence, usage capture, doctor and S9. No background schedule.</p>")

    return "".join(out)


def _fb_row_html(f, scope_span):
    text = f["essence"]
    essence_cell = (f"<span title='{esc(text)}'>{esc(text[:79] + chr(8230))}</span>" if len(text) > 80 else esc(text))
    w = age_weeks_of(f["created"])
    return (f"<tr><td>{esc(f['id'])}</td><td>{essence_cell}</td><td>{scope_span(f['scope'])}</td>"
            f"<td>{esc(f['created']) if f['created'] else '—'}</td><td>{w if w is not None else '—'} wk</td></tr>")



def _package_version() -> str:
    """The installed package's own version, read from its manifest. The header carried a
    typed "0.7.0" through seven releases: a label nobody computes is a label nobody updates."""
    import json as _json
    for manifest in (".claude-plugin", ".codex-plugin", ".plugin"):
        try:
            data = _json.loads((Path(__file__).resolve().parent.parent / manifest / "plugin.json")
                               .read_text(encoding="utf-8"))
            version = str(data.get("version") or "").split("+", 1)[0].strip()
            if version:
                return version
        except Exception:
            continue
    return "version not reported"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--include-archive", action="store_true")
    ap.add_argument("--task", action="append", default=[], metavar="TICKET",
                    help="show only this task (repeatable); sections with no task key stay whole and say so")
    ap.add_argument("--out", default=None, help="write the page here instead of qa-factory/state/factory-dashboard.html")
    ap.add_argument("--read-only", action="store_true",
                    help="change nothing under --root: no cost recapture, no signal/history files; needs --out outside the root")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else project_root()
    wanted = list(dict.fromkeys(t.strip() for t in args.task if t.strip()))
    # A filtered page must never replace the whole page every session reads.
    if (args.read_only or wanted) and not args.out:
        ap.error("--read-only and --task need --out <file>: a partial or read-only render never writes the shared page")
    out_path = Path(args.out).resolve() if args.out else root / "qa-factory" / "state" / "factory-dashboard.html"
    if args.read_only and (out_path == root or root in out_path.parents):
        ap.error(f"--read-only refuses --out inside --root ({out_path}): nothing under the root may change")
    global _LEVEL_GLOBS
    _LEVEL_GLOBS = level_globs(root)

    cfg = project_config(root)     # the ONE reader of the config (BOM-tolerant): the pass and the marks read the same values

    bugs, bug_sources = load_bugs(root)
    loaded_docs = []
    stale = {}
    cost_dir = root / "qa-factory" / "state" / "cost"
    if cost_dir.exists():
        # A stale cost file (old format, or a backfilled activity that landed after the
        # original capture) is recomputed from its own transcript before the dashboard
        # reads it, same as any other dashboard-refresh path: honour the shared skip env var
        # so a red probe (run_suite.py sets it for the whole batch) never triggers this.
        if os.environ.get("QA_FACTORY_SKIP_DASHBOARD_REFRESH") != "1" and not args.read_only:
            try:
                from cost_capture import recapture_stale
                # What the pass did is kept, not thrown away: a file it did NOT recompute (a live or huge
                # transcript, a gone one, a busy writer) still shows its low figure, and the Cost tab's alert
                # must say so with the pass's own reason (and the door that reason names).
                stale = stale_outcomes(recapture_stale(root))
            except Exception:
                pass
        for f in sorted_paths(cost_dir.glob("*.json")):
            try:
                loaded = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(loaded, dict):
                continue      # not a cost file: no record, never a crash
            if not loaded.get("session_id"):
                loaded["_source_file"] = str(f)   # the identity of a file that carries none (session_key)
            loaded_docs.append(loaded)
    # EVERY cost file is re-priced ONCE, here, at read time: the catalogue's rates, a project's
    # `rate_overrides` as the price base exactly as `task_price` uses them. Nothing below reads the
    # valuations a file was captured with (they stay on disk as history), so the Cost tab's by-model,
    # by-task, by-agent, by-day, spend and estimate figures are all the catalogue's (FR-10).
    cost_cfg = cfg.get("cost") if isinstance(cfg.get("cost"), dict) else {}
    import cost_capture as cost_capture_module
    try:
        catalogue = cost_capture_module.load_catalogue()
    except Exception:
        catalogue = {}     # unreadable catalogue: every file is then counted as not re-priceable, and the page says so
    sessions, reprice = reprice_documents(loaded_docs, cost_cfg, catalogue)

    # The signals banner is built below from metric_signals.refresh. Until 0.7.12 an older
    # banner was ALSO computed here out of state/metrics-board.md — a file no role writes
    # any more — and then silently overwritten by the newer one before the page was assembled.

    # Open obligations from state/obligations.md (written by S8/S9): count + oldest age.
    # The full section lives on the "Testing" tab (first in its content) — the banner above
    # the tabs keeps only signals, no tables.
    ob_path = ledger_path(root, "obligations.md")
    ob_counts: dict = {}
    ob_list: list = []
    ob_list_all: list = []   # the whole root's open obligations: the estimates carry no task filter
    obligations_html = ""
    if ob_path.exists():
        open_obs, oldest = [], None
        for line in ob_path.read_text(encoding="utf-8", errors="replace").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
            if len(cells) >= 8 and cells[0].lower() not in ("id",) and not set("".join(cells)) <= {"-", ":", " "}:
                status = cells[7].lower()
                if status.startswith(("open", "ripe")):
                    ob_list_all.append((cells[3], cells[2], 1 if status.startswith("ripe") else 0, cells[6], cells[4]))
                if status.startswith(("open", "ripe")) and (not wanted or cells[3] in wanted):  # cells[3] = the task column
                    open_obs.append(cells)
                    a = ob_counts.setdefault(cells[3], [0, 0])
                    ripe_i = 1 if status.startswith("ripe") else 0
                    a[ripe_i] += 1
                    ob_list.append((cells[3], cells[2], ripe_i, cells[6], cells[4]))
                    m = re.match(r"\d{4}-\d{2}-\d{2}", cells[5])
                    if m:
                        age = (date.today() - datetime.strptime(m.group(0), "%Y-%m-%d").date()).days
                        oldest = age if oldest is None else max(oldest, age)
        def essence_cell(text, limit=180):
            # Walls of text in the essence (legal before the A16 date-cutoff) must not blow up
            # the table: show the first sentence, the rest behind an expander (operator decision).
            t2 = str(text).strip()
            if len(t2) <= limit:
                return esc(t2)
            cut = t2.find(". ", 40)
            head = t2[:cut + 1] if 0 < cut <= limit else t2[:limit].rsplit(" ", 1)[0] + "…"
            return (f"{esc(head)} <details class='subd' style='display:inline'>"
                    f"<summary class='sub-cap' style='display:inline;padding:0 6px;font-size:10px'>more</summary>"
                    f"<span class='nd'>{esc(t2[len(head):].strip())}</span></details>")

        if open_obs:
            ripe = [o for o in open_obs if o[7].lower().startswith("ripe")]
            obs_rows = "".join(f"<tr><td>{esc(o[0])}</td><td>{essence_cell(o[1])}</td><td>{esc(o[4])}</td><td>{esc(o[7])}</td></tr>"
                               for o in open_obs)
            age_note = "" if oldest is None else f", oldest {oldest} d"
            obligations_html = (f"<section class='alert'><h2>Remaining checks: {len(open_obs)}{age_note}"
                                + (f" &middot; ready to perform {len(ripe)}" if ripe else "") + "</h2>"
                                f"<table class='tight1'><tr><th>id</th><th>essence</th><th>trigger</th><th>status</th></tr>{obs_rows}</table>"
                                "<p class='nd'>Ledger: qa-factory/state/obligations.md; written by S8/S9, reviewed at the next applicable story preflight.</p></section>")

    # The factory's deferred decisions (onboarding/gates) from factory-backlog.md: a debt of
    # the factory's own setup, not a task obligation. No file/section — the list is empty; closed
    # rows are not shown. The full table lives on the "Factory" tab; the banner carries only the
    # signal line about the ripe ones (no tables above the tabs).
    dd_rows = parse_deferred_decisions(ledger_path(root, "factory-backlog.md"))
    dd_open = []
    from project_decisions import parse_rows as decision_rows, due as decision_due
    backlog_path = ledger_path(root, "factory-backlog.md")
    typed_decisions = {r["id"]:r for r in decision_rows(backlog_path.read_text(encoding="utf-8"))} if backlog_path.exists() else {}
    readiness = C.load_json(RP.readiness(root))
    verified_capabilities = {k for k,v in readiness.get("capabilities",{}).items() if isinstance(v,dict) and v.get("status")=="ok"}
    for row in dd_rows:
        did, essence_raw, trigger, created, status, resolution = (row["id"], row["essence"],
            row["trigger"], row["created"], row["status"], row["resolution"])
        if status.lower().startswith("closed"):
            continue
        essence, fname = split_marker(essence_raw)
        ripe_dd = decision_due(typed_decisions[did], verified_capabilities=verified_capabilities,
                               stories_since=completed_s9_since(root, created)) if did in typed_decisions else deferred_decision_ripe(trigger, created, status + " " + resolution)
        dd_open.append({"id": did, "essence": essence, "file": fname, "trigger": trigger,
                        "created": created, "ripe": ripe_dd})
    dd_ripe = [d for d in dd_open if d["ripe"]]
    # The sentence is kept here and joined to the banner where the banner is built (below): this line used to
    # append to `banner` before it existed, an UnboundLocalError on every render with a ripe decision.
    ripe_banner = (f"<section class='alert'><h2>Ripe deferred factory decisions: {len(dd_ripe)} — "
                   "recorded decision triggers need attention</h2></section>") if dd_ripe else ""

    # The factory event journal (records/journal.jsonl) — for "Factory health" on the "Factory" tab.
    # The journal the writers use: a person's own `journal_path` is honoured exactly as log_append.py
    # does (runtime_paths.configured), not the layout's default place (t-272, class row).
    journal_path = RP.configured(root, cfg.get("journal_path"), "journal.jsonl")
    journal_events = parse_journal(journal_path)
    journal_exists = journal_path.exists()

    # Estimation precedents (S9): records/estimation-ledger.jsonl — the cost join with cost/*.json,
    # the obligations join with ob_list above.
    est_records = parse_ledger(RP.record(root, "estimation-ledger.jsonl"))
    taskruns = parse_taskruns(root, args.include_archive)
    cases = parse_cases(root)
    # Hidden = flagged-archived stories plus anything still sitting in a legacy archive
    # folder. Counting only the folders (the old behaviour) reported 0 hidden the moment
    # archiving became a flag, which reads as "nothing archived" rather than "not shown".
    art_dir = artifact_root(root=root)
    archived_hidden = 0
    if not args.include_archive:
        archived_hidden = sum(1 for t in taskruns if t.get("archived"))
        for legacy in ("archive", "_archive"):
            d = art_dir / legacy
            if d.exists():
                archived_hidden += len(list(d.rglob("run-report.json")))
        taskruns = [t for t in taskruns if not t.get("archived")]
    all_runs = parse_taskruns(root, True)
    driver, spread = parse_driver_runs(root)
    # THE binding of this render, computed once: a session a driver journal names belongs whole to that
    # journal's task in every section that groups by task (By task and the story card, the cost findings
    # of both tabs, the estimates floor, the hot-cache signals, the banner).
    task_of = task_binding(driver)
    # What a journal session cost, asked of the journal ONCE (driver_journal.root_charged: a total is a
    # running total or one call's cost for the whole root, never per session): the health card, the
    # banner and By agent's dispatch records read this answer, and none of them prices a session on its
    # own. (A story's PRICE is `task_price`'s answer, asked once per task below.)
    charged, _unknown = root_charged(driver)
    # The per-task view (--task), an optional comparison view; without it nothing changes.
    # Metrics and trends are NEVER filtered (owner): every metric widget, the signals, the
    # history and the banner are drawn from the whole-root snapshot exactly as in the default
    # view, and carry the note all_tasks_note (a per-task swap of some metrics once put two
    # numbers for one quantity on one page). What --task filters is the lists of tasks, sessions
    # and cases: the Testing tab's stories, tests by level, bugs, ledger, obligations and
    # lifecycle; the Cost tab's By task / By agent / By model / By day / Top tools; the
    # per-story orchestrator share; and the estimates table (its own label says so). Factory
    # health and the findings of the factory read the whole root.
    task_view = None
    task_header = all_tasks_note = ""
    sessions_view, bugs_view = sessions, bugs
    taskruns_whole = taskruns
    if wanted:
        present = {t["task"] for t in all_runs}
        missing = [t for t in wanted if t not in present]
        others = len(present - set(wanted))
        taskruns = [t for t in taskruns if t["task"] in wanted]
        cases = [c for c in cases if c.get("task") in wanted]
        view_case_ids = {str(c.get("id")) for c in cases}
        def _bug_in_view(b):
            named = b.get("task") or b.get("story")
            if named:
                return str(named) in wanted
            return bool(set(C.case_ids(b.get("found_by")) or C.case_ids(b.get("case"))) & view_case_ids)
        bugs_view = [b for b in bugs if _bug_in_view(b)]
        inside, _outside_sessions = split_project_sessions(sessions, root)
        task_view = select_task_sessions(inside, wanted, driver, task_of)
        task_view["tasks"] = wanted
        sessions_view = task_view["whole"]
        all_tasks_note = "<p class='nd'>All tasks in this root: the sections below carry no task key.</p>"
        task_header = (f"<div class='meta'>Task: {esc(', '.join(wanted))} &middot; the root holds {others} other task(s), not shown</div>"
                       + "".join(f"<div class='meta warn'>no artifacts for {esc(t)} under {esc(root)}</div>" for t in missing))
        for t in missing:
            print(f"factory_dashboard: no artifacts for {t} under {root}")
    from metrics_projection import project as project_metrics
    registry_rows = []
    if backlog_path.exists():
        registry_rows.extend({"id": row["id"], "status": row["status"], "scope": row["scope"],
                              "created": row["created"],
                              "ripe": decision_due(typed_decisions[row["id"]], verified_capabilities=verified_capabilities,
                                                   stories_since=completed_s9_since(root, row["created"]))
                              if row["id"] in typed_decisions else False}
                             for row in dd_rows)
        for cells in parse_factory_findings(backlog_path):
            fid, _, scope, _, created, status, _ = (list(cells) + [""] * 7)[:7]
            registry_rows.append({"id": fid, "status": status, "scope": scope,
                                  "created": created, "ripe": False})
    # project() writes state/metrics.json under the root it reads unless told not to: a read-only
    # render asks for the same value with write=False, so nothing is opened for writing. Metrics,
    # trends and the history behind them are always the whole root's (the dashboard accumulates;
    # --task is a comparison view, never a filter of them).
    snapshot = project_metrics(root, all_runs, bugs, sessions, journal_events,
                               est_records, cfg, registry=registry_rows if backlog_path.exists() else None,
                               health=load_maintenance(root), write=not args.read_only)
    normalized_estimates = snapshot.get('estimates', [])
    est_view = [r for r in normalized_estimates if r.get("task") in wanted] if wanted else normalized_estimates
    # THE price answers of this render: `task_price` is asked ONCE per task, here, and By task, the story
    # card, By agent, the spend card, the task view and the estimates below all read these answers. The
    # tasks asked about are the journals', the ones story activities name, the task view's and the
    # estimates'; the function decides by evidence what belongs to each.
    project_sessions, _outside = split_project_sessions(sessions, root)
    # The state of every session of THIS render, worked out ONCE and handed to both tabs (B-b): the Cost tab and
    # the Factory tab's finding list cannot disagree about a session that is still being written.
    marks = session_marks(project_sessions, cfg.get("cost"), stale)
    price_tasks = price_task_ids(project_sessions, task_of,
                                 [r.get("task") for r in normalized_estimates] + [t["task"] for t in all_runs] + wanted)
    answers = price_answers(root, price_tasks, project_sessions, driver, spread, catalogue, cost_cfg)
    # The driver's charges, on the rate base of the price they sit beside (the Factory tab's share and the
    # banner): the CLI's list-price figure scaled per session when the project prices at its own rates.
    factors, on_project_rates = price_factors(answers)
    # A task's estimate figure is its PRICE (never the projection's own sum of the tags): one figure when
    # the records agree or only one exists (marked "single source (chat): ..." or "not cross-checked" in the notes), a floor when the
    # price is incomplete, a RANGE (no figure for the $-band widgets) while the two records differ, and
    # "no session of this task has a record" where nothing is known.
    cost_lookup, floor_tasks, floor_notes, price_ranges = estimate_prices(est_view, answers)
    est_signals = estimate_signals([r for r in est_view if r.get('completed')])
    from metric_signals import refresh as refresh_signals
    from dashboard_widgets import render as render_widgets, signals_html
    if args.read_only:
        # refresh_signals appends today's point to metrics-history.json and rewrites
        # metric-signals.json under the root it is given. A read-only render hands it a
        # scratch root holding copies of the two files: the same evaluation, no write into the root.
        with tempfile.TemporaryDirectory(prefix="factory-dashboard-") as scratch:
            source_state = root / "qa-factory" / "state"
            scratch_state = Path(scratch) / "qa-factory" / "state"
            scratch_state.mkdir(parents=True)
            for name in ("metrics-history.json", "metric-signals.json"):
                if (source_state / name).exists():
                    shutil.copyfile(source_state / name, scratch_state / name)
            signal_receipt, metric_history = refresh_signals(Path(scratch), snapshot, cfg, sessions, task_of)
    else:
        signal_receipt, metric_history = refresh_signals(root, snapshot, cfg, sessions, task_of)
    # The retry line rides with the estimate messages: it is a threshold on a projected value,
    # not a trend rule with a baseline, and the person reads it in the same place.
    retry_row = retry_signal(next((m.get("value") for m in snapshot.get("metrics", [])
                                   if m.get("id") == "F05" and m.get("status") == "available"), None))
    # F09 rides in the same place for the same reason: a threshold on a value the receipts
    # already carry, read by the person where every other threshold is read.
    from retro_numbers import share_limit_from_cfg
    share_rows = orchestrator_shares(sessions, taskruns, share_limit_from_cfg(cfg), driver, task_of, charged, factors)
    banner = signals_html(signal_receipt, ([retry_row] if retry_row else []) + share_rows) + ripe_banner + (f"<section class='alert'>Deferred decisions ready for review: {len(dd_ripe)}</section>" if dd_ripe else "")
    if wanted:
        banner = "<p class='nd'>Metric warnings and trends: all tasks in this root, never filtered (the history they are judged against is the whole root's).</p>" + banner
    testing_html = (bug_sources_note(bug_sources, len(bugs_view) if wanted else None)
                    + (all_tasks_note if wanted else "") + render_widgets(snapshot, "TA", metric_history))
    tabs = [("testing", "Testing", tab_automation(None, taskruns, cases, ob_counts, archived_hidden, ob_list, testing_html, obligations_html, bugs_view)),
            ("cost", "Cost", tab_cost(sessions_view if wanted else sessions, None, root, driver, spread, task_view, task_of,
                                      answers, reprice, charged, stale, marks)
             + all_tasks_note + render_widgets(snapshot, "C", metric_history)
             + ("<p class='nd'>The estimates table below shows " + esc(", ".join(wanted)) + " only; the metric widgets above are the whole root's.</p>" if wanted else "")
             + tab_estimates(est_view, ob_list_all, cost_lookup, est_signals, floor_tasks=floor_tasks, floor_notes=floor_notes,
                             price_ranges=price_ranges)),
            ("factory", "Factory", all_tasks_note + tab_factory(root, cfg, dd_open, sessions, journal_events, journal_exists, [t["task"]+": "+str((t.get("lifecycle") or {}).get("next_action",{}).get("action")) for t in taskruns_whole if (t.get("lifecycle") or {}).get("next_action")], taskruns_whole, est_records, cost_capture_findings(sessions, root, task_of, answers, driver, marks), snapshot, driver, charged, on_project_rates, factors) + render_widgets(snapshot, "F", metric_history))]
    nav = "".join(f"<button class='tab{' active' if i == 0 else ''}' data-tab='{tid}'>{esc(title)}</button>"
                  for i, (tid, title, _) in enumerate(tabs))
    panels = "".join(f"<div class='panel{' active' if i == 0 else ''}' id='{tid}'>{body}</div>"
                     for i, (tid, _, body) in enumerate(tabs))

    out = out_path
    page = ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Test Factory Metrics</title><style>"
            ":root{color-scheme:dark}"
            "body{font:14px/1.5 -apple-system,'Segoe UI',Arial,sans-serif;background:#101216;color:#e6e6e6;margin:0;padding:26px;max-width:1160px;margin-inline:auto}"
            "h1{font-size:21px;margin:0 0 2px}h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#8b929c;margin:4px 0 10px}"
            "h3{font-size:13px;margin:16px 0 6px;color:#c9ced6}"
            ".meta{color:#8b929c;font-size:12px;margin-bottom:16px}"
            "section{background:#14171c;border:1px solid #262a31;border-radius:12px;padding:16px 18px;margin:14px 0;overflow-x:auto}"
            "section.alert{border-color:#F9303C}"
            ".cards{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0}"
            ".card{background:#14171c;border:1px solid #262a31;border-top:3px solid #2297F6;border-radius:10px;padding:12px 16px;min-width:168px}"
            ".val{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}"
            ".lbl{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#8b929c;margin-top:2px}"
            ".sub{font-size:11px;color:#98a1ab}"
            "@media(max-width:700px){.metric-table tr{display:block;padding:12px 0;border-bottom:1px solid #262a31}.metric-table tr:first-child{display:none}.metric-table td{display:block;border:0;padding:4px 0;max-width:none!important}.metric-table td::before{content:attr(data-label) ': ';font-weight:600;color:#8b929c}.metric-table details{overflow-wrap:anywhere}}"
            "table{border-collapse:collapse;margin:6px 0;width:100%}th,td{border-bottom:1px solid #262a31;padding:5px 12px;text-align:left;font-size:12.5px}"
            "th{color:#8b929c;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #363b44}"
            "td{font-variant-numeric:tabular-nums}"
            "tr.total td{border-top:1px solid #363b44;font-weight:700}"
            ".money{color:#FDB022}.ok{color:#2dd4a0}.warn{color:#F9303C}.skip{color:#FDB022}.info{color:#98a1ab}.nd{color:#98a1ab;font-style:italic;font-size:12px}"
            ".unset{color:#c9727a}"
            ".d{font-size:12px;color:#FDB022}.flat{color:#8b929c}"
            ".bar{height:9px;background:#2297F6;border-radius:3px}"
            ".tabs{display:flex;gap:6px;margin:16px 0 4px}"
            ".tab{background:#14171c;border:1px solid #262a31;border-radius:999px;color:#8b929c;padding:7px 18px;font-size:13px;cursor:pointer}"
            ".tab.active{color:#e6e6e6;border-color:#2297F6}"
            ".panel{display:none}.panel.active{display:block}"
            "details.formulas{background:#14171c;border:1px dashed #363b44;border-radius:10px;padding:10px 16px;margin:14px 0}"
            "details.formulas{max-width:100%;box-sizing:border-box;overflow-x:auto;overflow-wrap:anywhere}details.formulas summary{cursor:pointer;color:#8b929c;font-size:12.5px}"
            "details.lvl{margin:8px 0}"
            "details.lvl summary{cursor:pointer;background:#14171c;border:1px solid #262b33;border-radius:8px;"
            "padding:8px 12px;color:#c8cdd4;font-size:13px}"
            "details.lvl summary:hover{border-color:#3a4150}"
            "details.lvl > *:not(summary){margin-left:20px;margin-right:4px}"
            "details.subd summary{cursor:pointer;list-style:none}details.subd summary::-webkit-details-marker{display:none}"
            "details.subd>summary.sub-cap::before{content:'\\25B8  ';color:#2297F6}"
            "details.subd[open]>summary.sub-cap::before{content:'\\25BE  ';color:#2297F6}"
            "details.subd summary:hover{border-color:#3a4150}"
            "details.lvl[open]{border-left:2px solid #23272f;border-radius:0 0 0 8px;padding-bottom:8px}"
            "details.feat{margin:14px 0;border:1px solid #2a3038;border-radius:10px;padding:4px 12px;background:#12151a}"
            "details.feat>summary{cursor:pointer;padding:9px 6px;font-size:13.5px;color:#e6e6e6}"
            "details.feat>summary:hover{color:#fff}"
            "details.taskd{margin:8px 0 10px 14px}"
            "details.taskd>summary{cursor:pointer;padding:7px 10px;background:#171b21;border:1px solid #262b33;"
            "border-radius:8px;color:#c8cdd4;font-size:12.5px}"
            "details.taskd>summary:hover{border-color:#3a4150}"
            "details.taskd>*:not(summary){margin-left:14px}"
            ".wcards{display:flex;gap:14px;flex-wrap:nowrap;align-items:stretch}"
            ".wcard{background:#14171c;border:1px solid #262b33;border-radius:10px;padding:14px 18px;flex:1 1 0;min-width:0;overflow:hidden}"
            ".wcards.mini{flex-wrap:wrap;margin:8px 0 4px;gap:10px}"
            ".wcards.mini .wcard{flex:0 1 auto;padding:10px 14px}"
            ".wcard h3{margin:0 0 10px;font-size:13.5px;color:#e6e6e6}"
            ".wleg{margin-top:8px;font-size:12px;color:#aab3bd}"
            ".tight1 td:first-child,.tight1 th:first-child{white-space:nowrap;width:1%}"
            ".est-tight td:nth-child(2),.est-tight th:nth-child(2){white-space:nowrap;width:1%}"
            "section.findings{background:#111722;border:1px solid #1f2c40;border-left:4px solid #2297F6}"
            "section.deferred{background:#171221;border:1px solid #2a2140;border-left:4px solid #C084FC}"
            "details.deferred{background:#171221;border:1px solid #2a2140;border-left:4px solid #C084FC;"
            "border-radius:12px;padding:0;margin:14px 0;overflow:hidden}"
            "details.deferred summary{cursor:pointer;list-style:none;padding:14px 18px;display:flex;"
            "justify-content:space-between;align-items:baseline;gap:12px;font-size:13px;color:#e6e6e6}"
            "details.deferred summary::-webkit-details-marker{display:none}"
            "details.deferred summary .src{color:#8b929c;font-size:11px;white-space:nowrap}"
            "details.deferred[open] summary{border-bottom:1px solid #2a2140}"
            "details.deferred table{margin:4px 18px 16px}"
            "table.dd td:nth-child(1),table.dd th:nth-child(1),table.dd td:nth-child(3),table.dd th:nth-child(3)"
            "{white-space:nowrap}"
            "table.dd tr.ripe td{background:#20182f}"
            ".dd-tag{color:#FDB022;font-size:11px;font-weight:700;white-space:nowrap}"
            ".wcard .nd{color:#98a1ab;font-style:normal}"
            ".sub-cap{display:block;margin:12px 0 6px;padding:6px 10px;font-size:11.5px;font-weight:700;color:#c8cdd4;"
            "text-transform:uppercase;letter-spacing:.5px;background:#191e26;border:1px solid #2a3038;"
            "border-left:3px solid #2297F6;border-radius:6px}"
            "details.lvl table{margin:6px 0 12px}"
            "details.lvl td[title]{cursor:help;text-decoration:underline dotted #3a4150}"
            "footer{color:#98a1ab;font-size:11.5px;margin-top:18px}"
            "table,td,p,li{color:inherit}.case-id{color:#98a1ab;font-size:11px;overflow-wrap:anywhere}"
            ".wrap{flex-wrap:wrap}.wrap .wcard{flex:1 1 260px}svg{max-width:100%;height:auto}a{color:#69baff}"
            # The case name is the visible text; the pytest node id is an overlay OUT OF FLOW
            # (position:absolute) so hovering never changes the row's height and the table
            # never jumps under the cursor.
            ".case{position:relative;display:block;cursor:help}.case .t{color:#e6e6e6}"
            ".case .id{display:none;position:absolute;left:0;top:100%;z-index:9;width:max-content;"
            "max-width:min(560px,80vw);padding:6px 9px;background:#1c2027;border:1px solid #3a4150;"
            "border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,.5);font:11px/1.35 Consolas,monospace;"
            "color:#c9ced6;white-space:normal;word-break:break-all}.case:hover .id{display:block}"
            ".pill{white-space:nowrap;display:inline-block;padding:1px 8px;border-radius:9px;font-size:11px;border:1px solid #363b44}"
            ".p-ok{color:#2dd4a0;border-color:#2dd4a0}.p-bug{color:#F9303C;border-color:#F9303C}"
            ".p-env{color:#FDB022;border-color:#FDB022}.p-wait{color:#8fb5ff;border-color:#8fb5ff}.p-grey{color:#98a1ab}"
            ".lv{white-space:nowrap;font-size:11px;color:#8b929c;text-transform:uppercase;letter-spacing:.06em}"
            ".chip{display:inline-block;background:#1c2027;border:1px solid #363b44;border-radius:6px;"
            "padding:0 7px;font-size:11px;color:#98a1ab;margin-left:6px}"
            "ul.left{margin:0;padding-left:18px;font-size:12.5px}"
            # A long subtitle must wrap inside its card, never widen it: one health card with
            # three named marathons used to stretch the whole row off the page.
            ".cards .card{flex:1 1 200px;max-width:260px}.cards .card .sub{white-space:normal;overflow-wrap:anywhere}"
            "@media(max-width:760px){body{padding:12px}.wcards{flex-wrap:wrap}.wcard{flex:1 1 260px}details.taskd{margin-left:0}details.taskd>*:not(summary){margin-left:0}details.lvl>*:not(summary){margin-left:0}.tabs{flex-wrap:wrap}.card{min-width:0;flex:1 1 150px}section{padding:12px}.feat,.taskd,.lvl{min-width:0;overflow-x:auto}}"
            "</style></head><body>"
            "<h1>Test Factory Metrics</h1>"
            f"<div class='meta'>QA Factory {esc(_package_version())}</div>"
            + task_header +
            f"<div class='meta'>Generated {datetime.now():%Y-%m-%d %H:%M} · testing · cost (+estimates by cost) · factory · "
            "trend over absolute · formulas expand within each suite</div>"
            + banner + f"<div class='tabs'>{nav}</div>{panels}"
            "<script>document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{"
            "document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));"
            "document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));"
            "b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active');}));document.querySelectorAll('[data-open-tab]').forEach(a=>a.addEventListener('click',()=>{document.querySelector('[data-tab='+a.dataset.openTab+']').click();let el=document.getElementById(a.hash.slice(1));for(let p=el;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;}));</script>"
            "<footer>Sources: state/metrics.json · bugs/*.md · state/bug-snapshot.json · state/cost/*.json (usage capture) · "
            "records/estimation-ledger.jsonl (estimation precedents, written at S9) · factory-backlog.md · "
            "records/journal.jsonl (the \"Factory\" tab). "
            "Render: factory_dashboard.py — deterministic, no LLM; refresh follows accepted artifacts, registry changes and usage capture; doctor can refresh on demand.</footer>"
            "</body></html>")
    page = re.sub(r"<svg width='([\d.]+)' height='([\d.]+)'", lambda m: f"<svg viewBox='0 0 {m[1]} {m[2]}' width='{m[1]}' height='{m[2]}' role='img'", page)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(page, encoding="utf-8")
    os.replace(temporary, out)
    print(f"factory_dashboard: {out} (stories {len(taskruns)}, bugs {len(bugs)}, cost sessions {len(sessions)})")


if __name__ == "__main__":
    main()
