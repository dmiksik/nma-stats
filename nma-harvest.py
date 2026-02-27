#!/usr/bin/env python3
import argparse
import gzip
import json
import os
import random
import time
from urllib.parse import urljoin

import requests


def open_maybe_gzip(path: str, mode: str):
    if path.endswith(".gz"):
        return gzip.open(path, mode)
    return open(path, mode, encoding="utf-8")


def load_checkpoint(path: str):
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(path: str, data: dict):
    if not path:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description="Harvest all records from an InvenioRDM instance into JSONL.")
    ap.add_argument("--base-url", default="https://nma.eosc.cz/api/records",
                    help="Base endpoint for searching records (default: NMA /api/records).")
    ap.add_argument("--out", default="nma_records.jsonl.gz",
                    help="Output file (recommended .jsonl.gz).")
    ap.add_argument("--checkpoint", default="nma_checkpoint.json",
                    help="Checkpoint file for resuming.")
    ap.add_argument("--size", type=int, default=100,
                    help="Page size (InvenioRDM default 10; try 100).")
    ap.add_argument("--sort", default="oldest",
                    help='Sort: "newest", "oldest", ... (see InvenioRDM sort options).')
    ap.add_argument("--q", default="",
                    help="Optional ElasticSearch query-string filter.")
    ap.add_argument("--allversions", action="store_true",
                    help="Include all versions (otherwise only latest).")
    ap.add_argument("--min-delay", type=float, default=0.2,
                    help="Minimum delay between requests (seconds).")
    ap.add_argument("--max-delay", type=float, default=0.8,
                    help="Maximum delay between requests (seconds).")
    ap.add_argument("--max-pages", type=int, default=0,
                    help="For testing: stop after N pages (0 = no limit).")
    args = ap.parse_args()

    sess = requests.Session()
    headers = {"Accept": "application/json"}

    # Resume?
    ckpt = load_checkpoint(args.checkpoint)
    next_url = ckpt.get("next_url") if ckpt else None
    written = int(ckpt.get("written", 0)) if ckpt else 0
    pages = int(ckpt.get("pages", 0)) if ckpt else 0

    params = {
        "size": args.size,
        "sort": args.sort,
    }
    if args.q:
        params["q"] = args.q
    if args.allversions:
        params["allversions"] = 1

    with open_maybe_gzip(args.out, "at") as out_f:
        while True:
            if args.max_pages and pages >= args.max_pages:
                print(f"[stop] max-pages reached: {args.max_pages}")
                break

            try:
                if next_url:
                    r = sess.get(next_url, headers=headers, timeout=60)
                else:
                    r = sess.get(args.base_url, params=params, headers=headers, timeout=60)

                # Polite handling of rate limiting
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    sleep_s = float(retry_after) if retry_after else 10.0
                    print(f"[429] rate-limited, sleeping {sleep_s:.1f}s")
                    time.sleep(sleep_s)
                    continue

                r.raise_for_status()
                data = r.json()

                hits = (((data.get("hits") or {}).get("hits")) or [])
                if not hits:
                    print("[done] no hits returned")
                    save_checkpoint(args.checkpoint, {"next_url": None, "written": written, "pages": pages})
                    break

                for rec in hits:
                    out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()

                written += len(hits)
                pages += 1

                # Prefer API-provided pagination link
                links = data.get("links") or {}
                nxt = links.get("next")
                next_url = urljoin(r.url, nxt) if nxt else None

                save_checkpoint(args.checkpoint, {"next_url": next_url, "written": written, "pages": pages})

                total = ((data.get("hits") or {}).get("total"))
                print(f"[page {pages}] +{len(hits)} (written={written}) total={total}")

                if not next_url:
                    print("[done] no links.next -> reached last page")
                    break

                time.sleep(random.uniform(args.min_delay, args.max_delay))

            except requests.RequestException as e:
                print(f"[error] {e} (sleep 15s and retry)")
                time.sleep(15)

    print(f"[ok] output: {args.out}")
    print(f"[ok] checkpoint: {args.checkpoint}")


if __name__ == "__main__":
    main()

