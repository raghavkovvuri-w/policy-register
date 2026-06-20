"""
build_register.py - Builds the authoritative policy register from extracted metadata.
Computes review status, preserves human edits on re-run.
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
EXTRACTED_PATH = BASE_DIR / "data" / "register" / "extracted_metadata.json"
REGISTER_PATH = BASE_DIR / "data" / "register" / "policies_register.json"

STATUS_ORDER = {"OVERDUE": 0, "DUE_SOON": 1, "CURRENT": 2, "MISSING_DATA": 3}


def parse_date(date_str: str):
    """Parse a date string, returning None if not found or invalid."""
    if not date_str or date_str == "not found":
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def compute_status(next_review_date_str: str) -> dict:
    """Compute review status from the next review date."""
    review_date = parse_date(next_review_date_str)
    if review_date is None:
        return {"status": "MISSING_DATA", "days_until_review": None, "is_overdue": False, "is_due_soon": False}

    today = date.today()
    days_left = (review_date - today).days

    if days_left < 0:
        return {"status": "OVERDUE", "days_until_review": days_left, "is_overdue": True, "is_due_soon": False}
    elif days_left <= 90:
        return {"status": "DUE_SOON", "days_until_review": days_left, "is_overdue": False, "is_due_soon": True}
    else:
        return {"status": "CURRENT", "days_until_review": days_left, "is_overdue": False, "is_due_soon": False}


def load_existing_register() -> dict:
    """Load existing register to preserve human edits."""
    if REGISTER_PATH.exists():
        with open(REGISTER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def merge_with_existing(new_record: dict, existing_policies: dict) -> dict:
    """Preserve manually_verified fields from existing register."""
    key = new_record.get("url", new_record.get("filename", ""))
    if key in existing_policies:
        existing = existing_policies[key]
        for field, value in existing.items():
            if isinstance(value, dict) and value.get("manually_verified"):
                new_record[field] = value
            elif field == "manually_verified_fields":
                for mv_field in value:
                    if mv_field in existing:
                        new_record[mv_field] = existing[mv_field]
    return new_record


def main():
    with open(EXTRACTED_PATH, "r", encoding="utf-8") as f:
        extracted = json.load(f)

    existing_register = load_existing_register()
    existing_policies = {}
    if existing_register:
        for p in existing_register.get("policies", []):
            key = p.get("url", p.get("filename", ""))
            existing_policies[key] = p

    policies = []
    for record in extracted["policies"]:
        meta = record["extracted"]
        next_review = meta.get("next_review_date", "not found")
        status_info = compute_status(next_review)

        policy = {
            "policy_name": meta.get("policy_name", record.get("link_text", record["filename"])),
            "source": record["source"],
            "filename": record["filename"],
            "local_path": record["local_path"],
            "url": record["url"],
            "link_text": record.get("link_text", ""),
            "approval_date": meta.get("approval_date", "not found"),
            "next_review_date": next_review,
            "review_frequency": meta.get("review_frequency", "not found"),
            "owner": meta.get("owner", "not found"),
            "version": meta.get("version", "not found"),
            "categories": meta.get("categories", []),
            "status": status_info["status"],
            "days_until_review": status_info["days_until_review"],
            "is_overdue": status_info["is_overdue"],
            "is_due_soon": status_info["is_due_soon"],
        }

        policy = merge_with_existing(policy, existing_policies)
        policies.append(policy)

    policies.sort(key=lambda p: (STATUS_ORDER.get(p["status"], 99), p.get("days_until_review") or 9999))

    counts = {"OVERDUE": 0, "DUE_SOON": 0, "CURRENT": 0, "MISSING_DATA": 0}
    for p in policies:
        counts[p["status"]] = counts.get(p["status"], 0) + 1

    register = {
        "register_metadata": {
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "total_policies": len(policies),
            "status_counts": counts,
            "sources": list(set(p["source"] for p in policies)),
        },
        "policies": policies,
    }

    REGISTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTER_PATH, "w", encoding="utf-8") as f:
        json.dump(register, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("REGISTER BUILT")
    logger.info(f"Total policies: {len(policies)}")
    for status, count in counts.items():
        logger.info(f"  {status}: {count}")
    logger.info(f"Output: {REGISTER_PATH}")


if __name__ == "__main__":
    main()
