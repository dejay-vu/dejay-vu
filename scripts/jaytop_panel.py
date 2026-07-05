#!/usr/bin/env python3
"""jaytop panel — render the GitHub contribution timeline as an nvtop-style SVG.

Fetches the contribution calendar via the GitHub GraphQL API (bearer
GITHUB_TOKEN) and draws a terminal window with a smoothed utilization curve
(contributions/day, last 12 weeks) plus a streak/total status line. Stdlib only.

Usage:
  GITHUB_TOKEN=... python scripts/jaytop_panel.py
  python scripts/jaytop_panel.py --fixture scripts/fixture_contrib.json
"""

import argparse
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

GRAPHQL_URL = "https://api.github.com/graphql"
USERNAME = "dejay-vu"
QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

CHART_DAYS = 12 * 7

# Tokyo Night; text uses ink tokens, never the series color
BG, BORDER, GRID = "#1a1b26", "#292e42", "#292e42"
SERIES, ACCENT = "#7aa2f7", "#f7768e"
INK, INK_DIM, INK_FAINT = "#c0caf5", "#a9b1d6", "#565f89"
DOT_RED, DOT_YELLOW, DOT_GREEN, PROMPT = "#f7768e", "#e0af68", "#9ece6a", "#9ece6a"
MONO = "SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace"

W, H = 900, 320
BAR_H = 34
PLOT_L, PLOT_R, PLOT_T, PLOT_B = 50, 878, 66, 230
X_LABEL_Y, SEP_Y, FOOTER_Y = 248, 262, 286


def fetch_calendar(token: str) -> dict:
    payload = json.dumps({"query": QUERY, "variables": {"login": USERNAME}}).encode()
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read())
    if body.get("errors"):
        raise RuntimeError(f"GraphQL errors: {body['errors']}")
    return body


def flatten_days(body: dict) -> tuple[list[tuple[date, int]], int]:
    calendar = body["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = [
        (date.fromisoformat(d["date"]), d["contributionCount"])
        for week in calendar["weeks"]
        for d in week["contributionDays"]
    ]
    days.sort(key=lambda d: d[0])
    return days, calendar["totalContributions"]


def streaks(days: list[tuple[date, int]]) -> tuple[int, int]:
    counts = [c for _, c in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    current = 0
    tail = counts[:-1] if counts and counts[-1] == 0 else counts  # today at 0 doesn't break it
    for c in reversed(tail):
        if c == 0:
            break
        current += 1
    return current, longest


def smooth_path(points: list[tuple[float, float]]) -> str:
    # quadratic beziers through segment midpoints
    d = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        d.append(f"Q {x0:.1f} {y0:.1f} {(x0 + x1) / 2:.1f} {(y0 + y1) / 2:.1f}")
    d.append(f"L {points[-1][0]:.1f} {points[-1][1]:.1f}")
    return " ".join(d)


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def render(days: list[tuple[date, int]], total_12mo: int, today: date) -> str:
    window = days[-CHART_DAYS:]
    counts = [c for _, c in window]
    current, longest = streaks(days)

    # normalize to the smoothed curve's maximum so its crest touches the 100% line;
    # vertex of the midpoint quadratic at point i is (c[i-1] + 6*c[i] + c[i+1]) / 8
    n = len(window)
    smoothed_max = max(
        (counts[i - 1] + 6 * counts[i] + counts[i + 1]) / 8 if 0 < i < n - 1 else counts[i]
        for i in range(n)
    ) or 1
    span_x, span_y = PLOT_R - PLOT_L, PLOT_B - PLOT_T
    points = [
        (PLOT_L + i * span_x / (n - 1), PLOT_B - (c / smoothed_max) * span_y)
        for i, c in enumerate(counts)
    ]
    line_d = smooth_path(points)
    area_d = f"{line_d} L {points[-1][0]:.1f} {PLOT_B} L {points[0][0]:.1f} {PLOT_B} Z"
    dash = int(polyline_length(points) * 1.05) + 20

    peak_i = max(range(n), key=lambda i: window[i][1])
    peak_x, peak_y = points[peak_i]
    # the midpoint-smoothed curve undershoots the raw vertex; pin the dot to the curve
    if 0 < peak_i < n - 1:
        m0 = (points[peak_i - 1][1] + peak_y) / 2
        m1 = (peak_y + points[peak_i + 1][1]) / 2
        peak_y = (m0 + 2 * peak_y + m1) / 4
    # label sits beside the dot (never above/below) so it can't collide with the curve crest
    if peak_x < PLOT_L + 90:
        peak_anchor, peak_label_x = "start", peak_x + 10
    else:
        peak_anchor, peak_label_x = "end", peak_x - 10
    peak_label_y = peak_y + 3.5

    grid, y_labels = [], []
    for frac, label in [(0, "0%"), (0.25, "25%"), (0.5, "50%"), (0.75, "75%"), (1, "100%")]:
        y = PLOT_B - frac * span_y
        dashes = "" if frac == 0 else ' stroke-dasharray="3 4" opacity="0.55"'
        grid.append(f'<line x1="{PLOT_L}" y1="{y:.1f}" x2="{PLOT_R}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"{dashes}/>')
        y_labels.append(f'<text x="{PLOT_L - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="tick">{label}</text>')

    month_ticks, last_x = [], -1e9
    for i, (d, _) in enumerate(window):
        if d.day == 1 and points[i][0] - last_x > 44:
            month_ticks.append(f'<text x="{points[i][0]:.1f}" y="{X_LABEL_Y}" text-anchor="middle" class="tick">{d:%b}</text>')
            last_x = points[i][0]

    def stat(x: float, label: str, value: str) -> str:
        return (
            f'<text x="{x}" y="{FOOTER_Y}" class="stat">'
            f'<tspan fill="{PROMPT}">▸ </tspan>'
            f'<tspan fill="{INK}">{value}</tspan>'
            f'<tspan fill="{INK_FAINT}"> {label}</tspan></text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img"
     aria-label="GitHub contributions over the last 12 weeks, styled as a GPU utilization graph">
  <style>
    text {{ font-family: {MONO}; }}
    .tick  {{ font-size: 10px; fill: {INK_FAINT}; }}
    .title {{ font-size: 12px; fill: {INK_FAINT}; }}
    .legend {{ font-size: 11px; fill: {INK_DIM}; }}
    .stat  {{ font-size: 12.5px; }}
    .peaklabel {{ font-size: 10px; fill: {INK}; stroke: {BG}; stroke-width: 3px; paint-order: stroke; }}
    .meta  {{ font-size: 10px; fill: #3b4261; }}
    .line  {{ stroke-dasharray: {dash}; stroke-dashoffset: {dash}; animation: draw 1.8s ease-out 0.2s forwards; }}
    .fade  {{ opacity: 0; animation: fade 0.9s ease-out forwards; }}
    .fade-area {{ animation-delay: 1.0s; }}
    .fade-dot  {{ animation-delay: 1.7s; }}
    .fade-stats {{ animation-delay: 1.4s; }}
    @keyframes draw {{ to {{ stroke-dashoffset: 0; }} }}
    @keyframes fade {{ to {{ opacity: 1; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .line {{ animation: none; stroke-dashoffset: 0; }}
      .fade {{ animation: none; opacity: 1; }}
    }}
  </style>
  <defs>
    <linearGradient id="areafill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{SERIES}" stop-opacity="0.32"/>
      <stop offset="1" stop-color="{SERIES}" stop-opacity="0.02"/>
    </linearGradient>
    <clipPath id="plot"><rect x="{PLOT_L}" y="{PLOT_T - 6}" width="{span_x}" height="{span_y + 6}"/></clipPath>
  </defs>

  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="10" fill="{BG}" stroke="{BORDER}"/>
  <circle cx="22" cy="{BAR_H / 2}" r="5.5" fill="{DOT_RED}"/>
  <circle cx="42" cy="{BAR_H / 2}" r="5.5" fill="{DOT_YELLOW}"/>
  <circle cx="62" cy="{BAR_H / 2}" r="5.5" fill="{DOT_GREEN}"/>
  <text x="{W / 2}" y="{BAR_H / 2 + 4}" text-anchor="middle" class="title">dejayvu@oxford: ~ (jaytop)</text>
  <text x="{W - 16}" y="{BAR_H / 2 + 4}" text-anchor="end" class="meta">updated {today.isoformat()}</text>
  <line x1="0.5" y1="{BAR_H}" x2="{W - 0.5}" y2="{BAR_H}" stroke="{BORDER}"/>

  <text x="{PLOT_L}" y="54" class="legend">GPU 0: Junhao Zhang — Compute Utilization (contributions/day)</text>
  <text x="{PLOT_R}" y="54" text-anchor="end" class="tick">last 12 weeks</text>

  {"".join(grid)}
  {"".join(y_labels)}
  {"".join(month_ticks)}

  <g clip-path="url(#plot)">
    <path d="{area_d}" fill="url(#areafill)" class="fade fade-area"/>
    <path d="{line_d}" fill="none" stroke="{SERIES}" stroke-width="2" stroke-linejoin="round" class="line"/>
  </g>
  <g class="fade fade-dot">
    <circle cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="3.5" fill="{ACCENT}" stroke="{BG}" stroke-width="2"/>
    <text x="{peak_label_x:.1f}" y="{peak_label_y:.1f}" text-anchor="{peak_anchor}" class="peaklabel">peak {window[peak_i][1]}/day</text>
  </g>

  <line x1="0.5" y1="{SEP_Y}" x2="{W - 0.5}" y2="{SEP_Y}" stroke="{BORDER}"/>
  <g class="fade fade-stats">
    {stat(PLOT_L, "contributions (12 mo)", f"{total_12mo:,}")}
    {stat(380, "peak/day", str(window[peak_i][1]))}
    {stat(560, "current streak", f"{current}d")}
    {stat(730, "longest", f"{longest}d")}
  </g>
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="render from a GraphQL response JSON file")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "jaytop.svg")
    args = parser.parse_args()

    if args.fixture:
        body = json.loads(args.fixture.read_text(encoding="utf-8"))
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("GITHUB_TOKEN is not set (or pass --fixture)")
        body = fetch_calendar(token)

    days, total = flatten_days(body)
    svg = render(days, total, datetime.now(timezone.utc).date())
    args.output.write_text(svg, encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
