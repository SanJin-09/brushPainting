#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

try:
    import httpx
except ImportError as exc:  # pragma: no cover - import guard
    print(
        "error: missing dependency 'httpx'. Install it with "
        "`pip install httpx` or `pip install -r requirements-dev.txt`.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

from reference_image_filters import ImageFilterConfig, ImageFilterPipeline


DEFAULT_HEADERS = {
    "User-Agent": "brushPainting-reference-collector/1.0 (+manual review)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

IMAGE_ATTR_CANDIDATES = [
    "src",
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-url",
    "data-image",
    "data-full",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
API_JOB_MODES = {"json_records", "json_values_to_detail"}
ACCESS_MODES = {"download", "metadata_only"}
SOURCE_TYPES = {"api", "iiif", "html"}
DOWNLOAD_POLICY_VERSION = "compliance-v1"


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.images: list[str] = []
        self.meta_values: dict[str, list[str]] = {}
        self.page_title_fragments: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value for key, value in attrs if value}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
            return

        if tag == "meta":
            content = attr_map.get("content")
            name = attr_map.get("name") or attr_map.get("property") or attr_map.get("itemprop") or attr_map.get("http-equiv")
            if content and name:
                self._add_meta_value(name, content)
            return

        if tag == "link":
            href = attr_map.get("href")
            rel = attr_map.get("rel", "").lower()
            if href and "canonical" in rel:
                self._add_meta_value("__canonical_url__", href)
            if href and "license" in rel:
                self._add_meta_value("__license_href__", href)
            if href and "alternate" in rel:
                self.links.append(href)
            return

        if tag == "a":
            href = attr_map.get("href")
            if href:
                self.links.append(href)
            return

        if tag in {"img", "source"}:
            for name in IMAGE_ATTR_CANDIDATES:
                value = attr_map.get(name)
                if value:
                    self.images.append(value)
            srcset = attr_map.get("srcset")
            if srcset:
                self.images.extend(_parse_srcset(srcset))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.page_title_fragments.append(data.strip())

    @property
    def page_title(self) -> str:
        return _normalize_whitespace(" ".join(self.page_title_fragments))

    def _add_meta_value(self, key: str, value: str) -> None:
        normalized_key = key.strip().lower()
        normalized_value = _normalize_whitespace(value)
        if not normalized_key or not normalized_value:
            return
        bucket = self.meta_values.setdefault(normalized_key, [])
        if normalized_value not in bucket:
            bucket.append(normalized_value)


@dataclass
class ApiJob:
    name: str
    mode: str
    start_url: str
    list_path: str
    page_fields: list[str]
    image_fields: list[str]
    record_text_fields: list[str]
    record_allow_patterns: list[str]
    record_deny_patterns: list[str]
    metadata_fields: dict[str, list[str]]
    license_text_fields: list[str]
    detail_url_template: str | None
    detail_page_fields: list[str]
    detail_image_fields: list[str]
    detail_record_text_fields: list[str]
    detail_record_allow_patterns: list[str]
    detail_record_deny_patterns: list[str]
    detail_metadata_fields: dict[str, list[str]]
    detail_license_text_fields: list[str]
    query_params: dict[str, str]
    pagination_param: str | None
    pagination_start: int
    pagination_step: int
    max_requests: int

    @classmethod
    def load_many(cls, payloads: list[dict[str, Any]]) -> list["ApiJob"]:
        jobs: list[ApiJob] = []
        for index, payload in enumerate(payloads):
            mode = str(payload.get("mode", "json_records"))
            if mode not in API_JOB_MODES:
                raise ValueError(f"jobs[{index}].mode must be one of {sorted(API_JOB_MODES)}")

            start_url = str(payload.get("start_url", "")).strip()
            if not start_url:
                raise ValueError(f"jobs[{index}].start_url is required")

            list_path = str(payload.get("list_path", "")).strip()
            if not list_path:
                raise ValueError(f"jobs[{index}].list_path is required")

            detail_url_template = payload.get("detail_url_template")
            if mode == "json_values_to_detail" and not str(detail_url_template or "").strip():
                raise ValueError(f"jobs[{index}].detail_url_template is required for json_values_to_detail")

            jobs.append(
                cls(
                    name=str(payload.get("name") or f"job_{index + 1}"),
                    mode=mode,
                    start_url=start_url,
                    list_path=list_path,
                    page_fields=[str(x) for x in payload.get("page_fields", [])],
                    image_fields=[str(x) for x in payload.get("image_fields", [])],
                    record_text_fields=[str(x) for x in payload.get("record_text_fields", [])],
                    record_allow_patterns=[str(x) for x in payload.get("record_allow_patterns", [])],
                    record_deny_patterns=[str(x) for x in payload.get("record_deny_patterns", [])],
                    metadata_fields=_load_field_map(payload.get("metadata_fields", {})),
                    license_text_fields=[str(x) for x in payload.get("license_text_fields", [])],
                    detail_url_template=str(detail_url_template).strip() if detail_url_template else None,
                    detail_page_fields=[str(x) for x in payload.get("detail_page_fields", [])],
                    detail_image_fields=[str(x) for x in payload.get("detail_image_fields", [])],
                    detail_record_text_fields=[str(x) for x in payload.get("detail_record_text_fields", [])],
                    detail_record_allow_patterns=[str(x) for x in payload.get("detail_record_allow_patterns", [])],
                    detail_record_deny_patterns=[str(x) for x in payload.get("detail_record_deny_patterns", [])],
                    detail_metadata_fields=_load_field_map(payload.get("detail_metadata_fields", {})),
                    detail_license_text_fields=[str(x) for x in payload.get("detail_license_text_fields", [])],
                    query_params={str(k): str(v) for k, v in payload.get("query_params", {}).items()},
                    pagination_param=str(payload.get("pagination_param")).strip() if payload.get("pagination_param") else None,
                    pagination_start=int(payload.get("pagination_start", 0)),
                    pagination_step=int(payload.get("pagination_step", 1)),
                    max_requests=max(1, int(payload.get("max_requests", 1))),
                )
            )
        return jobs


@dataclass
class Config:
    site_id: str
    access_mode: str
    source_type: str
    start_urls: list[str]
    allowed_domains: set[str]
    output_dir: Path
    request_delay_seconds: float
    timeout_seconds: float
    max_pages: int
    max_images: int
    min_image_bytes: int
    respect_robots_txt: bool
    page_url_allow_patterns: list[str]
    page_url_deny_patterns: list[str]
    content_allow_patterns: list[str]
    content_deny_patterns: list[str]
    image_url_allow_patterns: list[str]
    image_url_deny_patterns: list[str]
    headers: dict[str, str]
    api_jobs: list[ApiJob]
    image_filter: ImageFilterConfig
    requires_open_license: bool
    license_allow_patterns: list[str]
    license_deny_patterns: list[str]
    max_requests_per_minute: int
    download_policy_version: str
    follow_page_links: bool
    html_record_allow_patterns: list[str]
    html_metadata_fields: dict[str, list[str]]
    html_regex_fields: dict[str, list[str]]
    html_download_link_patterns: list[str]

    @classmethod
    def load(cls, path: Path, *, output_override: str | None = None) -> "Config":
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        site_id = str(payload.get("site_id", "")).strip()
        if not site_id:
            raise ValueError("config.site_id is required")

        access_mode = str(payload.get("access_mode", "")).strip()
        if access_mode not in ACCESS_MODES:
            raise ValueError(f"config.access_mode must be one of {sorted(ACCESS_MODES)}")

        source_type = str(payload.get("source_type", "")).strip()
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"config.source_type must be one of {sorted(SOURCE_TYPES)}")

        if payload.get("respect_robots_txt", True) is not True:
            raise ValueError("config.respect_robots_txt must be true in compliance mode")

        jobs_payload = payload.get("download_jobs") if access_mode == "download" else payload.get("discovery_jobs")
        if jobs_payload is None:
            jobs_payload = payload.get("api_jobs", [])
        api_jobs = ApiJob.load_many(jobs_payload)

        start_urls = [str(url).strip() for url in payload.get("start_urls", []) if str(url).strip()]
        if not start_urls and not api_jobs:
            raise ValueError("config.start_urls is required unless download_jobs/discovery_jobs is set")

        allowed_domains = {
            _normalize_domain(domain)
            for domain in payload.get("allowed_domains", [])
            if str(domain).strip()
        }
        if not allowed_domains:
            seeds = start_urls + [job.start_url for job in api_jobs]
            allowed_domains = {_normalize_domain(urlparse(url).netloc) for url in seeds}

        output_dir = Path(output_override or payload.get("output_dir") or f"runtime/reference_scrape/{site_id}").resolve()
        headers = dict(DEFAULT_HEADERS)
        headers.update({str(k): str(v) for k, v in payload.get("headers", {}).items()})
        image_filter = ImageFilterConfig.load(payload.get("image_filter", {}))

        requires_open_license = bool(payload.get("requires_open_license", access_mode == "download"))
        license_allow_patterns = [str(x) for x in payload.get("license_allow_patterns", [])]
        if access_mode == "download" and requires_open_license and not license_allow_patterns:
            raise ValueError("download mode with requires_open_license=true must define license_allow_patterns")

        max_requests_per_minute = max(1, int(payload.get("max_requests_per_minute", 30)))
        configured_delay = float(payload.get("request_delay_seconds", 0))
        effective_delay = max(configured_delay, 60.0 / max_requests_per_minute)

        max_images = int(payload.get("max_images", 500))
        if access_mode == "download" and max_images <= 0:
            raise ValueError("download mode requires config.max_images > 0")

        return cls(
            site_id=site_id,
            access_mode=access_mode,
            source_type=source_type,
            start_urls=start_urls,
            allowed_domains=allowed_domains,
            output_dir=output_dir,
            request_delay_seconds=effective_delay,
            timeout_seconds=float(payload.get("timeout_seconds", 20)),
            max_pages=int(payload.get("max_pages", 200)),
            max_images=max_images,
            min_image_bytes=int(payload.get("min_image_bytes", 50_000)),
            respect_robots_txt=True,
            page_url_allow_patterns=[str(x) for x in payload.get("page_url_allow_patterns", [])],
            page_url_deny_patterns=[str(x) for x in payload.get("page_url_deny_patterns", [])],
            content_allow_patterns=[str(x) for x in payload.get("content_allow_patterns", [])],
            content_deny_patterns=[str(x) for x in payload.get("content_deny_patterns", [])],
            image_url_allow_patterns=[str(x) for x in payload.get("image_url_allow_patterns", [])],
            image_url_deny_patterns=[str(x) for x in payload.get("image_url_deny_patterns", [])],
            headers=headers,
            api_jobs=api_jobs,
            image_filter=image_filter,
            requires_open_license=requires_open_license,
            license_allow_patterns=license_allow_patterns,
            license_deny_patterns=[str(x) for x in payload.get("license_deny_patterns", [])],
            max_requests_per_minute=max_requests_per_minute,
            download_policy_version=str(payload.get("download_policy_version", DOWNLOAD_POLICY_VERSION)),
            follow_page_links=bool(payload.get("follow_page_links", False)),
            html_record_allow_patterns=[str(x) for x in payload.get("html_record_allow_patterns", [])],
            html_metadata_fields=_load_field_map(payload.get("html_metadata_fields", {})),
            html_regex_fields=_load_field_map(payload.get("html_regex_fields", {})),
            html_download_link_patterns=[str(x) for x in payload.get("html_download_link_patterns", [])],
        )


class Scraper:
    def __init__(self, config: Config, *, dry_run: bool = False, verbose: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self.verbose = verbose
        self.visited_pages: set[str] = set()
        self.queued_pages: set[str] = set()
        self.page_queue: list[str] = []
        self.seen_image_urls: set[str] = set()
        self.seen_hashes: set[str] = set()
        self.robot_cache: dict[str, RobotFileParser] = {}
        self.manifest_path = self.config.output_dir / "manifest.jsonl"
        self.rejected_manifest_path = self.config.output_dir / "rejected_manifest.jsonl"
        self.summary_path = self.config.output_dir / "summary.json"
        self.image_filter = ImageFilterPipeline(self.config.image_filter, verbose=verbose)
        self.session = httpx.Client(
            follow_redirects=True,
            timeout=self.config.timeout_seconds,
            headers=self.config.headers,
        )
        self.stats = {
            "pages_processed": 0,
            "images_saved": 0,
            "metadata_records": 0,
            "skipped_for_license": 0,
            "skipped_for_robots": 0,
            "skipped_for_filter": 0,
            "skipped_for_missing_download_entry": 0,
        }

    def close(self) -> None:
        self.session.close()

    def run(self) -> dict[str, Any]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        for url in self.config.start_urls:
            self._enqueue_page(url)

        with self.manifest_path.open("a", encoding="utf-8") as manifest:
            self._run_api_jobs(manifest)

            while (
                self.page_queue
                and self.stats["pages_processed"] < self.config.max_pages
                and self._has_image_capacity()
            ):
                page_url = self.page_queue.pop(0)
                self.queued_pages.discard(page_url)

                if page_url in self.visited_pages:
                    continue
                if not self._is_allowed_url(
                    page_url,
                    allow_patterns=self.config.page_url_allow_patterns,
                    deny_patterns=self.config.page_url_deny_patterns,
                ):
                    continue
                if not self._can_fetch(page_url):
                    self.stats["skipped_for_robots"] += 1
                    self._append_rejected_record(
                        {
                            "site_id": self.config.site_id,
                            "access_mode": self.config.access_mode,
                            "source_type": "html",
                            "source_page": page_url,
                            "object_url": page_url,
                            "rejected_reason": "robots_disallow",
                            "download_policy_version": self.config.download_policy_version,
                        }
                    )
                    self._log(f"skip robots.txt disallow: {page_url}")
                    continue

                self.visited_pages.add(page_url)
                self.stats["pages_processed"] += 1
                self._log(f"page {self.stats['pages_processed']}: {page_url}")

                try:
                    response = self.session.get(page_url)
                    response.raise_for_status()
                except Exception as exc:
                    self._append_rejected_record(
                        {
                            "site_id": self.config.site_id,
                            "access_mode": self.config.access_mode,
                            "source_type": "html",
                            "source_page": page_url,
                            "object_url": page_url,
                            "rejected_reason": "page_fetch_failed",
                            "error": str(exc),
                            "download_policy_version": self.config.download_policy_version,
                        }
                    )
                    self._log(f"page fetch failed: {page_url} ({exc})")
                    time.sleep(self.config.request_delay_seconds)
                    continue

                content_type = response.headers.get("content-type", "")
                if content_type.startswith("image/") and self.config.access_mode == "download":
                    if self._save_image_from_response(
                        response,
                        source_page=page_url,
                        image_url=page_url,
                        manifest=manifest,
                        extra_fields=self._build_audit_fields(
                            metadata={"object_url": page_url},
                            job_name="start_url",
                            source_page=page_url,
                            source_type="html",
                            license_status="not_checked_direct_image",
                            download_entry_status="direct_image",
                        ),
                    ):
                        self.stats["images_saved"] += 1
                    time.sleep(self.config.request_delay_seconds)
                    continue

                if "json" in content_type:
                    self._log(f"skip unexpected json page: {page_url}")
                    time.sleep(self.config.request_delay_seconds)
                    continue

                parser = LinkCollector()
                parser.feed(response.text)
                html_metadata = self._extract_html_metadata(page_url, response.text, parser)
                html_filter_text = self._build_html_filter_text(page_url, response.text, html_metadata)

                if not _record_matches(
                    html_filter_text,
                    allow_patterns=self.config.content_allow_patterns,
                    deny_patterns=self.config.content_deny_patterns,
                ):
                    self._append_rejected_record(
                        {
                            **self._build_audit_fields(
                                metadata=html_metadata,
                                job_name="html_page_filter",
                                source_page=page_url,
                                source_type="html",
                                license_status="not_checked_page_filtered",
                                download_entry_status=str(html_metadata.get("download_entry_status") or "not_checked"),
                            ),
                            "rejected_reason": "page_content_filter",
                        }
                    )
                    time.sleep(self.config.request_delay_seconds)
                    continue

                if self.config.access_mode == "metadata_only" and self._should_record_html_page(page_url):
                    self._write_metadata_record(
                        manifest=manifest,
                        metadata=html_metadata,
                        job_name="html_discovery",
                        source_page=page_url,
                        source_type="html",
                        license_status="not_checked_metadata_only",
                    )

                if self.config.access_mode == "download":
                    self.stats["images_saved"] += self._download_images_from_html_page(
                        page_url=page_url,
                        raw_html=response.text,
                        parser=parser,
                        html_metadata=html_metadata,
                        manifest=manifest,
                    )

                if self.config.follow_page_links:
                    for href in parser.links:
                        normalized = self._normalize_url(page_url, href)
                        if not normalized:
                            continue
                        if not self._is_allowed_url(
                            normalized,
                            allow_patterns=self.config.page_url_allow_patterns,
                            deny_patterns=self.config.page_url_deny_patterns,
                        ):
                            continue
                        self._enqueue_page(normalized)

                time.sleep(self.config.request_delay_seconds)

        summary = {
            "site_id": self.config.site_id,
            "access_mode": self.config.access_mode,
            "source_type": self.config.source_type,
            "output_dir": str(self.config.output_dir),
            "manifest": str(self.manifest_path),
            "rejected_manifest": str(self.rejected_manifest_path),
            "download_policy_version": self.config.download_policy_version,
            **self.stats,
        }
        if not self.dry_run:
            self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return summary

    def _run_api_jobs(self, manifest) -> None:
        for job in self.config.api_jobs:
            if not self._has_image_capacity():
                break
            self._log(f"api job: {job.name}")
            self._run_api_job(job, manifest)

    def _run_api_job(self, job: ApiJob, manifest) -> None:
        for index in range(job.max_requests):
            if not self._has_image_capacity():
                break

            params = dict(job.query_params)
            if job.pagination_param:
                params[job.pagination_param] = str(job.pagination_start + index * job.pagination_step)

            payload = self._fetch_json(job.start_url, params=params)
            if payload is None:
                time.sleep(self.config.request_delay_seconds)
                continue

            records = _extract_json_path(payload, job.list_path)
            if not records:
                self._log(f"api job empty: {job.name}")
                break

            if job.mode == "json_records":
                for record in records:
                    if not self._has_image_capacity():
                        break
                    self._process_json_record(
                        record,
                        job=job,
                        detail=False,
                        base_url=job.start_url,
                        source_page=job.start_url,
                        manifest=manifest,
                    )
                    time.sleep(self.config.request_delay_seconds)
                continue

            for value in records:
                if not self._has_image_capacity():
                    break
                detail_url = str(job.detail_url_template).format(value=value)
                detail_payload = self._fetch_json(detail_url)
                if detail_payload is None:
                    time.sleep(self.config.request_delay_seconds)
                    continue
                self._process_json_record(
                    detail_payload,
                    job=job,
                    detail=True,
                    base_url=detail_url,
                    source_page=detail_url,
                    manifest=manifest,
                )
                time.sleep(self.config.request_delay_seconds)

    def _fetch_json(self, url: str, *, params: dict[str, str] | None = None) -> Any | None:
        if not self._is_allowed_url(url, allow_patterns=[], deny_patterns=[]):
            self._log(f"skip disallowed api url: {url}")
            return None
        if not self._can_fetch(url):
            self.stats["skipped_for_robots"] += 1
            self._append_rejected_record(
                {
                    "site_id": self.config.site_id,
                    "access_mode": self.config.access_mode,
                    "source_type": "api",
                    "source_page": url,
                    "object_url": url,
                    "rejected_reason": "robots_disallow",
                    "download_policy_version": self.config.download_policy_version,
                }
            )
            self._log(f"skip robots.txt disallow: {url}")
            return None

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            self._append_rejected_record(
                {
                    "site_id": self.config.site_id,
                    "access_mode": self.config.access_mode,
                    "source_type": "api",
                    "source_page": url,
                    "object_url": url,
                    "rejected_reason": "api_fetch_failed",
                    "error": str(exc),
                    "download_policy_version": self.config.download_policy_version,
                }
            )
            self._log(f"api fetch failed: {url} ({exc})")
            return None

    def _process_json_record(
        self,
        record: Any,
        *,
        job: ApiJob,
        detail: bool,
        base_url: str,
        source_page: str,
        manifest,
    ) -> None:
        record_text_fields = job.detail_record_text_fields if detail else job.record_text_fields
        record_allow_patterns = job.detail_record_allow_patterns if detail else job.record_allow_patterns
        record_deny_patterns = job.detail_record_deny_patterns if detail else job.record_deny_patterns
        page_fields = job.detail_page_fields if detail else job.page_fields
        image_fields = job.detail_image_fields if detail else job.image_fields
        metadata_fields = job.detail_metadata_fields if detail else job.metadata_fields
        license_text_fields = job.detail_license_text_fields if detail else job.license_text_fields

        record_text = _build_record_text(record, record_text_fields)
        if not _record_matches(record_text, allow_patterns=record_allow_patterns, deny_patterns=record_deny_patterns):
            if self.verbose and record_text:
                self._log(f"skip filtered record: {record_text[:160]}")
            return

        metadata = _extract_record_metadata(record, metadata_fields)
        metadata.setdefault("object_url", source_page)
        metadata["priority_tags"] = _derive_priority_tags(" | ".join(str(value) for value in metadata.values() if value))

        for field in page_fields:
            for value in _extract_json_path(record, field):
                normalized = self._normalize_url(base_url, str(value))
                if not normalized:
                    continue
                self._enqueue_page(normalized)

        if self.config.access_mode == "metadata_only":
            self._write_metadata_record(
                manifest=manifest,
                metadata=metadata,
                job_name=job.name,
                source_page=source_page,
                source_type="api",
                license_status="not_checked_metadata_only",
            )
            return

        if not image_fields:
            return

        license_status = self._evaluate_license(
            license_text=self._build_license_text(record, metadata, license_text_fields),
            source_page=source_page,
            metadata=metadata,
            source_type="api",
        )
        if not license_status["allowed"]:
            self.stats["skipped_for_license"] += 1
            self._append_rejected_record(
                {
                    **self._build_audit_fields(
                        metadata=metadata,
                        job_name=job.name,
                        source_page=source_page,
                        source_type="api",
                        license_status=license_status["status"],
                        download_entry_status="api_image_field",
                    ),
                    "rejected_reason": "license",
                }
            )
            return

        extra_fields = self._build_audit_fields(
            metadata=metadata,
            job_name=job.name,
            source_page=source_page,
            source_type="api",
            license_status=license_status["status"],
            download_entry_status="api_image_field",
        )
        for field in image_fields:
            for value in _extract_json_path(record, field):
                if not self._has_image_capacity():
                    return
                if self._download_image_if_allowed(str(value), source_page=source_page, manifest=manifest, extra_fields=extra_fields):
                    self.stats["images_saved"] += 1

    def _download_images_from_html_page(self, *, page_url: str, raw_html: str, parser: LinkCollector, html_metadata: dict[str, Any], manifest) -> int:
        license_status = self._evaluate_license(
            license_text=self._build_html_license_text(raw_html, html_metadata),
            source_page=page_url,
            metadata=html_metadata,
            source_type="html",
        )
        download_candidates = self._collect_html_download_candidates(page_url, parser)
        download_entry_status = "available" if download_candidates else html_metadata.get("download_entry_status", "not_found")

        if not license_status["allowed"]:
            self.stats["skipped_for_license"] += 1
            self._append_rejected_record(
                {
                    **self._build_audit_fields(
                        metadata=html_metadata,
                        job_name="html_download",
                        source_page=page_url,
                        source_type="html",
                        license_status=license_status["status"],
                        download_entry_status=download_entry_status,
                    ),
                    "rejected_reason": "license",
                }
            )
            return 0

        if not download_candidates:
            self.stats["skipped_for_missing_download_entry"] += 1
            self._append_rejected_record(
                {
                    **self._build_audit_fields(
                        metadata=html_metadata,
                        job_name="html_download",
                        source_page=page_url,
                        source_type="html",
                        license_status=license_status["status"],
                        download_entry_status=download_entry_status,
                    ),
                    "rejected_reason": "missing_download_entry",
                }
            )
            return 0

        saved = 0
        extra_fields = self._build_audit_fields(
            metadata=html_metadata,
            job_name="html_download",
            source_page=page_url,
            source_type="html",
            license_status=license_status["status"],
            download_entry_status=download_entry_status,
        )
        for candidate in download_candidates:
            if not self._has_image_capacity(additional=saved):
                break
            if self._download_image_if_allowed(candidate, source_page=page_url, manifest=manifest, extra_fields=extra_fields):
                saved += 1
        return saved

    def _has_image_capacity(self, *, additional: int = 0) -> bool:
        if self.config.access_mode != "download":
            return True
        return self.stats["images_saved"] + additional < self.config.max_images

    def _write_metadata_record(
        self,
        *,
        manifest,
        metadata: dict[str, Any],
        job_name: str,
        source_page: str,
        source_type: str,
        license_status: str,
    ) -> None:
        record = {
            **self._build_audit_fields(
                metadata=metadata,
                job_name=job_name,
                source_page=source_page,
                source_type=source_type,
                license_status=license_status,
                download_entry_status=str(metadata.get("download_entry_status") or "not_applicable"),
            ),
            "record_type": "metadata_only",
        }
        manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
        manifest.flush()
        self.stats["metadata_records"] += 1
        self._log(f"metadata: {record.get('object_url') or source_page}")

    def _extract_html_metadata(self, page_url: str, raw_html: str, parser: LinkCollector) -> dict[str, Any]:
        body_text = _html_to_text(raw_html)
        metadata: dict[str, Any] = {}
        for field, candidates in self.config.html_metadata_fields.items():
            value = _resolve_html_field(
                candidates,
                parser=parser,
                page_url=page_url,
                body_text=body_text,
            )
            if value:
                metadata[field] = value

        for field, patterns in self.config.html_regex_fields.items():
            if metadata.get(field):
                continue
            for pattern in patterns:
                match = re.search(pattern, body_text, re.IGNORECASE)
                if not match:
                    continue
                captured = match.group(1) if match.groups() else match.group(0)
                normalized = _normalize_whitespace(captured)
                if normalized:
                    metadata[field] = normalized
                    break

        metadata.setdefault("title", parser.page_title)
        metadata.setdefault("object_url", _first_non_empty(parser.meta_values.get("__canonical_url__", [])) or page_url)
        metadata.setdefault("rights_url", _first_non_empty(parser.meta_values.get("__license_href__", [])))
        metadata.setdefault("download_entry_status", self._infer_download_entry_status(parser, page_url))
        metadata["priority_tags"] = _derive_priority_tags(" | ".join(str(value) for value in metadata.values() if value))
        return {key: value for key, value in metadata.items() if value not in (None, "", [])}

    def _build_html_filter_text(self, page_url: str, raw_html: str, metadata: dict[str, Any]) -> str:
        fragments: list[str] = [page_url, _html_to_text(raw_html)]
        for key in ("title", "artist", "catalog_number", "rights", "object_url"):
            value = metadata.get(key)
            if value:
                fragments.append(str(value))
        priority_tags = metadata.get("priority_tags")
        if isinstance(priority_tags, list):
            fragments.extend(str(tag) for tag in priority_tags if tag)
        return " | ".join(fragment for fragment in fragments if fragment)

    def _infer_download_entry_status(self, parser: LinkCollector, page_url: str) -> str:
        if self._collect_html_download_candidates(page_url, parser):
            return "available"
        if parser.images:
            return "page_image_only"
        return "not_found"

    def _collect_html_download_candidates(self, page_url: str, parser: LinkCollector) -> list[str]:
        candidates: list[str] = []
        for href in parser.links:
            normalized = self._normalize_url(page_url, href)
            if not normalized:
                continue
            if self.config.html_download_link_patterns and any(
                re.search(pattern, normalized, re.IGNORECASE) for pattern in self.config.html_download_link_patterns
            ):
                candidates.append(normalized)

        if candidates:
            return _unique(candidates)

        for image_url in parser.images:
            normalized = self._normalize_url(page_url, image_url)
            if not normalized:
                continue
            candidates.append(normalized)
        return _unique(candidates)

    def _should_record_html_page(self, page_url: str) -> bool:
        if not self.config.html_record_allow_patterns:
            return True
        return any(re.search(pattern, page_url, re.IGNORECASE) for pattern in self.config.html_record_allow_patterns)

    def _build_license_text(self, record: Any, metadata: dict[str, Any], fields: list[str]) -> str:
        fragments: list[str] = []
        if fields:
            fragments.append(_build_record_text(record, fields))
        for key in ("rights", "rights_url"):
            value = metadata.get(key)
            if value:
                fragments.append(str(value))
        return " | ".join(fragment for fragment in fragments if fragment)

    def _build_html_license_text(self, raw_html: str, metadata: dict[str, Any]) -> str:
        fragments = [_html_to_text(raw_html)]
        for key in ("rights", "rights_url"):
            value = metadata.get(key)
            if value:
                fragments.append(str(value))
        return " | ".join(fragment for fragment in fragments if fragment)

    def _evaluate_license(
        self,
        *,
        license_text: str,
        source_page: str,
        metadata: dict[str, Any],
        source_type: str,
    ) -> dict[str, Any]:
        if self.config.access_mode != "download":
            return {"allowed": True, "status": "not_required_metadata_only"}
        if not self.config.requires_open_license:
            return {"allowed": True, "status": "not_required"}

        if self.config.license_deny_patterns and any(
            re.search(pattern, license_text, re.IGNORECASE) for pattern in self.config.license_deny_patterns
        ):
            return {"allowed": False, "status": "denied_by_license_pattern"}

        if self.config.license_allow_patterns and any(
            re.search(pattern, license_text, re.IGNORECASE) for pattern in self.config.license_allow_patterns
        ):
            return {"allowed": True, "status": "matched_open_license"}

        self._log(f"skip missing explicit open license: {source_page}")
        return {"allowed": False, "status": "missing_open_license"}

    def _build_audit_fields(
        self,
        *,
        metadata: dict[str, Any],
        job_name: str,
        source_page: str,
        source_type: str,
        license_status: str,
        download_entry_status: str,
    ) -> dict[str, Any]:
        audit = {
            "site_id": self.config.site_id,
            "job_name": job_name,
            "source_type": source_type,
            "access_mode": self.config.access_mode,
            "source_page": source_page,
            "object_url": metadata.get("object_url") or source_page,
            "rights": metadata.get("rights"),
            "rights_url": metadata.get("rights_url"),
            "license_check_status": license_status,
            "download_policy_version": self.config.download_policy_version,
            "download_entry_status": download_entry_status,
        }
        for key, value in metadata.items():
            if key in audit:
                continue
            audit[key] = value
        if "priority_tags" not in audit:
            audit["priority_tags"] = _derive_priority_tags(" | ".join(str(value) for value in metadata.values() if value))
        return audit

    def _enqueue_page(self, page_url: str) -> None:
        normalized = self._normalize_url(page_url, page_url)
        if not normalized:
            return
        if normalized in self.visited_pages or normalized in self.queued_pages:
            return
        self.page_queue.append(normalized)
        self.queued_pages.add(normalized)

    def _download_image_if_allowed(
        self,
        image_url: str,
        *,
        source_page: str,
        manifest,
        extra_fields: dict[str, Any],
        require_image_hint: bool = False,
    ) -> bool:
        normalized = self._normalize_url(source_page, image_url)
        if not normalized or normalized in self.seen_image_urls:
            return False
        if not self._is_allowed_url(
            normalized,
            allow_patterns=self.config.image_url_allow_patterns,
            deny_patterns=self.config.image_url_deny_patterns,
            require_image_hint=require_image_hint,
        ):
            return False
        if not self._can_fetch(normalized):
            self.stats["skipped_for_robots"] += 1
            self._append_rejected_record(
                {
                    **extra_fields,
                    "image_url": normalized,
                    "rejected_reason": "robots_disallow",
                }
            )
            return False

        self.seen_image_urls.add(normalized)
        return self._download_image(normalized, source_page, manifest, extra_fields=extra_fields)

    def _download_image(self, image_url: str, source_page: str, manifest, *, extra_fields: dict[str, Any]) -> bool:
        try:
            response = self.session.get(image_url)
            response.raise_for_status()
        except Exception as exc:
            self._append_rejected_record(
                {
                    **extra_fields,
                    "image_url": image_url,
                    "rejected_reason": "image_fetch_failed",
                    "error": str(exc),
                }
            )
            self._log(f"image fetch failed: {image_url} ({exc})")
            return False
        return self._save_image_from_response(
            response,
            source_page=source_page,
            image_url=image_url,
            manifest=manifest,
            extra_fields=extra_fields,
        )

    def _save_image_from_response(
        self,
        response: httpx.Response,
        *,
        source_page: str,
        image_url: str,
        manifest,
        extra_fields: dict[str, Any],
    ) -> bool:
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            self._append_rejected_record(
                {
                    **extra_fields,
                    "image_url": image_url,
                    "source_page": source_page,
                    "content_type": content_type,
                    "rejected_reason": "non_image_response",
                }
            )
            self._log(f"skip non-image: {image_url} ({content_type or 'unknown'})")
            return False
        content = response.content
        if len(content) < self.config.min_image_bytes:
            self._append_rejected_record(
                {
                    **extra_fields,
                    "image_url": image_url,
                    "source_page": source_page,
                    "content_type": content_type,
                    "size_bytes": len(content),
                    "rejected_reason": "tiny_image",
                }
            )
            self._log(f"skip tiny image: {image_url} ({len(content)} bytes)")
            return False

        passed_filter, filter_diagnostics = self.image_filter.assess(content)
        if not passed_filter:
            self.stats["skipped_for_filter"] += 1
            self._append_rejected_record(
                {
                    **extra_fields,
                    "image_url": image_url,
                    "source_page": source_page,
                    "content_type": content_type,
                    "size_bytes": len(content),
                    "filter_diagnostics": filter_diagnostics,
                    "rejected_reason": "image_filter",
                }
            )
            self._log(f"skip image filter: {image_url} ({filter_diagnostics.get('rejected_by', 'unknown')})")
            return False

        digest = hashlib.sha256(content).hexdigest()
        if digest in self.seen_hashes:
            self._log(f"skip duplicate hash: {image_url}")
            return False

        self.seen_hashes.add(digest)
        extension = _guess_extension(image_url, content_type)
        filename = _build_filename(image_url, digest, extension)
        target = self.config.output_dir / filename

        if not self.dry_run:
            target.write_bytes(content)

        record = {
            **extra_fields,
            "record_type": "downloaded_image",
            "image_url": image_url,
            "source_page": source_page,
            "saved_path": str(target),
            "content_type": content_type,
            "size_bytes": len(content),
            "sha256": digest,
            "filter_diagnostics": filter_diagnostics,
        }
        manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
        manifest.flush()
        self._log(f"saved: {target.name}")
        return True

    def _append_rejected_record(self, record: dict[str, Any]) -> None:
        with self.rejected_manifest_path.open("a", encoding="utf-8") as rejected_manifest:
            rejected_manifest.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _normalize_url(self, base_url: str, raw_url: str) -> str | None:
        raw_url = raw_url.strip()
        if not raw_url or raw_url.startswith("data:") or raw_url.startswith("javascript:"):
            return None
        normalized = urljoin(base_url, raw_url)
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            return None
        if not _domain_allowed(parsed.netloc, self.config.allowed_domains):
            return None
        return normalized

    def _is_allowed_url(
        self,
        url: str,
        *,
        allow_patterns: list[str],
        deny_patterns: list[str],
        require_image_hint: bool = False,
    ) -> bool:
        parsed = urlparse(url)
        if not _domain_allowed(parsed.netloc, self.config.allowed_domains):
            return False

        if require_image_hint and not _looks_like_image(url):
            return False

        if allow_patterns and not any(re.search(pattern, url, re.IGNORECASE) for pattern in allow_patterns):
            return False
        if any(re.search(pattern, url, re.IGNORECASE) for pattern in deny_patterns):
            return False
        return True

    def _can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        robots_key = f"{parsed.scheme}://{parsed.netloc}"
        parser = self.robot_cache.get(robots_key)
        if parser is None:
            parser = RobotFileParser()
            parser.set_url(urljoin(robots_key, "/robots.txt"))
            try:
                parser.read()
            except Exception:
                return True
            self.robot_cache[robots_key] = parser
        return parser.can_fetch(self.config.headers.get("User-Agent", "*"), url)

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, file=sys.stderr)


def _extract_json_path(value: Any, path: str) -> list[Any]:
    if path.startswith("__literal__:"):
        return [path.split(":", 1)[1]]

    if not path:
        return [value]

    parts = path.split(".")
    return _extract_json_parts(value, parts)


def _extract_json_parts(value: Any, parts: list[str]) -> list[Any]:
    if not parts:
        return [] if value is None else [value]

    part = parts[0]
    expand_list = part.endswith("[]")
    key = part[:-2] if expand_list else part

    if key:
        if not isinstance(value, dict):
            return []
        value = value.get(key)

    if expand_list:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        items: list[Any] = []
        for item in value:
            items.extend(_extract_json_parts(item, parts[1:]))
        return items

    return _extract_json_parts(value, parts[1:])


def _extract_record_metadata(record: Any, field_map: dict[str, list[str]]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field, candidates in field_map.items():
        value = _resolve_record_field(record, candidates)
        if value:
            metadata[field] = value
    return metadata


def _resolve_record_field(record: Any, candidates: list[str]) -> str | None:
    fragments: list[str] = []
    for candidate in candidates:
        for value in _extract_json_path(record, candidate):
            normalized = _normalize_scalar(value)
            if normalized and normalized not in fragments:
                fragments.append(normalized)
    if not fragments:
        return None
    return " | ".join(fragments)


def _resolve_html_field(
    candidates: list[str],
    *,
    parser: LinkCollector,
    page_url: str,
    body_text: str,
) -> str | None:
    for candidate in candidates:
        if candidate.startswith("__literal__:"):
            normalized = _normalize_whitespace(candidate.split(":", 1)[1])
            if normalized:
                return normalized
            continue
        if candidate == "__page_title__":
            if parser.page_title:
                return parser.page_title
            continue
        if candidate == "__page_url__":
            return page_url
        if candidate == "__canonical_url__":
            value = _first_non_empty(parser.meta_values.get("__canonical_url__", []))
            if value:
                return value
            continue
        if candidate == "__license_href__":
            value = _first_non_empty(parser.meta_values.get("__license_href__", []))
            if value:
                return value
            continue
        if candidate == "__body_text__":
            if body_text:
                return body_text
            continue
        value = _first_non_empty(parser.meta_values.get(candidate.lower(), []))
        if value:
            return value
    return None


def _parse_srcset(value: str) -> list[str]:
    urls: list[str] = []
    for part in value.split(","):
        candidate = part.strip().split(" ")[0].strip()
        if candidate:
            urls.append(candidate)
    return urls


def _build_record_text(record: Any, fields: list[str]) -> str:
    if not fields:
        return ""

    fragments: list[str] = []
    for field in fields:
        for value in _extract_json_path(record, field):
            normalized = _normalize_scalar(value)
            if normalized:
                fragments.append(normalized)
    return " | ".join(fragment for fragment in fragments if fragment)


def _record_matches(record_text: str, *, allow_patterns: list[str], deny_patterns: list[str]) -> bool:
    if deny_patterns and any(re.search(pattern, record_text, re.IGNORECASE) for pattern in deny_patterns):
        return False
    if allow_patterns and not any(re.search(pattern, record_text, re.IGNORECASE) for pattern in allow_patterns):
        return False
    return True


def _load_field_map(payload: dict[str, Any]) -> dict[str, list[str]]:
    field_map: dict[str, list[str]] = {}
    for key, raw_value in payload.items():
        if isinstance(raw_value, list):
            field_map[str(key)] = [str(item) for item in raw_value]
        else:
            field_map[str(key)] = [str(raw_value)]
    return field_map


def _normalize_domain(domain: str) -> str:
    return domain.lower().lstrip(".")


def _domain_allowed(domain: str, allowed_domains: set[str]) -> bool:
    normalized = _normalize_domain(domain)
    return any(normalized == allowed or normalized.endswith(f".{allowed}") for allowed in allowed_domains)


def _looks_like_image(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS)


def _guess_extension(image_url: str, content_type: str) -> str:
    path_ext = Path(urlparse(image_url).path).suffix.lower()
    if path_ext in IMAGE_EXTENSIONS:
        return path_ext
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
    return guessed or ".jpg"


def _build_filename(image_url: str, digest: str, extension: str) -> str:
    stem = Path(urlparse(image_url).path).stem or "image"
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._") or "image"
    return f"{safe_stem}_{digest[:12]}{extension}"


def _normalize_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = _normalize_whitespace(value)
        return normalized or None
    return _normalize_whitespace(json.dumps(value, ensure_ascii=False))


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _html_to_text(raw_html: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return _normalize_whitespace(without_tags)


def _derive_priority_tags(text: str) -> list[str]:
    lowered = text.lower()
    tags: list[str] = []
    tag_rules = {
        "color": ["color", "colour", "colored", "設色", "设色", "重彩", "青綠", "青绿", "mineral pigment"],
        "figure": ["figure", "figures", "lady", "ladies", "court", "portrait", "仕女", "人物", "宫廷"],
        "landscape": ["landscape", "mountain", "river", "山水", "青绿山水", "樓閣", "楼阁"],
        "bird_flower": ["bird", "flower", "peony", "花鳥", "花鸟", "折枝", "禽", "flora"],
    }
    for tag, keywords in tag_rules.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            tags.append(tag)
    return tags


def _first_non_empty(values: list[str]) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compliance-first reference scraper: downloads only whitelisted open-license images or records metadata only.",
    )
    parser.add_argument("--config", required=True, help="Path to scraper JSON config")
    parser.add_argument("--output-dir", help="Override output directory from config")
    parser.add_argument("--dry-run", action="store_true", help="Parse and log without writing image files")
    parser.add_argument("--verbose", action="store_true", help="Print crawl progress to stderr")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = Config.load(Path(args.config), output_override=args.output_dir)
        scraper = Scraper(config, dry_run=args.dry_run, verbose=args.verbose)
        try:
            scraper.run()
        finally:
            scraper.close()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
