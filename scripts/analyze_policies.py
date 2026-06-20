"""
analyze_policies.py - Three-tier policy analysis.
Tier 1: Deterministic compliance checks (no LLM).
Tier 2: LLM-based factual observations (Group vs HE comparisons, version diffs).
Tier 3: LLM-based suggestions for review (lowest confidence, always flagged).
"""

import json
import os
import re
import logging
from pathlib import Path
from datetime import date

import anthropic
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
REGISTER_PATH = BASE_DIR / "data" / "register" / "policies_register.json"
OUTPUT_PATH = BASE_DIR / "data" / "register" / "analysis.json"

DISCLAIMER = "AI-generated prompt for governance review. Not a verified finding."


def load_register():
    with open(REGISTER_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_full_text(pdf_path: Path, max_pages: int = 10) -> str:
    """Extract text from a PDF (more pages for analysis than for metadata)."""
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


def tier1_compliance(policies: list) -> list:
    """Deterministic compliance checks - no LLM needed."""
    findings = []
    all_names = {p["policy_name"].lower() for p in policies if p.get("policy_name")}
    today = date.today()

    for policy in policies:
        source_file = policy["filename"]
        issues = []

        if not policy.get("policy_name") or policy["policy_name"] == "not found":
            issues.append("Missing policy name")
        if not policy.get("approval_date") or policy["approval_date"] == "not found":
            issues.append("Missing approval date")
        if not policy.get("next_review_date") or policy["next_review_date"] == "not found":
            issues.append("Missing next review date")
        if not policy.get("owner") or policy["owner"] == "not found":
            issues.append("Missing owner/responsible department")

        # Check for orphaned references - look for mentions of other policy names
        local_path = BASE_DIR / policy["local_path"]
        if local_path.exists():
            text = extract_full_text(local_path, max_pages=3)
            # Look for references to policies not in our register
            policy_ref_patterns = [
                r"(?:refer to|see|in accordance with|as per)\s+(?:the\s+)?([A-Z][A-Za-z\s&]+Policy)",
                r"(?:refer to|see|in accordance with|as per)\s+(?:the\s+)?([A-Z][A-Za-z\s&]+Procedure)",
            ]
            for pattern in policy_ref_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    ref_name = match.strip().lower()
                    if ref_name not in all_names and len(ref_name) > 5:
                        issues.append(f"References '{match.strip()}' which is not in the register")

        if issues:
            findings.append({
                "policy_name": policy.get("policy_name", source_file),
                "source": policy["source"],
                "source_file": source_file,
                "issues": issues,
            })

    return findings


def find_matching_policies(policies: list) -> list:
    """Find policies that appear in both IEG central and UCP sets."""
    ieg_policies = {p["policy_name"].lower(): p for p in policies if p["source"] == "ieg_central" and p.get("policy_name") != "not found"}
    ucp_policies = {p["policy_name"].lower(): p for p in policies if p["source"] == "ucp" and p.get("policy_name") != "not found"}

    matches = []
    for ieg_name, ieg_policy in ieg_policies.items():
        for ucp_name, ucp_policy in ucp_policies.items():
            # Check for similar names (fuzzy match on key words)
            ieg_words = set(ieg_name.split()) - {"policy", "procedure", "the", "and", "of", "for", "a"}
            ucp_words = set(ucp_name.split()) - {"policy", "procedure", "the", "and", "of", "for", "a"}
            if ieg_words and ucp_words:
                overlap = ieg_words & ucp_words
                if len(overlap) >= 2 or (len(overlap) >= 1 and len(ieg_words) <= 3):
                    matches.append((ieg_policy, ucp_policy))

    return matches


def find_versioned_documents(policies: list) -> list:
    """Find documents that have multiple dated versions (e.g. Annual Reports)."""
    from collections import defaultdict
    by_base_name = defaultdict(list)

    for p in policies:
        name = p.get("policy_name", p["filename"])
        # Strip years from name to find base document
        base = re.sub(r"\b20\d{2}[-/]?\d{0,2}\b", "", name).strip().rstrip("-/ ")
        if base:
            by_base_name[base.lower()].append(p)

    versioned = [(base, docs) for base, docs in by_base_name.items() if len(docs) > 1]
    return versioned


def tier2_observations(client: anthropic.Anthropic, policies: list) -> list:
    """LLM-based factual observations: Group vs HE comparisons and version diffs."""
    observations = []

    # Group vs HE comparisons
    matches = find_matching_policies(policies)
    logger.info(f"Tier 2: Found {len(matches)} Group vs HE policy pairs to compare")

    for ieg_policy, ucp_policy in matches:
        ieg_path = BASE_DIR / ieg_policy["local_path"]
        ucp_path = BASE_DIR / ucp_policy["local_path"]

        ieg_text = extract_full_text(ieg_path, max_pages=5)
        ucp_text = extract_full_text(ucp_path, max_pages=5)

        if not ieg_text or not ucp_text:
            continue

        prompt = f"""Compare these two versions of a similar policy - one from the IEG Group set and one from UCP (HE-specific).

IEG GROUP VERSION: "{ieg_policy['policy_name']}"
---
{ieg_text[:4000]}
---

UCP (HE) VERSION: "{ucp_policy['policy_name']}"
---
{ucp_text[:4000]}
---

Provide a factual comparison:
1. Substantive differences in process or requirements (not just wording)
2. Any direct contradictions between the two
3. Scope differences (what one covers that the other does not)

Return JSON only:
{{
  "summary": "one-line summary of the relationship",
  "substantive_differences": ["list of key differences"],
  "contradictions": ["list of contradictions, or empty"],
  "scope_differences": ["list of scope differences"]
}}"""

        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = message.content[0].text.strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            comparison = json.loads(response_text)
            observations.append({
                "type": "group_vs_he_comparison",
                "ieg_policy": ieg_policy["policy_name"],
                "ieg_file": ieg_policy["filename"],
                "ucp_policy": ucp_policy["policy_name"],
                "ucp_file": ucp_policy["filename"],
                "comparison": comparison,
            })
        except (json.JSONDecodeError, anthropic.APIError) as e:
            logger.warning(f"Tier 2 comparison failed for {ieg_policy['policy_name']} vs {ucp_policy['policy_name']}: {e}")

    # Version-over-time comparisons
    versioned = find_versioned_documents(policies)
    logger.info(f"Tier 2: Found {len(versioned)} document sets with multiple versions")

    for base_name, docs in versioned[:10]:  # Cap at 10 to manage API costs
        if len(docs) < 2:
            continue
        docs_sorted = sorted(docs, key=lambda d: d.get("approval_date", "0000"))
        older = docs_sorted[0]
        newer = docs_sorted[-1]

        older_text = extract_full_text(BASE_DIR / older["local_path"], max_pages=5)
        newer_text = extract_full_text(BASE_DIR / newer["local_path"], max_pages=5)

        if not older_text or not newer_text:
            continue

        prompt = f"""Compare these two versions of the same document over time.

OLDER VERSION: "{older.get('policy_name', older['filename'])}"
---
{older_text[:4000]}
---

NEWER VERSION: "{newer.get('policy_name', newer['filename'])}"
---
{newer_text[:4000]}
---

Summarise the substantive changes between versions. Focus on policy/procedural changes, not formatting.

Return JSON only:
{{
  "summary": "one-line summary of changes",
  "key_changes": ["list of substantive changes"],
  "removed_content": ["anything significant that was removed"],
  "added_content": ["anything significant that was added"]
}}"""

        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = message.content[0].text.strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            changes = json.loads(response_text)
            observations.append({
                "type": "version_comparison",
                "base_document": base_name,
                "older_file": older["filename"],
                "newer_file": newer["filename"],
                "changes": changes,
            })
        except (json.JSONDecodeError, anthropic.APIError) as e:
            logger.warning(f"Tier 2 version comparison failed for {base_name}: {e}")

    return observations


def tier3_suggestions(client: anthropic.Anthropic, policies: list) -> list:
    """LLM-based suggestions for review - lowest confidence, always flagged."""
    suggestions = []

    for i, policy in enumerate(policies):
        local_path = BASE_DIR / policy["local_path"]
        if not local_path.exists():
            continue

        text = extract_full_text(local_path, max_pages=5)
        if not text or len(text) < 200:
            continue

        logger.info(f"Tier 3: Analysing {i+1}/{len(policies)} - {policy.get('policy_name', policy['filename'])}")

        prompt = f"""Review this policy document for potential issues that a governance reviewer should check.

Policy: "{policy.get('policy_name', policy['filename'])}"
Source: {policy['source']}
---
{text[:6000]}
---

Look for:
1. Internally contradictory language
2. Ambiguous wording that practitioners commonly misread
3. References to potentially superseded legislation or guidance
4. Missing cross-references to related policies

For each issue found, return JSON array:
[
  {{
    "category": "contradiction/ambiguity/superseded_reference/missing_cross_reference",
    "observation": "what the reviewer should check",
    "location_hint": "where in the document (section/paragraph reference if visible)",
    "confidence": "high/medium/low"
  }}
]

If no issues found, return an empty array: []
Be conservative - only flag things genuinely worth a reviewer's time."""

        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = message.content[0].text.strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            items = json.loads(response_text)
            for item in items:
                item["source_file"] = policy["filename"]
                item["policy_name"] = policy.get("policy_name", policy["filename"])
                item["source"] = policy["source"]
                item["requires_human_review"] = True
                item["disclaimer"] = DISCLAIMER
                suggestions.append(item)
        except (json.JSONDecodeError, anthropic.APIError) as e:
            logger.warning(f"Tier 3 analysis failed for {policy['filename']}: {e}")

    return suggestions


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY environment variable not set.")
        raise SystemExit(1)

    client = anthropic.Anthropic(api_key=api_key)
    register = load_register()
    policies = register["policies"]

    logger.info(f"Analysing {len(policies)} policies across 3 tiers...")

    # Tier 1 - deterministic
    logger.info("=== TIER 1: Compliance checks (deterministic) ===")
    tier1 = tier1_compliance(policies)
    logger.info(f"Tier 1: {len(tier1)} policies with compliance issues")

    # Tier 2 - LLM observations
    logger.info("=== TIER 2: Observations (LLM, factual comparisons) ===")
    tier2 = tier2_observations(client, policies)
    logger.info(f"Tier 2: {len(tier2)} observations generated")

    # Tier 3 - LLM suggestions
    logger.info("=== TIER 3: Suggestions for review (LLM, lowest confidence) ===")
    tier3 = tier3_suggestions(client, policies)
    logger.info(f"Tier 3: {len(tier3)} suggestions generated")

    analysis = {
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "total_policies_analysed": len(policies),
        "tier1_compliance": {
            "description": "Deterministic compliance checks - no LLM used",
            "total_issues": len(tier1),
            "findings": tier1,
        },
        "tier2_observations": {
            "description": "LLM-based factual observations - comparisons with cited sources",
            "total_observations": len(tier2),
            "findings": tier2,
        },
        "tier3_suggestions": {
            "description": "LLM-generated prompts for governance review - lowest confidence tier",
            "disclaimer": DISCLAIMER,
            "total_suggestions": len(tier3),
            "by_confidence": {
                "high": len([s for s in tier3 if s.get("confidence") == "high"]),
                "medium": len([s for s in tier3 if s.get("confidence") == "medium"]),
                "low": len([s for s in tier3 if s.get("confidence") == "low"]),
            },
            "findings": tier3,
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("ANALYSIS COMPLETE")
    logger.info(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
