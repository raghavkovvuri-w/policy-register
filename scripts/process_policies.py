"""
process_policies.py - Extracts metadata from downloaded policy PDFs using Claude API.
Reads the first 2 pages of each PDF and asks Claude to extract structured metadata.
"""

import json
import os
import logging
from pathlib import Path

import anthropic
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = BASE_DIR / "data" / "policies" / "MANIFEST.json"
OUTPUT_PATH = BASE_DIR / "data" / "register" / "extracted_metadata.json"

EXTRACTION_SYSTEM_PROMPT = (
    "Extract policy metadata from the document text. Be precise about dates. "
    "If a field is not explicitly present in the text, return the exact string "
    "'not found' - never guess or infer a date. Return JSON only, no prose."
)

EXTRACTION_USER_PROMPT = """Extract the following metadata from this policy document text. Return ONLY valid JSON with these fields:

{{
  "policy_name": "the full policy title",
  "approval_date": "YYYY-MM-DD or 'not found'",
  "next_review_date": "YYYY-MM-DD or 'not found'",
  "review_frequency": "annual/biennial/triennial/other or 'not found'",
  "owner": "responsible person or department, or 'not found'",
  "version": "version number/string or 'not found'",
  "categories": ["list of categories like safeguarding, academic, finance, data protection, HR, health and safety, IT, governance, estates, equality"]
}}

Document text (first 2 pages):
---
{text}
---"""


def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_text_from_pdf(pdf_path: Path, max_pages: int = 2) -> str:
    """Extract text from the first N pages of a PDF."""
    try:
        reader = PdfReader(str(pdf_path))
        pages_to_read = min(max_pages, len(reader.pages))
        text = ""
        for i in range(pages_to_read):
            page_text = reader.pages[i].extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        logger.warning(f"Failed to read PDF {pdf_path}: {e}")
        return ""


def extract_metadata_with_claude(client: anthropic.Anthropic, text: str) -> dict:
    """Send text to Claude API for metadata extraction."""
    if not text or len(text) < 50:
        return None

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=EXTRACTION_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": EXTRACTION_USER_PROMPT.format(text=text[:8000])}
            ],
        )
        response_text = message.content[0].text.strip()
        # Strip markdown code fences if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse Claude response as JSON: {e}")
        return None
    except anthropic.APIError as e:
        logger.warning(f"Anthropic API error: {e}")
        return None


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY environment variable not set.")
        raise SystemExit(1)

    client = anthropic.Anthropic(api_key=api_key)
    manifest = load_manifest()
    results = []

    completeness = {}
    fields = ["policy_name", "approval_date", "next_review_date", "review_frequency", "owner", "version"]

    total = len(manifest["files"])
    logger.info(f"Processing {total} policy PDFs...")

    for i, file_record in enumerate(manifest["files"], 1):
        local_path = BASE_DIR / file_record["local_path"]
        source = file_record["source"]
        logger.info(f"[{i}/{total}] {file_record['filename']} ({source})")

        if not local_path.exists():
            logger.warning(f"  File not found: {local_path}")
            continue

        text = extract_text_from_pdf(local_path)
        if not text:
            logger.warning(f"  No text extracted from {file_record['filename']}")
            metadata = {f: "not found" for f in fields}
            metadata["categories"] = []
        else:
            metadata = extract_metadata_with_claude(client, text)
            if metadata is None:
                logger.warning(f"  Extraction failed for {file_record['filename']}")
                metadata = {f: "not found" for f in fields}
                metadata["categories"] = []

        record = {
            "source": source,
            "filename": file_record["filename"],
            "local_path": file_record["local_path"],
            "url": file_record["url"],
            "link_text": file_record.get("link_text", ""),
            "extracted": metadata,
        }
        results.append(record)

        # Track completeness per source
        if source not in completeness:
            completeness[source] = {f: {"found": 0, "not_found": 0} for f in fields}
        for field in fields:
            val = metadata.get(field, "not found")
            if val and val != "not found":
                completeness[source][field]["found"] += 1
            else:
                completeness[source][field]["not_found"] += 1

    output = {
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "total_processed": len(results),
        "completeness_summary": completeness,
        "policies": results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("EXTRACTION COMPLETE")
    logger.info(f"Processed: {len(results)} files")
    logger.info(f"Output: {OUTPUT_PATH}")
    logger.info("")
    logger.info("COMPLETENESS SUMMARY:")
    for source, fields_data in completeness.items():
        logger.info(f"  [{source}]")
        for field, counts in fields_data.items():
            total_f = counts["found"] + counts["not_found"]
            pct = (counts["found"] / total_f * 100) if total_f > 0 else 0
            logger.info(f"    {field}: {counts['found']}/{total_f} ({pct:.0f}% found)")


if __name__ == "__main__":
    main()
