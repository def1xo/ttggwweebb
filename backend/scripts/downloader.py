#!/usr/bin/env python3
"""High-volume image downloader with resume/retry support.

Usage examples:
  python backend/scripts/downloader.py \
    --input urls.txt --output-dir ./dataset/shop_vkus --workers 32

  python backend/scripts/downloader.py \
    --input items.csv --url-column image_url --supplier-column supplier \
    --output-dir ./dataset --workers 48 --timeout 25 --max-retries 5
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests


IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif"}


@dataclass
class Task:
    idx: int
    url: str
    supplier: str


@dataclass
class Result:
    idx: int
    url: str
    supplier: str
    path: str
    ok: bool
    status: str
    bytes: int
    elapsed_ms: int


def _safe_supplier_name(v: str) -> str:
    s = re.sub(r"[^0-9a-zA-Zа-яА-ЯёЁ._-]+", "_", str(v or "").strip())
    return s.strip("._-") or "unknown_supplier"


def _guess_ext(url: str, content_type: str | None) -> str:
    p = urlparse(url)
    ext = Path(p.path).suffix.lower()
    if ext in IMG_EXTS:
        return ext
    ct = str(content_type or "").lower()
    if "jpeg" in ct:
        return ".jpg"
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "gif" in ct:
        return ".gif"
    return ".jpg"


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()


def _iter_input_rows(path: Path, url_col: str, supplier_col: str | None) -> Iterable[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".lst"}:
        for line in path.read_text(encoding="utf-8").splitlines():
            u = line.strip()
            if u and u.startswith(("http://", "https://")):
                yield u, "default"
        return

    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                u = str(row.get(url_col) or "").strip()
                s = str(row.get(supplier_col) or "default").strip() if supplier_col else "default"
                if u.startswith(("http://", "https://")):
                    yield u, s
        return

    # csv fallback
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            u = str(row.get(url_col) or "").strip()
            s = str(row.get(supplier_col) or "default").strip() if supplier_col else "default"
            if u.startswith(("http://", "https://")):
                yield u, s


def download_many(
    tasks: list[Task],
    output_dir: Path,
    workers: int,
    timeout: int,
    max_retries: int,
    min_bytes: int,
) -> list[Result]:
    q: queue.Queue[Task | None] = queue.Queue(maxsize=max(1024, workers * 16))
    out: list[Result] = []
    out_lock = threading.Lock()

    session = requests.Session()
    session.headers.update({"User-Agent": "bulk-downloader/1.0"})

    def worker() -> None:
        while True:
            task = q.get()
            if task is None:
                q.task_done()
                break
            t0 = time.time()
            supplier_dir = output_dir / _safe_supplier_name(task.supplier)
            supplier_dir.mkdir(parents=True, exist_ok=True)
            stem = _url_hash(task.url)
            existing = list(supplier_dir.glob(f"{stem}.*"))
            if existing and existing[0].stat().st_size >= min_bytes:
                res = Result(task.idx, task.url, task.supplier, str(existing[0]), True, "cached", existing[0].stat().st_size, int((time.time()-t0)*1000))
                with out_lock:
                    out.append(res)
                q.task_done()
                continue

            err = "download_failed"
            saved_path = ""
            size = 0
            ok = False
            for _attempt in range(1, max_retries + 1):
                try:
                    r = session.get(task.url, timeout=timeout, stream=True)
                    r.raise_for_status()
                    ext = _guess_ext(task.url, r.headers.get("content-type"))
                    path = supplier_dir / f"{stem}{ext}"
                    tmp = supplier_dir / f"{stem}.part"
                    with tmp.open("wb") as f:
                        for chunk in r.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                f.write(chunk)
                    size = tmp.stat().st_size
                    if size < min_bytes:
                        err = f"too_small:{size}"
                        tmp.unlink(missing_ok=True)
                        continue
                    tmp.replace(path)
                    ok = True
                    saved_path = str(path)
                    err = "ok"
                    break
                except Exception as e:  # noqa: BLE001
                    err = str(e)[:200]
                    time.sleep(min(2.0, 0.2 * _attempt))

            res = Result(task.idx, task.url, task.supplier, saved_path, ok, err, size, int((time.time()-t0)*1000))
            with out_lock:
                out.append(res)
            q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, workers))]
    for t in threads:
        t.start()

    for t in tasks:
        q.put(t)
    for _ in threads:
        q.put(None)

    q.join()
    return sorted(out, key=lambda r: r.idx)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help=".txt/.csv/.jsonl with URLs")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--url-column", default="image_url")
    ap.add_argument("--supplier-column", default="supplier")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--min-bytes", type=int, default=8_000)
    ap.add_argument("--report", default="download_report.csv")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = list(_iter_input_rows(in_path, args.url_column, args.supplier_column))
    dedup = []
    seen = set()
    for url, supplier in rows:
        k = (url, supplier)
        if k in seen:
            continue
        seen.add(k)
        dedup.append((url, supplier))

    tasks = [Task(i, u, s) for i, (u, s) in enumerate(dedup)]
    print(f"tasks={len(tasks)} workers={args.workers}")
    results = download_many(tasks, out_dir, args.workers, args.timeout, args.max_retries, args.min_bytes)

    report_path = Path(args.report)
    with report_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["idx", "supplier", "url", "ok", "status", "bytes", "elapsed_ms", "path"])
        for r in results:
            w.writerow([r.idx, r.supplier, r.url, int(r.ok), r.status, r.bytes, r.elapsed_ms, r.path])

    ok = sum(1 for r in results if r.ok)
    print(f"done ok={ok} fail={len(results)-ok} report={report_path}")
    return 0 if ok > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
