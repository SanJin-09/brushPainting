#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scrape_reference_images import Config, Scraper


@dataclass
class BatchSite:
    site_id: str
    config_path: Path
    output_subdir: str | None


@dataclass
class BatchConfig:
    batch_id: str
    download_policy_version: str
    sites: list[BatchSite]

    @classmethod
    def load(cls, path: Path) -> "BatchConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        batch_id = str(payload.get("batch_id", "")).strip()
        if not batch_id:
            raise ValueError("batch.batch_id is required")

        sites: list[BatchSite] = []
        for index, item in enumerate(payload.get("sites", [])):
            site_id = str(item.get("site_id", "")).strip()
            config_path = str(item.get("config", "")).strip()
            if not site_id or not config_path:
                raise ValueError(f"batch.sites[{index}] requires site_id and config")
            config_file = (path.parent / config_path).resolve()
            sites.append(
                BatchSite(
                    site_id=site_id,
                    config_path=config_file,
                    output_subdir=str(item.get("output_subdir", "")).strip() or None,
                )
            )
        if not sites:
            raise ValueError("batch.sites must contain at least one site")

        return cls(
            batch_id=batch_id,
            download_policy_version=str(payload.get("download_policy_version", "compliance-v1")),
            sites=sites,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multiple compliant reference scrape site configs in sequence.")
    parser.add_argument("--batch", required=True, help="Path to batch JSON config")
    parser.add_argument("--output-root", required=True, help="Root directory for per-site outputs")
    parser.add_argument("--site", action="append", help="Run only selected site_id values")
    parser.add_argument("--resume", action="store_true", help="Skip sites that already have a summary.json")
    parser.add_argument("--dry-run", action="store_true", help="Run each site without writing images")
    parser.add_argument("--verbose", action="store_true", help="Print per-site progress")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        batch_path = Path(args.batch).resolve()
        batch = BatchConfig.load(batch_path)
        output_root = Path(args.output_root).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        selected = set(args.site or [])

        site_summaries: list[dict[str, Any]] = []
        for site in batch.sites:
            if selected and site.site_id not in selected:
                continue

            site_output = output_root / (site.output_subdir or site.site_id)
            summary_path = site_output / "summary.json"
            if args.resume and summary_path.exists():
                site_summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))
                continue

            config = Config.load(site.config_path, output_override=str(site_output))
            scraper = Scraper(config, dry_run=args.dry_run, verbose=args.verbose)
            try:
                summary = scraper.run()
            finally:
                scraper.close()
            site_summaries.append(summary)

        batch_summary = {
            "batch_id": batch.batch_id,
            "download_policy_version": batch.download_policy_version,
            "output_root": str(output_root),
            "site_count": len(site_summaries),
            "sites": site_summaries,
            "downloaded": sum(int(item.get("images_saved", 0)) for item in site_summaries),
            "metadata_only": sum(int(item.get("metadata_records", 0)) for item in site_summaries),
            "skipped_for_license": sum(int(item.get("skipped_for_license", 0)) for item in site_summaries),
            "skipped_for_robots": sum(int(item.get("skipped_for_robots", 0)) for item in site_summaries),
        }
        summary_path = output_root / "batch_summary.json"
        summary_path.write_text(json.dumps(batch_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(batch_summary, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
