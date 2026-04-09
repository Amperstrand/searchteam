#!/usr/bin/env python3
"""Run the venue scoring pipeline and render results as a static HTML comparison page."""

import html
import json
import subprocess
import sys
from pathlib import Path


def status_marker(status: str) -> str:
    return {"DISQUALIFIED": "✖", "current": "●", "rejected": "✗", "considered": "◐", "candidate": "○"}.get(status, "?")


def run_score_json(score_py: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(score_py), "--json"],
        capture_output=True, text=True, cwd=score_py.parent.parent,
    )
    if result.returncode != 0:
        print(f"score.py failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def pct_color(pct: float) -> str:
    if pct >= 70:
        return "#22c55e"
    if pct >= 50:
        return "#eab308"
    if pct >= 30:
        return "#f97316"
    return "#ef4444"


def bar_html(pct: float, width: int = 20) -> str:
    filled = int(width * pct / 100)
    empty = width - filled
    return f'<span class="bar" style="--pct:{pct}%;--color:{pct_color(pct)}">' \
           f'{"█" * filled}{"░" * empty}</span>'


def category_rows(categories: dict) -> str:
    rows = []
    for cat_name, cat in categories.items():
        cat_pct = (cat["score"] / cat["max"] * 100) if cat["max"] > 0 else 0
        items_html = ""
        for item in cat["items"]:
            marker = "✓" if item["raw"] >= 0.7 else ("~" if item["raw"] >= 0.3 else "✗")
            items_html += (
                f'<tr class="item-row">'
                f'<td>{marker}</td>'
                f'<td>{html.escape(item["label"])}</td>'
                f'<td class="weight">w{item["weight"]}</td>'
                f'<td>{html.escape(item["detail"])}</td>'
                f'</tr>\n'
            )
        rows.append(
            f'<tr class="cat-row">'
            f'<td colspan="4" class="cat-header">'
            f'<span class="cat-name">{cat_name}</span>'
            f'{bar_html(cat_pct)}'
            f'<span class="cat-pct" style="color:{pct_color(cat_pct)}">{cat_pct:.1f}%</span>'
            f'</td></tr>\n'
            f'{items_html}'
        )
    return "\n".join(rows)


def disqualified_rows(must_failures: list) -> str:
    rows = ""
    for f in must_failures:
        rows += f'<tr><td>✖</td><td>{html.escape(f["label"])}</td><td colspan="2">{html.escape(f["reason"])}</td></tr>\n'
    return rows


def venue_card(result: dict, rank: int) -> str:
    name = html.escape(result["name"])
    slug = html.escape(result["slug"])
    status = html.escape(result["status"])
    marker = status_marker(result["status"])

    if result["status"] == "DISQUALIFIED":
        return (
            f'<div class="venue-card disqualified" id="{slug}">'
            f'<div class="card-header">'
            f'<span class="rank">#{rank}</span>'
            f'<span class="marker">{marker}</span>'
            f'<h2>{name}</h2>'
            f'<span class="slug">{slug.upper()}</span>'
            f'<span class="status-badge disqualified-badge">DISQUALIFIED</span>'
            f'</div>'
            f'<table class="criteria-table">'
            f'<thead><tr><th></th><th>Criterion</th><th colspan="2">Reason</th></tr></thead>'
            f'<tbody>{disqualified_rows(result["must_failures"])}</tbody>'
            f'</table></div>\n'
        )

    pct = result["pct"]
    score = result["total_score"]
    max_score = result["max_score"]

    return (
        f'<div class="venue-card" id="{slug}">'
        f'<div class="card-header">'
        f'<span class="rank">#{rank}</span>'
        f'<span class="marker">{marker}</span>'
        f'<h2>{name}</h2>'
        f'<span class="slug">{slug.upper()}</span>'
        f'<span class="status-badge">{status}</span>'
        f'</div>'
        f'<div class="score-display">'
        f'<div class="score-big" style="color:{pct_color(pct)}">{pct:.1f}%</div>'
        f'<div class="score-detail">{score:.1f} / {max_score}</div>'
        f'</div>'
        f'<table class="criteria-table">'
        f'<thead><tr><th></th><th>Criterion</th><th>Weight</th><th>Value</th></tr></thead>'
        f'<tbody>{category_rows(result["categories"])}</tbody>'
        f'</table></div>\n'
    )


def summary_table(qualified: list) -> str:
    rows = ""
    for i, r in enumerate(qualified, 1):
        pct = r["pct"]
        safe_slug = html.escape(r["slug"])
        rows += (
            f'<tr onclick="document.getElementById(\'{safe_slug}\').scrollIntoView({{behavior:\'smooth\'}})">'
            f'<td>{i}</td>'
            f'<td><strong>{html.escape(r["name"])}</strong></td>'
            f'<td class="mono">{safe_slug}</td>'
            f'<td class="status-badge">{html.escape(r["status"])}</td>'
            f'<td style="color:{pct_color(pct)};font-weight:bold">{pct:.1f}%</td>'
            f'</tr>\n'
        )
    return rows


def generate_html(data: dict) -> str:
    event = data["event"]
    results = data["results"]
    qualified = data["qualified"]

    disqualified = [r for r in results if r["status"] == "DISQUALIFIED"]
    ranked = []
    for i, r in enumerate(qualified, 1):
        ranked.append(venue_card(r, i))
    dq_cards = []
    for r in disqualified:
        dq_cards.append(venue_card(r, "—"))

    safe_name = html.escape(event["name"])
    safe_budget = html.escape(str(event.get("budget_range_nok", "N/A")))
    safe_attendance = html.escape(str(event.get("expected_attendance", "N/A")))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_name} — Venue Comparison</title>
<style>
  :root {{
    --bg: #0a0a0f;
    --surface: #13131a;
    --border: #2a2a3a;
    --text: #e4e4e7;
    --text-dim: #71717a;
    --accent: #22d3ee;
    --green: #22c55e;
    --yellow: #eab308;
    --orange: #f97316;
    --red: #ef4444;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --mono: "SF Mono", "Fira Code", "Fira Mono", monospace;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem 1rem;
    max-width: 1100px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.8rem;
    margin-bottom: 0.25rem;
    color: var(--accent);
  }}
  .subtitle {{
    color: var(--text-dim);
    font-size: 0.95rem;
    margin-bottom: 2rem;
  }}
  .summary {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 2.5rem;
    overflow: hidden;
  }}
  .summary h2 {{
    padding: 1rem 1.5rem;
    font-size: 1.1rem;
    border-bottom: 1px solid var(--border);
    color: var(--accent);
  }}
  .summary table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .summary th, .summary td {{
    padding: 0.75rem 1.5rem;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }}
  .summary tr:last-child td {{ border-bottom: none; }}
  .summary tr {{ cursor: pointer; transition: background 0.15s; }}
  .summary tbody tr:hover {{ background: rgba(34,211,238,0.05); }}
  .mono {{ font-family: var(--mono); font-size: 0.85rem; color: var(--text-dim); }}
  .status-badge {{
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: 4px;
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    background: rgba(34,211,238,0.12);
    color: var(--accent);
  }}
  .disqualified-badge {{
    background: rgba(239,68,68,0.15);
    color: var(--red);
  }}
  .venue-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 1.5rem;
    overflow: hidden;
    scroll-margin-top: 1rem;
  }}
  .venue-card.disqualified {{
    opacity: 0.65;
    border-color: rgba(239,68,68,0.3);
  }}
  .card-header {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }}
  .card-header h2 {{
    font-size: 1.25rem;
    flex: 1;
    min-width: 200px;
    color: var(--text);
  }}
  .rank {{
    font-family: var(--mono);
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text-dim);
    min-width: 2rem;
  }}
  .marker {{ font-size: 1.2rem; }}
  .slug {{
    font-family: var(--mono);
    font-size: 0.8rem;
    color: var(--text-dim);
    text-transform: uppercase;
  }}
  .score-display {{
    display: flex;
    align-items: baseline;
    gap: 1rem;
    padding: 1.25rem 1.5rem;
  }}
  .score-big {{
    font-size: 2.5rem;
    font-weight: 800;
    font-family: var(--mono);
  }}
  .score-detail {{
    font-size: 1rem;
    color: var(--text-dim);
    font-family: var(--mono);
  }}
  .criteria-table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .criteria-table th {{
    text-align: left;
    padding: 0.5rem 1.5rem;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-dim);
    border-bottom: 1px solid var(--border);
  }}
  .criteria-table td {{
    padding: 0.35rem 1.5rem;
    font-size: 0.88rem;
    border-bottom: 1px solid rgba(42,42,58,0.5);
  }}
  .item-row td {{ padding-left: 2.5rem; }}
  .cat-row td {{ padding: 0; border-bottom: none; }}
  .cat-header {{
    display: flex !important;
    align-items: center;
    gap: 0.75rem;
    padding: 0.6rem 1.5rem !important;
    font-weight: 600;
    background: rgba(255,255,255,0.02);
  }}
  .cat-name {{
    min-width: 120px;
    font-size: 0.85rem;
  }}
  .cat-pct {{
    font-family: var(--mono);
    font-size: 0.85rem;
    font-weight: 700;
    min-width: 3.5rem;
    text-align: right;
  }}
  .bar {{
    font-family: var(--mono);
    font-size: 0.7rem;
    letter-spacing: -0.05em;
    color: var(--color);
  }}
  .weight {{
    font-family: var(--mono);
    font-size: 0.8rem;
    color: var(--text-dim);
  }}
  .section-title {{
    font-size: 1.1rem;
    color: var(--text-dim);
    margin: 2rem 0 1rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .footer {{
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 0.8rem;
  }}
</style>
</head>
<body>

<h1>{safe_name}</h1>
<p class="subtitle">
  Budget: {safe_budget} NOK &nbsp;|&nbsp;
  Target attendance: {safe_attendance} &nbsp;|&nbsp;
  {len(results)} venues evaluated, {len(qualified)} qualified
</p>

<div class="summary">
  <h2>Ranking</h2>
  <table>
    <thead>
      <tr><th>#</th><th>Venue</th><th>Slug</th><th>Status</th><th>Score</th></tr>
    </thead>
    <tbody>
      {summary_table(qualified)}
    </tbody>
  </table>
</div>

{"".join(ranked)}

{"<h3 class='section-title'>Disqualified</h3>" + "".join(dq_cards) if disqualified else ""}

<div class="footer">
  Generated by pipeline/render.py — scores from pipeline/score.py
</div>

</body>
</html>"""


def main():
    base = Path(__file__).parent.parent
    score_py = base / "pipeline" / "score.py"
    build_dir = base / "build"

    data = run_score_json(score_py)
    html = generate_html(data)

    build_dir.mkdir(exist_ok=True)
    out_path = build_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Rendered {len(data['results'])} venues to {out_path}")


if __name__ == "__main__":
    main()
