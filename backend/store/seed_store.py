"""Read-only seed layer: pre-fetched ERA5 series for the preset places, shipped
with the deployment as gzipped JSON documents.

Why: the free Open-Meteo tier is weighted by data volume (a 75-year series costs
~200 'calls' against a 600/minute budget) and a serverless deployment shares one
outbound IP. Seeding the preset cities/states means the demo never depends on
live upstream quota; any other location is fetched on demand and cached.
Seeds are looked up only after the primary store misses and are never written to.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from .base import DocumentStore

SEEDED_COLLECTIONS = {"raw_series"}


def seed_file(root: str | Path, collection: str, doc_id: str) -> Path:
    return Path(root) / collection / (hashlib.sha1(doc_id.encode()).hexdigest()[:20] + ".json.gz")


def write_seed(root: str | Path, collection: str, doc_id: str, doc: dict[str, Any]) -> Path:
    path = seed_file(root, collection, doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(doc, fh, separators=(",", ":"))
    return path


class SeededStore:
    def __init__(self, primary: DocumentStore, seed_dir: str):
        self.primary, self.seed_dir = primary, seed_dir
        self.name = primary.name

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        doc = self.primary.get(collection, doc_id)
        if doc is not None or collection not in SEEDED_COLLECTIONS or not self.seed_dir:
            return doc
        path = seed_file(self.seed_dir, collection, doc_id)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None

    def put(self, collection: str, doc_id: str, doc: dict[str, Any], ttl_seconds: int) -> None:
        self.primary.put(collection, doc_id, doc, ttl_seconds)

    def incr(self, collection: str, doc_id: str, ttl_seconds: int) -> int:
        return self.primary.incr(collection, doc_id, ttl_seconds)
