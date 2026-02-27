#!/usr/bin/env python3
import argparse
import gzip
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Tuple

from urllib.parse import quote

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np


# EOSC barvy
EOSC_GREY = "#e4e4e3"
EOSC_GREEN = "#008691"
EOSC_PINK = "#ff5b7f"
EOSC_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "eosc", [EOSC_GREY, EOSC_GREEN, EOSC_PINK]
)


def open_any(path: Path):
    """Otevře JSONL nebo JSONL.GZ pro čtení textu."""
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def format_int_cz(n: int) -> str:
    """Tisíce oddělené mezerou podle CZ konvence."""
    return f"{n:,}".replace(",", " ")


def iter_records(path: Path):
    """Iterátor přes záznamy v JSONL."""
    with open_any(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def parse_created(rec: dict) -> date | None:
    """Vrátí datum z pole 'created' jako date."""
    created = rec.get("created")
    if not created:
        return None
    # Normalize 'Z' to +00:00
    created = created.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(created)
        return dt.date()
    except ValueError:
        return None


def get_publication_year(rec: dict) -> int | None:
    """Vrátí rok z metadata.publication_date, pokud jde rozumně přečíst."""
    meta = rec.get("metadata") or {}
    pub = meta.get("publication_date")
    if not pub or len(pub) < 4:
        return None
    try:
        return int(pub[:4])
    except ValueError:
        return None


def collect_counts(
    path: Path,
    start_date: date,
    end_date: date,
    pub_year_min: int = 2021,
    pub_year_max: int = 2025,
) -> Tuple[Dict[date, int], Dict[date, int]]:
    """Spočítá denní počty created pro všechny a pro 2021–2025."""
    counts_all: Counter[date] = Counter()
    counts_pub: Counter[date] = Counter()

    for rec in iter_records(path):
        d = parse_created(rec)
        if not d:
            continue
        if d < start_date or d > end_date:
            continue

        counts_all[d] += 1

        y = get_publication_year(rec)
        if y is not None and pub_year_min <= y <= pub_year_max:
            counts_pub[d] += 1

    # Doplnit nuly pro dny bez záznamů
    counts_all_full: Dict[date, int] = {}
    counts_pub_full: Dict[date, int] = {}
    cur = start_date
    while cur <= end_date:
        counts_all_full[cur] = counts_all.get(cur, 0)
        counts_pub_full[cur] = counts_pub.get(cur, 0)
        cur += timedelta(days=1)

    return counts_all_full, counts_pub_full


def compute_scale(
    counts: Dict[date, int],
    start_date: date,
    end_date: date,
    ignore_for_scale: date | None = None,
) -> Tuple[int, int]:
    """Najde min/max pro škálu, s možností ignorovat jeden den."""
    vals = []
    cur = start_date
    while cur <= end_date:
        if ignore_for_scale is not None and cur == ignore_for_scale:
            cur += timedelta(days=1)
            continue
        vals.append(counts.get(cur, 0))
        cur += timedelta(days=1)

    vals = [v for v in vals if v is not None]
    if not vals:
        return 0, 1
    vmin = min(vals)
    vmax = max(vals)
    if vmin == vmax:
        # zabránit delení nulou; posunout trochu
        vmin = 0
        vmax = max(vmax, 1)
    return vmin, vmax


def color_for_value(value: int, vmin: int, vmax: int) -> str:
    """Vrátí hex barvu podle EOSC colormapy."""
    if vmax <= vmin:
        t = 0.0
    else:
        t = (value - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, float(t)))
    rgb = EOSC_CMAP(t)
    return mcolors.to_hex(rgb)


def text_color_for_rgb(rgb: Tuple[int, int, int]) -> str:
    """Černý nebo bílý text podle jasu pozadí."""
    r, g, b = rgb
    # jednoduchý luminance odhad
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if luminance > 140 else "white"


def save_calendar_png(
    counts: Dict[date, int],
    start_date: date,
    end_date: date,
    title: str,
    png_path: Path,
    ignore_for_scale: date | None = None,
):
    """Uloží heatmap kalendář jako PNG do dané cesty."""
    png_path.parent.mkdir(parents=True, exist_ok=True)

    vmin, vmax = compute_scale(counts, start_date, end_date, ignore_for_scale)

    num_days = (end_date - start_date).days + 1
    num_weeks = math.ceil(num_days / 7)

    values = np.zeros((num_weeks, 7), dtype=int)
    labels_date = [["" for _ in range(7)] for _ in range(num_weeks)]
    labels_count = [["" for _ in range(7)] for _ in range(num_weeks)]

    for i in range(num_days):
        d = start_date + timedelta(days=i)
        week = i // 7
        dow = i % 7  # 0–6

        cnt = counts.get(d, 0)
        values[week, dow] = cnt
        labels_date[week][dow] = f"{d.day}.{d.month}."
        labels_count[week][dow] = format_int_cz(cnt) if cnt > 0 else ""

    fig_height = max(3.0, num_weeks * 0.6 + 1.5)
    fig, ax = plt.subplots(figsize=(10, fig_height))

    im = ax.imshow(values, cmap=EOSC_CMAP, aspect="auto", vmin=vmin, vmax=vmax)

    # Osy
    ax.set_xticks(range(7))
    ax.set_xticklabels(["Po", "Út", "St", "Čt", "Pá", "So", "Ne"])
    ax.set_yticks([])

    ax.set_title(title)

    # Popisky v buňkách
    for week in range(num_weeks):
        for dow in range(7):
            cnt = int(values[week, dow])
            # pozadí
            color_hex = color_for_value(cnt, vmin, vmax)
            r = int(color_hex[1:3], 16)
            g = int(color_hex[3:5], 16)
            b = int(color_hex[5:7], 16)

            if vmax > vmin:
                norm = (cnt - vmin) / (vmax - vmin)
            else:
                norm = 0.0
            text_color = text_color_for_rgb((r, g, b))
            if norm > 0.66:
                text_color = "white"

            # datum
            ax.text(
                dow,
                week - 0.15,
                labels_date[week][dow],
                ha="center",
                va="center",
                fontsize=6,
                color=text_color,
            )
            # počet
            ax.text(
                dow,
                week + 0.18,
                labels_count[week][dow],
                ha="center",
                va="center",
                fontsize=5,
                color=text_color,
            )

    # mřížka "čtverečků"
    ax.set_xticks(np.arange(-0.5, 7, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, num_weeks, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.5)
    ax.tick_params(which="both", length=0)

    fig.tight_layout()
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def generate_html(
    counts_all: Dict[date, int],
    counts_pub: Dict[date, int],
    start_date: date,
    end_date: date,
    summary_from: date,
    html_out: Path,
    nma_search_base: str,
    png_all: str | None = None,
    png_pub: str | None = None,
    ignore_for_scale: date | None = None,
):
    """
    Vygeneruje HTML stránku se dvěma kalendáři (vše / 2021–2025)
    a případně odkazy na PNG grafy.
    """

    def section_calendar(title: str, counts: Dict[date, int], filter_query: str | None):
        vmin, vmax = compute_scale(counts, start_date, end_date, ignore_for_scale)

        days_html = []
        current = start_date
        while current <= end_date:
            cnt = counts.get(current, 0)
            color_hex = color_for_value(cnt, vmin, vmax)

            r = int(color_hex[1:3], 16)
            g = int(color_hex[3:5], 16)
            b = int(color_hex[5:7], 16)
            text_color = text_color_for_rgb((r, g, b))
            if vmax > vmin:
                norm = (cnt - vmin) / (vmax - vmin)
            else:
                norm = 0.0
            if norm > 0.66:
                text_color = "white"

            date_label = f"{current.day}.{current.month}."
            date_iso = current.isoformat()

            if filter_query:
                term = f"created:[{date_iso} TO {date_iso}] AND {filter_query}"
            else:
                term = f"created:[{date_iso} TO {date_iso}]"

            q = quote(term, safe="")
            url = f"{nma_search_base}?q={q}"

            days_html.append(
                f'<a class="day" href="{url}" target="_blank" '
                f'style="background-color: {color_hex}; color: {text_color};">'
                f'<span class="date">{date_label}</span>'
                f'<span class="count">{format_int_cz(cnt)}</span>'
                f'</a>'
            )
            current += timedelta(days=1)

        dow_header = "".join(
            f'<div class="dow">{label}</div>'
            for label in ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
        )

        return (
            f'<section class="calendar-section">\n'
            f'  <h2>{title}</h2>\n'
            f'  <p class="hint">Kliknutím na den se otevře vyhledávání v NMA pro dané datum.</p>\n'
            f'  <div class="calendar-grid">\n'
            f'{dow_header}\n'
            f'{"".join(days_html)}\n'
            f'  </div>\n'
            f'</section>\n'
        )

    updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    extra_png_section = ""
    if png_all or png_pub:
        items = []
        if png_all:
            items.append(
                f'<li><a href="{png_all}">PNG: všechny záznamy (created)</a></li>'
            )
        if png_pub:
            items.append(
                f'<li><a href="{png_pub}">PNG: jen metadata.publication_date 2021–2025</a></li>'
            )
        extra_png_section = (
            "<section class=\"png-section\">\n"
            "  <h2>Obrázky ke stažení</h2>\n"
            "  <ul>\n"
            f"    {'\n    '.join(items)}\n"
            "  </ul>\n"
            "</section>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <title>Kalendář vytvoření záznamů v NMA</title>
  <style>
    :root {{
      --bg-page: #f7f7f7;
      --bg-card: #ffffff;
      --border-color: #dddddd;
      --text-main: #222222;
      --text-muted: #555555;
      --link: {EOSC_GREEN};
    }}

    * {{ box-sizing: border-box; }}

    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg-page);
      color: var(--text-main);
      margin: 0;
      padding: 0;
    }}

    .page {{
      max-width: 1200px;
      margin: 2rem auto;
      padding: 1.5rem;
      background: var(--bg-card);
      border-radius: 8px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    }}

    h1 {{
      margin-top: 0;
      margin-bottom: 0.25rem;
      font-size: 1.6rem;
    }}

    .subtitle {{
      margin-top: 0;
      margin-bottom: 1rem;
      color: var(--text-muted);
      font-size: 0.95rem;
    }}

    .meta {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-bottom: 1.5rem;
    }}

    a {{
      color: var(--link);
    }}

    .calendar-section {{
      margin-bottom: 2rem;
    }}

    .calendar-section h2 {{
      margin-bottom: 0.3rem;
      font-size: 1.3rem;
    }}

    .hint {{
      margin-top: 0;
      margin-bottom: 0.8rem;
      font-size: 0.85rem;
      color: var(--text-muted);
    }}

    .calendar-grid {{
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 4px;
      align-items: stretch;
    }}

    .dow {{
      text-align: center;
      font-weight: bold;
      font-size: 0.8rem;
      padding: 4px 0;
      color: var(--text-muted);
    }}

    .day {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 6px 4px;
      text-decoration: none;
      border-radius: 4px;
      min-height: 56px;
      transition: transform 0.1s ease, box-shadow 0.1s ease, opacity 0.15s ease;
    }}

    .day .date {{
      font-weight: bold;
      font-size: 0.8rem;
      margin-bottom: 2px;
    }}

    .day .count {{
      font-size: 0.75rem;
    }}

    .day:hover {{
      transform: translateY(-1px);
      box-shadow: 0 1px 4px rgba(0,0,0,0.15);
      opacity: 0.95;
    }}

    .legend {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 0.5rem;
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}

    .legend-bar {{
      display: inline-flex;
      height: 10px;
      width: 120px;
      background: linear-gradient(to right, {EOSC_GREY}, {EOSC_GREEN}, {EOSC_PINK});
      border-radius: 999px;
      border: 1px solid rgba(0,0,0,0.08);
    }}

    .png-section {{
      margin-top: 1.5rem;
      margin-bottom: 1.5rem;
    }}

    .png-section ul {{
      padding-left: 1.2rem;
    }}

    @media (max-width: 700px) {{
      .page {{
        margin: 0.5rem;
        padding: 1rem;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <h1>Kalendář vytvoření záznamů v NMA</h1>
    <p class="subtitle">
      Počty záznamů podle pole <code>created</code>, po dnech a týdnech.
    </p>
    <div class="meta">
      Generováno: {updated}<br>
      Rozsah dat: {start_date.isoformat()} – {end_date.isoformat()}<br>
      Textové tabulky: od {summary_from.isoformat()}
    </div>

    <div class="legend">
      <span>Legenda intenzity:</span>
      <span class="legend-bar"></span>
      <span>méně záznamů → více záznamů</span>
    </div>

    {section_calendar("Všechny záznamy (pole created)", counts_all, None)}

    {section_calendar("Jen záznamy s metadata.publication_date v letech 2021–2025",
                     counts_pub,
                     "metadata.publication_date:[2021 TO 2025]")}

    {extra_png_section}

    <p class="meta">
      Data: JSONL sklizeň z <a href="https://nma.eosc.cz" target="_blank" rel="noopener">NMA</a>.
      Kód skriptu: <code>stats/created_calendar.py</code>.
    </p>
  </div>
</body>
</html>
"""

    html_out.parent.mkdir(parents=True, exist_ok=True)
    with open(html_out, "w", encoding="utf-8") as f:
        f.write(html)


def write_summaries(
    counts_all: Dict[date, int],
    counts_pub: Dict[date, int],
    summary_from: date,
    stats_dir: Path,
):
    stats_dir.mkdir(parents=True, exist_ok=True)

    def to_lines(counts: Dict[date, int]):
        for d in sorted(counts.keys()):
            if d < summary_from:
                continue
            yield d, counts[d]

    # CSV
    with open(stats_dir / "created_counts_all.csv", "w", encoding="utf-8") as f:
        f.write("date,created_count\n")
        for d, cnt in to_lines(counts_all):
            f.write(f"{d.isoformat()},{cnt}\n")

    with open(
        stats_dir / "created_counts_pub_2021_2025.csv", "w", encoding="utf-8"
    ) as f:
        f.write("date,created_count\n")
        for d, cnt in to_lines(counts_pub):
            f.write(f"{d.isoformat()},{cnt}\n")

    # JSON
    json_all = [
        {"date": d.isoformat(), "created_count": cnt}
        for d, cnt in to_lines(counts_all)
    ]
    json_pub = [
        {"date": d.isoformat(), "created_count": cnt}
        for d, cnt in to_lines(counts_pub)
    ]

    with open(stats_dir / "created_counts_all.json", "w", encoding="utf-8") as f:
        json.dump(json_all, f, ensure_ascii=False, indent=2)

    with open(
        stats_dir / "created_counts_pub_2021_2025.json", "w", encoding="utf-8"
    ) as f:
        json.dump(json_pub, f, ensure_ascii=False, indent=2)


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Spočítá denní počty created a vygeneruje CSV, JSON, PNG kalendáře "
            "a HTML stránku."
        )
    )
    ap.add_argument(
        "--in",
        dest="input",
        required=True,
        help="Vstupní JSONL soubor (může být .gz).",
    )
    ap.add_argument(
        "--start-date",
        required=True,
        help="Počáteční datum (YYYY-MM-DD) – začátek kalendáře.",
    )
    ap.add_argument(
        "--end-date",
        required=True,
        help="Koncové datum (YYYY-MM-DD) – konec kalendáře.",
    )
    ap.add_argument(
        "--summary-from",
        required=True,
        help="Od kterého dne zapisovat textové souhrny (YYYY-MM-DD).",
    )
    ap.add_argument(
        "--html-out",
        required=True,
        help="Cesta k výstupnímu HTML souboru (např. docs/index.html).",
    )
    ap.add_argument(
        "--nma-search-base",
        default="https://nma.eosc.cz/datasets/",
        help="Základ URL pro NMA search (default: https://nma.eosc.cz/datasets/).",
    )
    return ap.parse_args()


def main():
    args = parse_args()

    input_path = Path(args.input)
    html_out = Path(args.html_out)
    stats_dir = Path("stats")

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    summary_from = date.fromisoformat(args.summary_from)

    # den, který ignorujeme v barvové škále (16. 1. 2026)
    ignore_for_scale = date(2026, 1, 16)

    counts_all, counts_pub = collect_counts(input_path, start_date, end_date)

    # textové výstupy
    write_summaries(counts_all, counts_pub, summary_from, stats_dir)

    # PNG do stejného adresáře jako HTML => docs/
    out_dir = html_out.parent
    png_all_path = out_dir / "calendar_created_all.png"
    png_pub_path = out_dir / "calendar_created_pub_2021_2025.png"

    save_calendar_png(
        counts_all,
        start_date,
        end_date,
        "Všechny záznamy (created)",
        png_all_path,
        ignore_for_scale=ignore_for_scale,
    )
    save_calendar_png(
        counts_pub,
        start_date,
        end_date,
        "Jen metadata.publication_date 2021–2025",
        png_pub_path,
        ignore_for_scale=ignore_for_scale,
    )

    # HTML (klikací kalendář) + odkazy na PNG
    generate_html(
        counts_all,
        counts_pub,
        start_date,
        end_date,
        summary_from,
        html_out,
        nma_search_base=args.nma_search_base,
        png_all=png_all_path.name,
        png_pub=png_pub_path.name,
        ignore_for_scale=ignore_for_scale,
    )


if __name__ == "__main__":
    main()
