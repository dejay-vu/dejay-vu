#!/usr/bin/env python3
"""dejayvu-smi — render all-time WakaTime coding stats as an nvidia-smi style panel.

Fetches https://wakatime.com/api/v1/users/current/stats/all_time (Basic auth with
WAKATIME_API_KEY) and rewrites the block between the waka section markers in
README.md. Stdlib only.

Usage:
  WAKATIME_API_KEY=... python scripts/dejayvu_smi.py       # live data, update README
  python scripts/dejayvu_smi.py --fixture scripts/fixture_stats.json
  python scripts/dejayvu_smi.py --fixture scripts/fixture_stats.json --dry-run
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://wakatime.com/api/v1/users/current/stats/all_time"
START_MARKER = "<!--START_SECTION:waka-->"
END_MARKER = "<!--END_SECTION:waka-->"

INNER = 89          # characters between the outer border pipes
C1, C2, C3 = 41, 24, 22  # top-box column widths (C1 + C2 + C3 + 2 separators == INNER)
BAR_WIDTH = 25
MAX_LANGS = 7
VRAM_CAP_MIB = 8760  # one year has 8760 hours

# nvidia-smi fields with no coding-stats equivalent; pure flavor
FLAVOR = {
    "smi_version": "5.0.0",
    "driver": "DPhil@Oxford",
    "cuda": "12.8",
    "gpu_name": "Junhao Zhang",
    "bus_id": "0000:OX:FD.0",
    "fan": "42%",
    "temp": "36C",
    "perf": "P0",
    "power": "65W / 300W",
    "util": "98%",
    "compute_mode": "Exclusive",
}

# languages rendered as compute+graphics processes; everything else is compute-only
CG_LANGUAGES = {"Python", "TypeScript", "JavaScript", "C++", "C", "CUDA", "Go", "Rust", "Java"}

EIGHTHS = "▏▎▍▌▋▊▉█"


def fit(text: str, width: int, align: str = "<") -> str:
    if len(text) > width:
        raise ValueError(f"segment too wide ({len(text)} > {width}): {text!r}")
    return f"{text:{align}{width}}"


def full_row(content: str) -> str:
    return f"|{fit(content, INNER)}|"


def col_row(a: str, b: str, c: str) -> str:
    return f"|{fit(a, C1)}|{fit(b, C2)}|{fit(c, C3)}|"


def bar(percent: float) -> str:
    filled = percent / 100.0 * BAR_WIDTH
    whole = int(filled)
    eighth = int((filled - whole) * 8)
    cells = "█" * whole + (EIGHTHS[eighth - 1] if eighth else "")
    return fit(cells, BAR_WIDTH).replace(" ", "░")


def hours_minutes(total_seconds: float) -> tuple[int, int]:
    return int(total_seconds) // 3600, (int(total_seconds) % 3600) // 60


def render(stats: dict, now: datetime) -> str:
    data = stats["data"]
    total_h, _ = hours_minutes(data["total_seconds"])
    used_mib = f"{total_h}MiB / {VRAM_CAP_MIB}MiB"

    lines = [
        f"{now:%a %b} {now.day:2d} {now:%H:%M:%S %Y}",
        "+" + "-" * INNER + "+",
        full_row(
            f" DEJAYVU-SMI {FLAVOR['smi_version']:<15}"
            f"Driver Version: {FLAVOR['driver']:<18}"
            f"CUDA Version: {FLAVOR['cuda']}"
        ),
        "|" + "-" * C1 + "+" + "-" * C2 + "+" + "-" * C3 + "|",
        col_row(" GPU  Name                 Persistence-M", " Bus-Id          Disp.A", " Volatile Uncorr. ECC"),
        col_row(" Fan  Temp   Perf          Pwr:Usage/Cap", "           Memory-Usage", " GPU-Util  Compute M."),
        "|" + "=" * C1 + "+" + "=" * C2 + "+" + "=" * C3 + "|",
        col_row(
            f"   0  {FLAVOR['gpu_name']:<26}{'On':>7}  ",
            f" {FLAVOR['bus_id']:>16}   On ",
            f"{'N/A':>20}  ",
        ),
        col_row(
            f" {FLAVOR['fan']:<4} {FLAVOR['temp']:<6} {FLAVOR['perf']:<11}{FLAVOR['power']:>15}  ",
            f"{used_mib:>21}  ",
            f"{FLAVOR['util']:>9}{FLAVOR['compute_mode']:>11}  ",
        ),
        "+" + "-" * C1 + "+" + "-" * C2 + "+" + "-" * C3 + "+",
        "",
        "+" + "-" * INNER + "+",
        full_row(" Processes (all-time coding activity, via WakaTime):"),
        full_row("  GPU   PID  Type  Process name        Util                         Time"),
        "|" + "=" * INNER + "|",
    ]

    languages = [l for l in data["languages"] if l["total_seconds"] > 0][:MAX_LANGS]
    for pid, lang in enumerate(languages, start=1):
        h, m = hours_minutes(lang["total_seconds"])
        ptype = "C+G" if lang["name"] in CG_LANGUAGES else "C"
        lines.append(
            full_row(
                f"{0:>5}{pid:>6}  {ptype:<5} {lang['name'][:17]:<17}  "
                f"{bar(lang['percent'])}  {lang['percent']:>5.1f} %  {h:>5} h {m:>2} m"
            )
        )
    lines.append("+" + "-" * INNER + "+")

    for line in lines[1:]:
        assert not line or len(line) == INNER + 2, f"misaligned row ({len(line)}): {line!r}"
    return "\n".join(lines)


def fetch_stats(api_key: str, tries: int = 5, delay: float = 10.0) -> dict:
    auth = base64.b64encode(api_key.encode()).decode()
    request = urllib.request.Request(API_URL, headers={"Authorization": f"Basic {auth}"})
    for attempt in range(1, tries + 1):
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read())
            # 202 means WakaTime is still recomputing the all_time range
            if response.status == 200 and body.get("data", {}).get("total_seconds") is not None:
                return body
        if attempt < tries:
            print(f"stats not ready (attempt {attempt}/{tries}), retrying in {delay:.0f}s")
            time.sleep(delay)
    raise RuntimeError("WakaTime stats not ready after retries")


def update_readme(readme: Path, panel: str) -> bool:
    text = readme.read_text(encoding="utf-8")
    try:
        head, rest = text.split(START_MARKER, 1)
        _, tail = rest.split(END_MARKER, 1)
    except ValueError:
        sys.exit(f"markers {START_MARKER} / {END_MARKER} not found in {readme}")
    new = f"{head}{START_MARKER}\n\n```text\n{panel}\n```\n\n{END_MARKER}{tail}"
    if new == text:
        return False
    readme.write_text(new, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="render from a stats JSON file instead of the API")
    parser.add_argument("--readme", type=Path, default=Path(__file__).resolve().parent.parent / "README.md")
    parser.add_argument("--dry-run", action="store_true", help="print the panel without touching the README")
    args = parser.parse_args()

    if args.fixture:
        stats = json.loads(args.fixture.read_text(encoding="utf-8"))
    else:
        api_key = os.environ.get("WAKATIME_API_KEY")
        if not api_key:
            sys.exit("WAKATIME_API_KEY is not set (or pass --fixture)")
        stats = fetch_stats(api_key)

    panel = render(stats, datetime.now(timezone.utc))
    if args.dry_run:
        print(panel)
        return
    changed = update_readme(args.readme, panel)
    print("README updated" if changed else "README already up to date")


if __name__ == "__main__":
    main()
