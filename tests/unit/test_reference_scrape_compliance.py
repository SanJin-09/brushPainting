import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from filter_downloaded_reference_images import evaluate_content_filter  # noqa: E402
from run_reference_scrape_batch import BatchConfig  # noqa: E402
from scrape_reference_images import Config, LinkCollector, Scraper, _record_matches  # noqa: E402


def test_download_config_requires_open_license_patterns(tmp_path):
    config_path = tmp_path / "invalid_download.json"
    config_path.write_text(
        json.dumps(
            {
                "site_id": "invalid_download",
                "access_mode": "download",
                "source_type": "api",
                "respect_robots_txt": True,
                "requires_open_license": True,
                "download_jobs": [
                    {
                        "name": "job",
                        "mode": "json_records",
                        "start_url": "https://example.com/api",
                        "list_path": "items[]",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="license_allow_patterns"):
        Config.load(config_path)


def test_config_rejects_non_compliant_robots_setting(tmp_path):
    config_path = tmp_path / "invalid_robots.json"
    config_path.write_text(
        json.dumps(
            {
                "site_id": "invalid_robots",
                "access_mode": "metadata_only",
                "source_type": "html",
                "start_urls": ["https://example.com/collection"],
                "respect_robots_txt": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="respect_robots_txt"):
        Config.load(config_path)


def test_batch_config_loads_all_official_sites():
    batch = BatchConfig.load(ROOT / "scripts" / "reference_scrape_batches" / "official_zero_auth_all.json")

    assert batch.batch_id == "official_zero_auth_all"
    assert len(batch.sites) == 8
    assert any(site.site_id == "met_open_access" for site in batch.sites)


def test_html_metadata_extraction_uses_meta_and_regex(tmp_path):
    config_path = tmp_path / "metadata.json"
    config_path.write_text(
        json.dumps(
            {
                "site_id": "metadata_site",
                "access_mode": "metadata_only",
                "source_type": "html",
                "start_urls": ["https://example.com/works/1"],
                "respect_robots_txt": True,
                "html_metadata_fields": {
                    "title": ["og:title", "__page_title__"],
                    "rights": ["dc.rights"],
                    "object_url": ["__canonical_url__", "__page_url__"],
                },
                "html_regex_fields": {
                    "catalog_number": ["Object\\s*No\\.?\\s*[:：]?\\s*([A-Z0-9-]+)"]
                },
                "html_download_link_patterns": ["download"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = Config.load(config_path)
    scraper = Scraper(config, dry_run=True, verbose=False)
    try:
        html = """
        <html>
          <head>
            <title>Fallback Title</title>
            <meta property="og:title" content="Colored Court Painting">
            <meta name="dc.rights" content="CC BY 4.0">
            <link rel="canonical" href="https://example.com/works/1">
          </head>
          <body>
            <a href="/download/full.jpg">Download</a>
            <div>Object No.: ABC-123</div>
          </body>
        </html>
        """
        parser = LinkCollector()
        parser.feed(html)
        metadata = scraper._extract_html_metadata("https://example.com/works/1", html, parser)
    finally:
        scraper.close()

    assert metadata["title"] == "Colored Court Painting"
    assert metadata["rights"] == "CC BY 4.0"
    assert metadata["catalog_number"] == "ABC-123"
    assert metadata["download_entry_status"] == "available"


def test_html_content_patterns_filter_out_ceramics(tmp_path):
    config_path = tmp_path / "content_filter.json"
    config_path.write_text(
        json.dumps(
            {
                "site_id": "content_filter_site",
                "access_mode": "download",
                "source_type": "html",
                "start_urls": ["https://example.com/object/1"],
                "respect_robots_txt": True,
                "requires_open_license": False,
                "max_images": 10,
                "content_allow_patterns": ["painting", "figure", "landscape"],
                "content_deny_patterns": ["porcelain", "ceramic", "vase"],
                "html_metadata_fields": {
                    "title": ["og:title", "__page_title__"],
                    "object_url": ["__canonical_url__", "__page_url__"]
                },
                "html_download_link_patterns": ["download"]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = Config.load(config_path)
    scraper = Scraper(config, dry_run=True, verbose=False)
    try:
        html = """
        <html>
          <head>
            <title>Qianlong porcelain vase</title>
            <meta property="og:title" content="Qianlong porcelain vase">
            <link rel="canonical" href="https://example.com/object/1">
          </head>
          <body>
            <a href="/download/full.jpg">Download</a>
          </body>
        </html>
        """
        parser = LinkCollector()
        parser.feed(html)
        metadata = scraper._extract_html_metadata("https://example.com/object/1", html, parser)
        text = scraper._build_html_filter_text("https://example.com/object/1", html, metadata)
    finally:
        scraper.close()

    assert (
        _record_matches(
            text,
            allow_patterns=config.content_allow_patterns,
            deny_patterns=config.content_deny_patterns,
        )
        is False
    )


def test_offline_content_filter_rejects_porcelain_metadata():
    passed, diagnostics = evaluate_content_filter(
        {
            "title": "Qianlong porcelain vase with lid",
            "object_url": "https://example.com/object/1",
            "priority_tags": ["color"],
        },
        allow_patterns=["painting", "figure", "landscape"],
        deny_patterns=["porcelain", "ceramic", "vase", "lid"],
    )

    assert passed is False
    assert diagnostics["matched_pattern"] in {"porcelain", "vase", "lid"}
