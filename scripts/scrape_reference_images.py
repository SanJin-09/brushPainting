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


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value for key, value in attrs if value}
        tag = tag.lower()
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
    detail_url_template: str | None
    detail_page_fields: list[str]
    detail_image_fields: list[str]
    detail_record_text_fields: list[str]
    detail_record_allow_patterns: list[str]
    detail_record_deny_patterns: list[str]
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
                raise ValueError(f"api_jobs[{index}].mode must be one of {sorted(API_JOB_MODES)}")

            start_url = str(payload.get("start_url", "")).strip()
            if not start_url:
                raise ValueError(f"api_jobs[{index}].start_url is required")

            list_path = str(payload.get("list_path", "")).strip()
            if not list_path:
                raise ValueError(f"api_jobs[{index}].list_path is required")

            detail_url_template = payload.get("detail_url_template")
            if mode == "json_values_to_detail" and not str(detail_url_template or "").strip():
                raise ValueError(f"api_jobs[{index}].detail_url_template is required for json_values_to_detail")

            jobs.append(
                cls(
                    name=str(payload.get("name") or f"api_job_{index + 1}"),
                    mode=mode,
                    start_url=start_url,
                    list_path=list_path,
                    page_fields=[str(x) for x in payload.get("page_fields", [])],
                    image_fields=[str(x) for x in payload.get("image_fields", [])],
                    record_text_fields=[str(x) for x in payload.get("record_text_fields", [])],
                    record_allow_patterns=[str(x) for x in payload.get("record_allow_patterns", [])],
                    record_deny_patterns=[str(x) for x in payload.get("record_deny_patterns", [])],
                    detail_url_template=str(detail_url_template).strip() if detail_url_template else None,
                    detail_page_fields=[str(x) for x in payload.get("detail_page_fields", [])],
                    detail_image_fields=[str(x) for x in payload.get("detail_image_fields", [])],
                    detail_record_text_fields=[str(x) for x in payload.get("detail_record_text_fields", [])],
                    detail_record_allow_patterns=[str(x) for x in payload.get("detail_record_allow_patterns", [])],
                    detail_record_deny_patterns=[str(x) for x in payload.get("detail_record_deny_patterns", [])],
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
    image_url_allow_patterns: list[str]
    image_url_deny_patterns: list[str]
    headers: dict[str, str]
    api_jobs: list[ApiJob]
    image_filter: ImageFilterConfig

    @classmethod
    def load(cls, path: Path, *, output_override: str | None = None) -> "Config":
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        api_jobs = ApiJob.load_many(payload.get("api_jobs", []))
        start_urls = [str(url).strip() for url in payload.get("start_urls", []) if str(url).strip()]
        if not start_urls and not api_jobs:
            raise ValueError("config.start_urls is required unless config.api_jobs is set")

        allowed_domains = {
            _normalize_domain(domain)
            for domain in payload.get("allowed_domains", [])
            if str(domain).strip()
        }
        if not allowed_domains:
            seeds = start_urls + [job.start_url for job in api_jobs]
            allowed_domains = {_normalize_domain(urlparse(url).netloc) for url in seeds}

        output_dir = Path(output_override or payload.get("output_dir") or "runtime/reference_scrape/default").resolve()
        headers = dict(DEFAULT_HEADERS)
        headers.update({str(k): str(v) for k, v in payload.get("headers", {}).items()})
        image_filter = ImageFilterConfig.load(payload.get("image_filter", {}))

        return cls(
            start_urls=start_urls,
            allowed_domains=allowed_domains,
            output_dir=output_dir,
            request_delay_seconds=float(payload.get("request_delay_seconds", 1.0)),
            timeout_seconds=float(payload.get("timeout_seconds", 20)),
            max_pages=int(payload.get("max_pages", 200)),
            max_images=int(payload.get("max_images", 500)),
            min_image_bytes=int(payload.get("min_image_bytes", 50_000)),
            respect_robots_txt=bool(payload.get("respect_robots_txt", True)),
            page_url_allow_patterns=[str(x) for x in payload.get("page_url_allow_patterns", [])],
            page_url_deny_patterns=[str(x) for x in payload.get("page_url_deny_patterns", [])],
            image_url_allow_patterns=[str(x) for x in payload.get("image_url_allow_patterns", [])],
            image_url_deny_patterns=[str(x) for x in payload.get("image_url_deny_patterns", [])],
            headers=headers,
            api_jobs=api_jobs,
            image_filter=image_filter,
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
        self.image_filter = ImageFilterPipeline(self.config.image_filter, verbose=verbose)
        self.session = httpx.Client(
            follow_redirects=True,
            timeout=self.config.timeout_seconds,
            headers=self.config.headers,
        )

    def close(self) -> None:
        self.session.close()

    def run(self) -> None:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        for url in self.config.start_urls:
            self._enqueue_page(url)

        pages_processed = 0
        images_saved = 0

        with self.manifest_path.open("a", encoding="utf-8") as manifest:
            images_saved += self._run_api_jobs(manifest)

            while self.page_queue and pages_processed < self.config.max_pages and images_saved < self.config.max_images:
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
                    self._log(f"skip robots.txt disallow: {page_url}")
                    continue

                self.visited_pages.add(page_url)
                pages_processed += 1
                self._log(f"page {pages_processed}: {page_url}")

                try:
                    response = self.session.get(page_url)
                    response.raise_for_status()
                except Exception as exc:
                    self._log(f"page fetch failed: {page_url} ({exc})")
                    time.sleep(self.config.request_delay_seconds)
                    continue

                content_type = response.headers.get("content-type", "")
                if content_type.startswith("image/"):
                    if self._save_image_from_response(response, source_page=page_url, image_url=page_url, manifest=manifest):
                        images_saved += 1
                    time.sleep(self.config.request_delay_seconds)
                    continue

                if "json" in content_type:
                    payload = response.json()
                    images_saved += self._process_json_record(
                        payload,
                        page_fields=[],
                        image_fields=["url", "image", "image_url", "primaryImage", "primaryImageSmall", "images.web.url"],
                        record_text_fields=[],
                        record_allow_patterns=[],
                        record_deny_patterns=[],
                        base_url=str(response.url),
                        source_page=page_url,
                        manifest=manifest,
                    )
                    time.sleep(self.config.request_delay_seconds)
                    continue

                parser = LinkCollector()
                parser.feed(response.text)

                for image_url in parser.images:
                    if images_saved >= self.config.max_images:
                        break
                    if self._download_image_if_allowed(image_url, source_page=page_url, manifest=manifest, require_image_hint=True):
                        images_saved += 1
                    time.sleep(self.config.request_delay_seconds)

                for href in parser.links:
                    if images_saved >= self.config.max_images:
                        break
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

        print(
            json.dumps(
                {
                    "output_dir": str(self.config.output_dir),
                    "manifest": str(self.manifest_path),
                    "pages_processed": pages_processed,
                    "images_saved": len(self.seen_hashes),
                },
                ensure_ascii=False,
            )
        )

    def _run_api_jobs(self, manifest) -> int:
        saved = 0
        for job in self.config.api_jobs:
            if len(self.seen_hashes) >= self.config.max_images:
                break
            self._log(f"api job: {job.name}")
            saved += self._run_api_job(job, manifest)
        return saved

    def _run_api_job(self, job: ApiJob, manifest) -> int:
        saved = 0
        for index in range(job.max_requests):
            if len(self.seen_hashes) >= self.config.max_images:
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
                    if len(self.seen_hashes) >= self.config.max_images:
                        break
                    saved += self._process_json_record(
                        record,
                        page_fields=job.page_fields,
                        image_fields=job.image_fields,
                        record_text_fields=job.record_text_fields,
                        record_allow_patterns=job.record_allow_patterns,
                        record_deny_patterns=job.record_deny_patterns,
                        base_url=job.start_url,
                        source_page=job.start_url,
                        manifest=manifest,
                    )
                    time.sleep(self.config.request_delay_seconds)
                continue

            for value in records:
                if len(self.seen_hashes) >= self.config.max_images:
                    break
                detail_url = str(job.detail_url_template).format(value=value)
                detail_payload = self._fetch_json(detail_url)
                if detail_payload is None:
                    time.sleep(self.config.request_delay_seconds)
                    continue
                saved += self._process_json_record(
                    detail_payload,
                    page_fields=job.detail_page_fields,
                    image_fields=job.detail_image_fields,
                    record_text_fields=job.detail_record_text_fields,
                    record_allow_patterns=job.detail_record_allow_patterns,
                    record_deny_patterns=job.detail_record_deny_patterns,
                    base_url=detail_url,
                    source_page=detail_url,
                    manifest=manifest,
                )
                time.sleep(self.config.request_delay_seconds)
        return saved

    def _fetch_json(self, url: str, *, params: dict[str, str] | None = None) -> Any | None:
        if not self._is_allowed_url(url, allow_patterns=[], deny_patterns=[]):
            self._log(f"skip disallowed api url: {url}")
            return None
        if not self._can_fetch(url):
            self._log(f"skip robots.txt disallow: {url}")
            return None

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            self._log(f"api fetch failed: {url} ({exc})")
            return None

    def _process_json_record(
        self,
        record: Any,
        *,
        page_fields: list[str],
        image_fields: list[str],
        record_text_fields: list[str],
        record_allow_patterns: list[str],
        record_deny_patterns: list[str],
        base_url: str,
        source_page: str,
        manifest,
    ) -> int:
        record_text = _build_record_text(record, record_text_fields)
        if not _record_matches(record_text, allow_patterns=record_allow_patterns, deny_patterns=record_deny_patterns):
            if self.verbose and record_text:
                self._log(f"skip filtered record: {record_text[:160]}")
            return 0

        saved = 0
        for field in page_fields:
            for value in _extract_json_path(record, field):
                normalized = self._normalize_url(base_url, str(value))
                if not normalized:
                    continue
                self._enqueue_page(normalized)

        for field in image_fields:
            for value in _extract_json_path(record, field):
                if len(self.seen_hashes) >= self.config.max_images:
                    break
                if self._download_image_if_allowed(str(value), source_page=source_page, manifest=manifest):
                    saved += 1
        return saved

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
            return False

        self.seen_image_urls.add(normalized)
        return self._download_image(normalized, source_page, manifest)

    def _download_image(self, image_url: str, source_page: str, manifest) -> bool:
        try:
            response = self.session.get(image_url)
            response.raise_for_status()
        except Exception as exc:
            self._log(f"image fetch failed: {image_url} ({exc})")
            return False
        return self._save_image_from_response(response, source_page=source_page, image_url=image_url, manifest=manifest)

    def _save_image_from_response(self, response: httpx.Response, *, source_page: str, image_url: str, manifest) -> bool:
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            self._log(f"skip non-image: {image_url} ({content_type or 'unknown'})")
            return False
        content = response.content
        if len(content) < self.config.min_image_bytes:
            self._log(f"skip tiny image: {image_url} ({len(content)} bytes)")
            return False

        passed_filter, filter_diagnostics = self.image_filter.assess(content)
        if not passed_filter:
            self._append_rejected_record(
                {
                    "image_url": image_url,
                    "source_page": source_page,
                    "content_type": content_type,
                    "size_bytes": len(content),
                    "filter_diagnostics": filter_diagnostics,
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

        if allow_patterns and not any(re.search(pattern, url) for pattern in allow_patterns):
            return False
        if any(re.search(pattern, url) for pattern in deny_patterns):
            return False
        return True

    def _can_fetch(self, url: str) -> bool:
        if not self.config.respect_robots_txt:
            return True

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
            if value is None:
                continue
            if isinstance(value, str):
                fragments.append(value)
            else:
                fragments.append(json.dumps(value, ensure_ascii=False))
    return " | ".join(fragment.strip() for fragment in fragments if str(fragment).strip())


def _record_matches(record_text: str, *, allow_patterns: list[str], deny_patterns: list[str]) -> bool:
    if deny_patterns and any(re.search(pattern, record_text, re.IGNORECASE) for pattern in deny_patterns):
        return False
    if allow_patterns and not any(re.search(pattern, record_text, re.IGNORECASE) for pattern in allow_patterns):
        return False
    return True


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch download reference images from allowed websites for later manual review.",
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
