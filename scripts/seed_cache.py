"""Pre-fetch ERA5 daily Tmax for the preset places into ./seed (gzipped JSON docs).

    python scripts/seed_cache.py            # fetch everything that is missing
    python scripts/seed_cache.py --load     # additionally load seeds into MongoDB (needs MONGODB_URI)

Paced to respect Open-Meteo's free-tier budgets (600 weighted calls/minute,
5,000/hour; one 75-year series costs ~200). On a rate-limit response it sleeps
for the advertised time and retries, so it is safe to leave running and to
re-run (cells that already exist are skipped).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import RAW_START_YEAR, get_settings, last_complete_year  # noqa: E402
from backend.store.file_store import FileStore  # noqa: E402
from backend.errors import UpstreamRateLimited, UpstreamUnavailable  # noqa: E402
from backend.service import AnalysisService, resolve_region  # noqa: E402
from backend.sources.open_meteo import OpenMeteoClient  # noqa: E402
from backend.store.seed_store import seed_file, write_seed  # noqa: E402


class MemoryStore:
    name = "memory"

    def __init__(self):
        self.docs: dict[tuple[str, str], dict] = {}

    def get(self, c, i):
        return self.docs.get((c, i))

    def put(self, c, i, doc, ttl):
        self.docs[(c, i)] = doc

    def incr(self, c, i, ttl):
        return 1


def cells() -> list[tuple[str, float, float]]:
    presets = json.loads((ROOT / "shared" / "presets.json").read_text(encoding="utf-8"))
    seen, out = set(), []
    for p in presets["cities"] + presets["states"]:
        r = resolve_region(p["lat"], p["lon"], None)
        if r.cell_id not in seen:
            seen.add(r.cell_id)
            out.append((p["name"], p["lat"], p["lon"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true", help="also upsert the seeds into MongoDB")
    ap.add_argument("--pause", type=float, default=22.0, help="seconds between fetches")
    args = ap.parse_args()

    settings = get_settings()
    seed_dir = ROOT / "seed"
    mem = MemoryStore()
    local = FileStore(settings.data_dir)
    svc = AnalysisService(mem, OpenMeteoClient(timeout=60), settings)
    todo = cells()
    print(f"{len(todo)} unique grid cells", flush=True)

    for name, lat, lon in todo:
        region = resolve_region(lat, lon, None)
        # Doc ids carry the data-through year, so build the id the same way the service does.
        doc_id = f"era5-tmax|{region.cell_id}|{RAW_START_YEAR}-{last_complete_year()}"
        path = seed_file(seed_dir, "raw_series", doc_id)
        if path.exists():
            print(f"skip   {name} (seed exists)", flush=True)
            continue
        cached = local.get("raw_series", doc_id)  # a previous dev run may already have fetched it
        if cached:
            write_seed(seed_dir, "raw_series", doc_id, cached)
            print(f"reused {name:<18} {region.cell_id} from local cache", flush=True)
            continue
        mem.docs.clear()
        for attempt in range(1, 40):
            try:
                doc, _ = svc.get_raw(region)
                break
            except UpstreamRateLimited as exc:
                wait = min(exc.retry_after or 60, 20 * 60) + 5
                print(f"  rate-limited on {name}; sleeping {wait}s (attempt {attempt})", flush=True)
                time.sleep(wait)
            except UpstreamUnavailable as exc:
                print(f"  upstream error on {name}: {exc.message}; retrying in 60s", flush=True)
                time.sleep(60)
        else:
            print(f"  giving up on {name}", flush=True)
            continue
        write_seed(seed_dir, "raw_series", doc["_id"], doc)
        print(f"seeded {name:<18} {region.cell_id}  {path.stat().st_size // 1024} KB", flush=True)
        time.sleep(args.pause)

    if args.load:
        from backend.store import build_store

        store = build_store(settings)
        n = 0
        for f in (seed_dir / "raw_series").glob("*.json.gz"):
            import gzip

            with gzip.open(f, "rt", encoding="utf-8") as fh:
                doc = json.load(fh)
            store.put("raw_series", doc["_id"], doc, settings.raw_ttl_seconds)
            n += 1
        print(f"loaded {n} seed documents into {store.name}")


if __name__ == "__main__":
    main()
