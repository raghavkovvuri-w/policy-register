"""
fetch_policies.py - Downloads all published policy PDFs from configured sources.
Uses Playwright to handle JavaScript-rendered pages with "Load More" pagination.
"""

import json
import hashlib
import time
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "sources.json"
POLICIES_DIR = BASE_DIR / "data" / "policies"
MANIFEST_PATH = BASE_DIR / "data" / "policies" / "MANIFEST.json"

SITE_SELECTORS = {
    "ieg_central": {
        "load_more": "a:has-text('Load More')",
        "document_links": "a[href*='.pdf']",
        "wait_for": ".page-report__document, main",
        "max_load_more_clicks": 50,
    },
    "ucp": {
        "load_more": "a:has-text('Load More'), button:has-text('Load More')",
        "document_links": "a[href*='.pdf']",
        "wait_for": "main, .entry-content",
        "max_load_more_clicks": 50,
    },
}


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_manifest():
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"files": [], "downloaded_urls": {}}


def save_manifest(manifest):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def click_load_more(page, selector: str, max_clicks: int):
    """Repeatedly click "Load More" until no more items appear or max reached."""
    clicks = 0
    while clicks < max_clicks:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0 or not locator.is_visible():
                break
            locator.click()
            clicks += 1
            page.wait_for_timeout(2000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeout:
                pass
        except PlaywrightTimeout:
            break
        except Exception as e:
            logger.warning(f"Load More click {clicks} failed: {e}")
            break
    return clicks


def collect_pdf_links(page, selector: str):
    """Collect all PDF links from the rendered page."""
    links = []
    elements = page.query_selector_all(selector)
    for el in elements:
        href = el.get_attribute("href")
        text = el.inner_text().strip() or el.get_attribute("title") or ""
        if href and ".pdf" in href.lower():
            if not href.startswith("http"):
                base = page.url
                if href.startswith("/"):
                    parsed = urlparse(base)
                    href = f"{parsed.scheme}://{parsed.netloc}{href}"
                else:
                    href = base.rstrip("/") + "/" + href
            links.append({"url": href, "text": text})

    # Also look for links containing storage.googleapis.com
    all_anchors = page.query_selector_all("a[href*='storage.googleapis.com']")
    for el in all_anchors:
        href = el.get_attribute("href")
        text = el.inner_text().strip() or el.get_attribute("title") or ""
        if href and href not in [l["url"] for l in links]:
            links.append({"url": href, "text": text})

    return links


def download_pdf(url: str, dest_path: Path, page=None) -> bool:
    """Download a PDF file. Uses Playwright page context if provided (carries cookies), else httpx."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Try Playwright-based download first (carries session cookies)
    if page:
        for attempt in range(3):
            try:
                response = page.request.get(url, timeout=60000)
                if response.ok:
                    dest_path.write_bytes(response.body())
                    return True
                logger.warning(f"HTTP {response.status} for {url} (attempt {attempt+1})")
            except Exception as e:
                logger.warning(f"Playwright download error for {url} (attempt {attempt+1}): {e}")
            time.sleep(2)
        return False

    # Fallback to httpx
    for attempt in range(3):
        try:
            with httpx.Client(follow_redirects=True, timeout=60.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    dest_path.write_bytes(resp.content)
                    return True
                logger.warning(f"HTTP {resp.status_code} for {url} (attempt {attempt+1})")
        except Exception as e:
            logger.warning(f"Download error for {url} (attempt {attempt+1}): {e}")
        time.sleep(2)
    return False


def scrape_site(source_key: str, source_config: dict, manifest: dict):
    """Scrape a single site for PDF links and download them."""
    url = source_config["url"]
    selectors = SITE_SELECTORS.get(source_key, SITE_SELECTORS["ieg_central"])
    site_dir = POLICIES_DIR / source_key

    stats = {"pages_visited": 1, "links_found": 0, "downloaded": 0, "skipped": 0, "failed": 0}

    logger.info(f"--- Scraping {source_key}: {url} ---")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeout:
            logger.warning(f"Initial page load timed out for {source_key}, continuing anyway")
            page.wait_for_timeout(3000)

        try:
            page.wait_for_selector(selectors["wait_for"], timeout=10000)
        except PlaywrightTimeout:
            logger.warning(f"Content selector not found for {source_key}, proceeding with page as-is")

        clicks = click_load_more(page, selectors["load_more"], selectors["max_load_more_clicks"])
        if clicks > 0:
            logger.info(f"Clicked 'Load More' {clicks} times for {source_key}")

        pdf_links = collect_pdf_links(page, selectors["document_links"])
        stats["links_found"] = len(pdf_links)
        logger.info(f"Found {len(pdf_links)} PDF links on {source_key}")

        for link in pdf_links:
            pdf_url = link["url"]
            uhash = url_hash(pdf_url)

            if uhash in manifest["downloaded_urls"]:
                stats["skipped"] += 1
                continue

            parsed = urlparse(pdf_url)
            filename = Path(parsed.path).name
            if not filename.endswith(".pdf"):
                filename = f"{uhash}.pdf"
            # Avoid filename collisions by prefixing with hash if needed
            dest = site_dir / filename
            if dest.exists():
                dest = site_dir / f"{uhash}_{filename}"

            if download_pdf(pdf_url, dest, page=page):
                file_record = {
                    "source": source_key,
                    "url": pdf_url,
                    "url_hash": uhash,
                    "local_path": str(dest.relative_to(BASE_DIR)),
                    "filename": dest.name,
                    "link_text": link["text"],
                    "file_size_bytes": dest.stat().st_size,
                    "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                manifest["files"].append(file_record)
                manifest["downloaded_urls"][uhash] = pdf_url
                stats["downloaded"] += 1
            else:
                stats["failed"] += 1

        browser.close()

    logger.info(
        f"[{source_key}] Summary: pages={stats['pages_visited']}, "
        f"links={stats['links_found']}, downloaded={stats['downloaded']}, "
        f"skipped={stats['skipped']}, failed={stats['failed']}"
    )
    return stats


def main():
    config = load_config()
    manifest = load_manifest()

    all_stats = {}
    public_sources = config["sources"]["public"]

    for key, source in public_sources.items():
        if not source.get("active", False):
            logger.info(f"Skipping inactive source: {key}")
            continue
        stats = scrape_site(key, source, manifest)
        all_stats[key] = stats

    save_manifest(manifest)

    logger.info("=" * 60)
    logger.info("FETCH COMPLETE")
    logger.info(f"Total files in manifest: {len(manifest['files'])}")
    for key, stats in all_stats.items():
        logger.info(f"  {key}: {stats['links_found']} found, {stats['downloaded']} new, {stats['failed']} failed")
    logger.info(f"Manifest saved to: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
