#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from reference_image_filters import ImageFilterPipeline, load_image_filter_config


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply image-level reference filters to a local directory of already-downloaded images.",
    )
    parser.add_argument("--config", required=True, help="Path to scraper JSON config with image_filter settings")
    parser.add_argument("--input-dir", required=True, help="Directory containing downloaded reference images")
    parser.add_argument("--report-dir", help="Directory for offline_kept_manifest.jsonl and offline_rejected_manifest.jsonl")
    parser.add_argument("--manifest", help="Optional existing manifest.jsonl from the original scrape for metadata merge")
    parser.add_argument("--move-rejected-to", help="Optional directory to move rejected files into, preserving relative paths")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate filters without moving files")
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        input_dir = Path(args.input_dir).resolve()
        if not input_dir.is_dir():
            print(f"error: input directory not found: {input_dir}", file=sys.stderr)
            return 1

        report_dir = Path(args.report_dir).resolve() if args.report_dir else input_dir / "_offline_filter_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        kept_manifest_path = report_dir / "offline_kept_manifest.jsonl"
        rejected_manifest_path = report_dir / "offline_rejected_manifest.jsonl"

        config_path = Path(args.config).resolve()
        filter_config = load_image_filter_config(config_path)
        pipeline = ImageFilterPipeline(filter_config, verbose=args.verbose)
        content_filter = load_content_filter_config(config_path)
        metadata_index = load_manifest_index(Path(args.manifest).resolve() if args.manifest else input_dir / "manifest.jsonl")
        move_rejected_to = Path(args.move_rejected_to).resolve() if args.move_rejected_to else None

        image_paths = list(iter_image_paths(input_dir, report_dir=report_dir, move_rejected_to=move_rejected_to))
        kept_count = 0
        rejected_count = 0

        with kept_manifest_path.open("w", encoding="utf-8") as kept_manifest, rejected_manifest_path.open(
            "w", encoding="utf-8"
        ) as rejected_manifest:
            for image_path in image_paths:
                if args.verbose:
                    print(f"scan: {image_path}", file=sys.stderr)

                content = image_path.read_bytes()
                sha256 = hashlib.sha256(content).hexdigest()
                base_record = {
                    "file_path": str(image_path),
                    "relative_path": str(image_path.relative_to(input_dir)),
                    "size_bytes": len(content),
                    "sha256": sha256,
                    "filter_diagnostics": {},
                }

                merged_record = merge_metadata(base_record, metadata_index, image_path=image_path, sha256=sha256)
                content_passed, content_diagnostics = evaluate_content_filter(
                    merged_record,
                    allow_patterns=content_filter["allow_patterns"],
                    deny_patterns=content_filter["deny_patterns"],
                )
                if not content_passed:
                    merged_record["filter_diagnostics"]["content_filter"] = content_diagnostics
                    merged_record["filter_diagnostics"]["rejected_by"] = "content_filter"
                    if move_rejected_to and not args.dry_run:
                        target = move_rejected_to / image_path.relative_to(input_dir)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(image_path), str(target))
                        merged_record["moved_to"] = str(target)
                    rejected_manifest.write(json.dumps(merged_record, ensure_ascii=False) + "\n")
                    rejected_count += 1
                    continue

                passed, diagnostics = pipeline.assess(content)
                merged_record["filter_diagnostics"].update(diagnostics)
                if passed:
                    kept_manifest.write(json.dumps(merged_record, ensure_ascii=False) + "\n")
                    kept_count += 1
                    continue

                if move_rejected_to and not args.dry_run:
                    target = move_rejected_to / image_path.relative_to(input_dir)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(image_path), str(target))
                    merged_record["moved_to"] = str(target)

                rejected_manifest.write(json.dumps(merged_record, ensure_ascii=False) + "\n")
                rejected_count += 1

        print(
            json.dumps(
                {
                    "input_dir": str(input_dir),
                    "report_dir": str(report_dir),
                    "kept_manifest": str(kept_manifest_path),
                    "rejected_manifest": str(rejected_manifest_path),
                    "images_scanned": len(image_paths),
                    "kept_count": kept_count,
                    "rejected_count": rejected_count,
                    "move_rejected_to": str(move_rejected_to) if move_rejected_to else None,
                    "dry_run": bool(args.dry_run),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def load_manifest_index(path: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return index

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            saved_path = record.get("saved_path")
            if isinstance(saved_path, str) and saved_path:
                saved = str(Path(saved_path).resolve())
                index[saved] = record
                index[Path(saved_path).name] = record

            image_url = record.get("image_url")
            if isinstance(image_url, str) and image_url:
                index[f"url:{image_url}"] = record

            sha256 = record.get("sha256")
            if isinstance(sha256, str) and sha256:
                index[f"sha:{sha256}"] = record

    return index


def load_content_filter_config(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {"allow_patterns": [], "deny_patterns": []}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return {
        "allow_patterns": [str(x) for x in payload.get("content_allow_patterns", [])],
        "deny_patterns": [str(x) for x in payload.get("content_deny_patterns", [])],
    }


def iter_image_paths(input_dir: Path, *, report_dir: Path, move_rejected_to: Path | None) -> list[Path]:
    image_paths: list[Path] = []
    excluded_roots: set[Path] = set()

    report_dir_resolved = report_dir.resolve()
    if report_dir_resolved != input_dir.resolve():
        excluded_roots.add(report_dir_resolved)

    if move_rejected_to is not None:
        move_rejected_resolved = move_rejected_to.resolve()
        if move_rejected_resolved != input_dir.resolve():
            excluded_roots.add(move_rejected_resolved)

    for path in input_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        resolved = path.resolve()
        if any(root == resolved or root in resolved.parents for root in excluded_roots):
            continue
        image_paths.append(path)
    image_paths.sort()
    return image_paths


def merge_metadata(base_record: dict[str, Any], metadata_index: dict[str, dict[str, Any]], *, image_path: Path, sha256: str) -> dict[str, Any]:
    merged = dict(base_record)
    source = metadata_index.get(str(image_path.resolve()))
    if source is None:
        source = metadata_index.get(image_path.name)
    if source is None:
        source = metadata_index.get(f"sha:{sha256}")
    if source is None:
        return merged

    for key, value in source.items():
        if key in {"saved_path", "sha256", "size_bytes"}:
            continue
        merged.setdefault(key, value)
    return merged


def evaluate_content_filter(
    record: dict[str, Any],
    *,
    allow_patterns: list[str],
    deny_patterns: list[str],
) -> tuple[bool, dict[str, Any]]:
    text = build_content_text(record)
    if deny_patterns:
        for pattern in deny_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False, {"matched_pattern": pattern, "text_excerpt": text[:240]}
    if allow_patterns and not any(re.search(pattern, text, re.IGNORECASE) for pattern in allow_patterns):
        return False, {"matched_pattern": None, "text_excerpt": text[:240]}
    return True, {}


def build_content_text(record: dict[str, Any]) -> str:
    excluded_keys = {
        "file_path",
        "saved_path",
        "moved_to",
        "sha256",
        "size_bytes",
        "filter_diagnostics",
        "content_type",
        "site_id",
        "job_name",
        "source_type",
        "access_mode",
        "source_page",
        "rights",
        "rights_url",
        "license_check_status",
        "download_policy_version",
        "download_entry_status",
        "record_type",
    }
    fragments: list[str] = []
    for key, value in record.items():
        if key in excluded_keys or value is None:
            continue
        if isinstance(value, str):
            normalized = " ".join(value.split())
            if normalized:
                fragments.append(normalized)
            continue
        if isinstance(value, list):
            normalized_items = [" ".join(str(item).split()) for item in value if str(item).strip()]
            if normalized_items:
                fragments.extend(normalized_items)
            continue
        if isinstance(value, (int, float, bool)):
            fragments.append(str(value))
    return " | ".join(fragments)


if __name__ == "__main__":
    raise SystemExit(main())
