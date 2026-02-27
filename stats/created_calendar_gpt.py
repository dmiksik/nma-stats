#!/usr/bin/env python3
import argparse
import csv
import gzip
import json
from datetime import datetime, date, timedelta
import math
from pathlib import Path
from urllib.parse import quote

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap


def open_in(path: str):
    """Otevře vstupní JSONL nebo JSONL.GZ podle přípony."""
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Spočítá počty záznamů podle pole 'created', vykreslí kalendářový heatmap "
            "a vygeneruje HTML s klikacími dny do NMA "
            "(větev A: všechny záznamy, větev B: jen metadata.publication_date 2021–2025)."
        )
    )
    ap.add_argument(
        "--in",
        dest="inp",
        required=True,
        help="Vstupní JSONL (.jsonl nebo .jsonl.gz), každý řádek = jeden záznam.",
    )
    # první datum v kalendářové mřížce (týden začíná tady)
    ap.add_argument(
        "--start-date",
        default="2026-01-12",
        help="První datum v kalendářové mřížce (YYYY-MM-DD), default 2026-01-12.",
    )
    # od kdy tě zajímá textový výpis a CSV/JSON
    ap.add_argument(
        "--summary-from",
        default="2026-01-16",
        help="První datum zahrnuté v CSV/JSON výpisu (YYYY-MM-DD), default 2026-01-16.",
    )
    ap.add_argument(
        "--end-date",
        default=None,
        help="Poslední datum (YYYY-MM-DD). Pokud není, vezme se dnešní den.",
    )
    # výstupy pro větev A (všechny záznamy)
    ap.add_argument(
        "--csv-out",
        default="stats/created_by_day.csv",
        help="Výstupní CSV (všechny záznamy) s počty created/den (default: stats/created_by_day.csv).",
    )
    ap.add_argument(
        "--json-out",
        default="stats/created_by_day.json",
        help="Výstupní JSON (všechny záznamy) s počty created/den (default: stats/created_by_day.json).",
    )
    ap.add_argument(
        "--png-out",
        default="stats/created_calendar.png",
        help="Výstupní PNG (všechny záznamy) s kalendářovým grafem (default: stats/created_calendar.png).",
    )
    # výstupy pro větev B (jen publication_date 2021–2025)
    ap.add_argument(
        "--csv-out-pub",
        default="stats/created_by_day_pub2021_2025.csv",
        help="Výstupní CSV (jen publication_date 2021–2025) (default: stats/created_by_day_pub2021_2025.csv).",
    )
    ap.add_argument(
        "--json-out-pub",
        default="stats/created_by_day_pub2021_2025.json",
        help="Výstupní JSON (jen publication_date 2021–2025) (default: stats/created_by_day_pub2021_2025.json).",
    )
    ap.add_argument(
        "--png-out-pub",
        default="stats/created_calendar_pub2021_2025.png",
        help="Výstupní PNG (jen publication_date 2021–2025) (default: stats/created_calendar_pub2021_2025.png).",
    )
    # HTML výstup
    ap.add_argument(
        "--html-out",
        default="stats/created_calendar.html",
        help="Výstupní HTML stránka s kalendáři a odkazy do NMA (default: stats/created_calendar.html).",
    )
    # základní URL pro vyhledávání v NMA
    ap.add_argument(
        "--nma-search-base",
        default="https://nma.eosc.cz/datasets/",
        help="Základní URL pro vyhledávání v NMA (default: https://nma.eosc.cz/datasets/).",
    )
    return ap.parse_args()


def format_int_cz(value: int) -> str:
    """Formátuje celé číslo podle české konvence: tisíce oddělené mezerou."""
    return f"{value:,}".replace(",", " ")


# --- barevná škála pro HTML (šedá -> zelená -> růžová) ---


GREY = (0xE4, 0xE4, 0xE3)
GREEN = (0x00, 0x86, 0x91)
PINK = (0xFF, 0x5B, 0x7F)


def _blend(c1, c2, t: float):
    r = round(c1[0] + (c2[0] - c1[0]) * t)
    g = round(c1[1] + (c2[1] - c1[1]) * t)
    b = round(c1[2] + (c2[2] - c1[2]) * t)
    return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))


def color_for_value(value: int, vmin: int, vmax: int) -> str:
    """Vrátí hex barvu pro danou hodnotu podle EOSC škály."""
    if vmax <= vmin:
        return "#e4e4e3"
    norm = (value - vmin) / (vmax - vmin)
    norm = max(0.0, min(1.0, norm))
    if norm <= 0.5:
        t = norm / 0.5
        rgb = _blend(GREY, GREEN, t)
    else:
        t = (norm - 0.5) / 0.5
        rgb = _blend(GREEN, PINK, t)
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def text_color_for_rgb(rgb) -> str:
    r, g, b = [c / 255.0 for c in rgb]
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if luminance > 0.5 else "white"


def compute_scale(counts: dict[date, int], start_date: date, end_date: date, ignore_for_scale: date | None):
    values = []
    for d, v in counts.items():
        if d < start_date or d > end_date:
            continue
        if ignore_for_scale is not None and d == ignore_for_scale:
            continue
        values.append(v)
    if values:
        vmin = min(values)
        vmax = max(values)
        if vmin == vmax:
            vmax = vmin + 1
    else:
        vmin, vmax = 0, 1
    return vmin, vmax


# --- PNG kalendář pomocí matplotlib ---


def make_calendar_png(
    counts: dict[date, int],
    start_date: date,
    end_date: date,
    png_out: str,
    title: str,
    ignore_for_scale: date | None = None,
):
    # 3) Kalendářová mřížka (7 dní v týdnu, řádky = týdny)
    n_days = (end_date - start_date).days + 1
    n_rows = math.ceil(n_days / 7)

    grid = [[0 for _ in range(7)] for _ in range(n_rows)]
    date_map = [[None for _ in range(7)] for _ in range(n_rows)]

    current = start_date
    for idx in range(n_days):
        r = idx // 7
        c = idx % 7
        d = current
        grid[r][c] = counts.get(d, 0)
        date_map[r][c] = d
        current += timedelta(days=1)

    vmin, vmax = compute_scale(counts, start_date, end_date, ignore_for_scale)

    fig, ax = plt.subplots(figsize=(10, 2 + 0.6 * n_rows))

    # EOSC barevná škála: šedá -> zelená -> růžová
    eosc_cmap = LinearSegmentedColormap.from_list(
        "eosc",
        ["#e4e4e3", "#008691", "#ff5b7f"]
    )

    im = ax.imshow(grid, cmap=eosc_cmap, vmin=vmin, vmax=vmax)

    # Popisky os
    ax.set_xticks(range(7))
    ax.set_xticklabels(["Po", "Út", "St", "Čt", "Pá", "So", "Ne"])
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([f"Týden {i+1}" for i in range(n_rows)])

    # Obrátit osu y tak, aby první týden byl nahoře
    ax.set_ylim(n_rows - 0.5, -0.5)
    ax.set_xlim(-0.5, 6.5)

    ax.set_title(title)

    norm = im.norm
    cmap = im.cmap

    for r in range(n_rows):
        for c in range(7):
            d = date_map[r][c]
            if d is None:
                continue
            count = grid[r][c]

            date_label = f"{d.day}.{d.month}."
            norm_val = norm(count)
            rgba = cmap(norm_val)
            luminance = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
            text_color = "black" if luminance > 0.5 else "white"
            if norm_val > 0.66:
                text_color = "white"

            ax.text(
                c,
                r - 0.15,
                date_label,
                ha="center",
                va="center",
                fontsize=7,
                fontweight="bold",
                color=text_color,
            )
            ax.text(
                c,
                r + 0.2,
                format_int_cz(count),
                ha="center",
                va="center",
                fontsize=6,
                color=text_color,
            )

    Path(png_out).parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    fig.savefig(png_out, dpi=150)
    plt.close(fig)


# --- HTML kalendář s klikacími dny ---


def generate_html(
    counts_all: dict[date, int],
    counts_pub: dict[date, int],
    start_date: date,
    end_date: date,
    summary_from: date,
    html_out: str,
    nma_search_base: str,
    ignore_for_scale: date | None = None,
):
    """
    Vygeneruje HTML stránku se dvěma kalendáři:
    - counts_all = všechny záznamy
    - counts_pub = jen publication_date 2021–2025
    """

    def build_calendar_section(title: str, counts: dict[date, int]):
        vmin, vmax = compute_scale(counts, start_date, end_date, ignore_for_scale)

        # dny v pořadí
        days = []
        current = start_date
        while current <= end_date:
            count = counts.get(current, 0)
            color_hex = color_for_value(count, vmin, vmax)
            # textová barva
            # (přepočet hex -> RGB)
            rgb = (
                int(color_hex[1:3], 16),
                int(color_hex[3:5], 16),
                int(color_hex[5:7], 16),
            )
            text_color = text_color_for_rgb(rgb)
            # když jsme blízko horní části škály (růžové), nutný bílý text
            if vmax > vmin:
                norm = (count - vmin) / (vmax - vmin)
                if norm > 0.66:
                    text_color = "white"

            date_label = f"{current.day}.{current.month}."
            date_iso = current.isoformat()

            # odkaz do NMA: created:[YYYY-MM-DD TO YYYY-MM-DD]
            term = f"created:[{date_iso} TO {date_iso}]"
            q = quote(term, safe="")
            url = f"{nma_search_base}?q={q}"

            days.append(
                f'<a class="day" href="{url}" target="_blank" '
                f'style="background-color: {color_hex}; color: {text_color};">'
                f'<span class="date">{date_label}</span>'
                f'<span class="count">{format_int_cz(count)}</span>'
                f'</a>'
            )
            current += timedelta(days=1)

        # hlavička dnů v týdnu
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
            f'{"".join(days)}\n'
            f'  </div>\n'
            f'</section>\n'
        )

    updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

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
      --link: #008691;
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
      background: linear-gradient(to right, #e4e4e3, #008691, #ff5b7f);
      border-radius: 999px;
      border: 1px solid rgba(0,0,0,0.08);
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

    {build_calendar_section("Všechny záznamy (pole created)", counts_all)}

    {build_calendar_section("Jen záznamy s metadata.publication_date v letech 2021–2025", counts_pub)}

    <p class="meta">
      Data: JSONL sklizeň z <a href="https://nma.eosc.cz" target="_blank" rel="noopener">NMA</a>.
      Kód skriptu: <code>stats/created_calendar.py</code>.
    </p>
  </div>
</body>
</html>
"""

    Path(html_out).parent.mkdir(parents=True, exist_ok=True)
    with open(html_out, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    args = parse_args()

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    summary_from = datetime.strptime(args.summary_from, "%Y-%m-%d").date()

    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    else:
        end_date = date.today()

    if summary_from < start_date:
        raise ValueError("summary-from nesmí být dřív než start-date")

    # 1) spočítat počty podle 'created'
    counts_all: dict[date, int] = {}   # větev A: všechny záznamy
    counts_pub: dict[date, int] = {}   # větev B: jen publication_date 2021–2025

    with open_in(args.inp) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            created_str = rec.get("created")
            if not created_str:
                continue

            created_str_norm = created_str.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(created_str_norm)
            except ValueError:
                continue

            d = dt.date()
            if d < start_date or d > end_date:
                continue

            # VĚTEV A: všechny záznamy
            counts_all[d] = counts_all.get(d, 0) + 1

            # VĚTEV B: jen záznamy s metadata.publication_date roky 2021–2025
            md = rec.get("metadata") or {}
            pub_date_str = (md.get("publication_date") or "").strip()
            if pub_date_str:
                year_str = pub_date_str[:4]
                try:
                    year = int(year_str)
                except ValueError:
                    year = None
                if year is not None and 2021 <= year <= 2025:
                    counts_pub[d] = counts_pub.get(d, 0) + 1

    # doplnit nuly pro dny, kde nic nevzniklo (v obou větvích)
    current = start_date
    while current <= end_date:
        counts_all.setdefault(current, 0)
        counts_pub.setdefault(current, 0)
        current += timedelta(days=1)

    # 2) CSV + JSON výpis (jen od summary_from do end_date)

    rows_all = sorted(counts_all.items())
    rows_summary_all = [(d, c) for (d, c) in rows_all if d >= summary_from]

    rows_pub = sorted(counts_pub.items())
    rows_summary_pub = [(d, c) for (d, c) in rows_pub if d >= summary_from]

    Path(args.csv_out).parent.mkdir(parents=True, exist_ok=True)

    # CSV – větev A
    with open(args.csv_out, "w", encoding="utf-8", newline="") as f_csv:
        w = csv.writer(f_csv)
        w.writerow(["date", "created_count_all"])
        for d, c in rows_summary_all:
            w.writerow([d.isoformat(), c])

    # CSV – větev B
    with open(args.csv_out_pub, "w", encoding="utf-8", newline="") as f_csv:
        w = csv.writer(f_csv)
        w.writerow(["date", "created_count_pub2021_2025"])
        for d, c in rows_summary_pub:
            w.writerow([d.isoformat(), c])

    # JSON – větev A
    summary_dict_all = {d.isoformat(): c for d, c in rows_summary_all}
    with open(args.json_out, "w", encoding="utf-8") as f_json:
        json.dump(summary_dict_all, f_json, ensure_ascii=False, indent=2)

    # JSON – větev B
    summary_dict_pub = {d.isoformat(): c for d, c in rows_summary_pub}
    with open(args.json_out_pub, "w", encoding="utf-8") as f_json:
        json.dump(summary_dict_pub, f_json, ensure_ascii=False, indent=2)

    # rychlá kontrola do stdout
    print("=== VĚTEV A: všechny záznamy ===")
    print("date,created_count_all")
    for d, c in rows_summary_all:
        print(f"{d.isoformat()},{c}")

    print("\n=== VĚTEV B: jen publication_date 2021–2025 ===")
    print("date,created_count_pub2021_2025")
    for d, c in rows_summary_pub:
        print(f"{d.isoformat()},{c}")

    ignore_date = date(2026, 1, 16)

    # PNG kalendáře
    make_calendar_png(
        counts=counts_all,
        start_date=start_date,
        end_date=end_date,
        png_out=args.png_out,
        title="Počty záznamů podle pole 'created' (všechny záznamy)",
        ignore_for_scale=ignore_date,
    )

    make_calendar_png(
        counts=counts_pub,
        start_date=start_date,
        end_date=end_date,
        png_out=args.png_out_pub,
        title="Počty záznamů podle 'created' (publication_date 2021–2025)",
        ignore_for_scale=ignore_date,
    )

    # HTML stránka s klikacími kalendáři
    generate_html(
        counts_all=counts_all,
        counts_pub=counts_pub,
        start_date=start_date,
        end_date=end_date,
        summary_from=summary_from,
        html_out=args.html_out,
        nma_search_base=args.nma_search_base,
        ignore_for_scale=ignore_date,
    )

    print(f"\nCSV (vše):          {args.csv_out}")
    print(f"JSON (vše):         {args.json_out}")
    print(f"PNG (vše):          {args.png_out}")
    print(f"CSV (pub 21–25):    {args.csv_out_pub}")
    print(f"JSON (pub 21–25):   {args.json_out_pub}")
    print(f"PNG (pub 21–25):    {args.png_out_pub}")
    print(f"HTML kalendáře:     {args.html_out}")


if __name__ == "__main__":
    main()
