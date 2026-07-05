#!/usr/bin/env python3
"""Remap the fixed Ubuntu-terminal palette of lowlighter/metrics' terminal
template onto Tokyo Night, so the card matches the rest of the profile.

Context-sensitive rules run first: #ebedf0 doubles as body text (color:) and
as the isocalendar empty-cell fill, and the GitHub greens double as text and
cell ramps. Then plain hex swaps handle the rest.

Usage: python scripts/tokyonight_metrics.py metrics.terminal.svg
"""

import sys
from pathlib import Path

ORDERED_REPLACEMENTS = [
    # text roles first (color:...), before the same hexes are treated as fills
    ("color:#ebedf0", "color:#c0caf5"),   # body text
    ("color:#9be9a8", "color:#9ece6a"),   # highlight text
    ("color:#40c463", "color:#7aa2f7"),   # progress bar, filled
    ("color:#216e39", "color:#3d59a1"),   # progress bar, rest
    ("color:#777", "color:#565f89"),
    # isocalendar cells: GitHub light greens -> Tokyo Night blue ramp (low -> high)
    ("#ebedf0", "#24283b"),
    ("#9be9a8", "#2e4373"),
    ("#40c463", "#4368b1"),
    ("#30a14e", "#5d87dd"),
    ("#216e39", "#7aa2f7"),
    # terminal chrome
    ("#42092b", "#1a1b26"),               # aubergine background
    ("#3c3b37", "#16161e"),               # title bar
    ("#504b45", "#24283b"),
    ("#595953", "#414868"),
    ("#7d7871", "#414868"),
    ("#d5d0ce", "#a9b1d6"),               # title text
    ("#f37458", "#f7768e"),               # close button
    ("#de4c12", "#db4b4b"),
    # prompt & accents
    ("#7eda29", "#9ece6a"),               # ps1 user@host
    ("#4878c0", "#7aa2f7"),               # ps1 location
    ("#3a96dd", "#7dcfff"),               # diff header
    ("#ae9da7", "#565f89"),               # muted
    ("#ddd", "#a9b1d6"),
]


def main() -> None:
    path = Path(sys.argv[1])
    svg = path.read_text(encoding="utf-8")
    for old, new in ORDERED_REPLACEMENTS:
        svg = svg.replace(old, new)
    path.write_text(svg, encoding="utf-8")
    print(f"recolored {path}")


if __name__ == "__main__":
    main()
