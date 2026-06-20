# Policy Register Dashboard

A tool that pulls every published policy from the Inspire Education Group institutional websites, builds an authoritative register with review dates and owners, flags overdue or missing data, and compares Group vs HE policy sets.

## Sources

- **IEG Central** (`ieg.ac.uk/documents/`) — Group-wide register covering Peterborough College, Stamford College and all group policies.
- **UCP** (`ucp.ac.uk/.../published-documents/`) — UCP HE-specific published documents.

## Requirements

- Python 3.10+
- Playwright for Python (handles JavaScript-loaded pages)
- Anthropic API key

## Setup

```bash
# Install dependencies
pip install playwright httpx pypdf anthropic

# Install Playwright browsers
playwright install chromium

# Set API key
set ANTHROPIC_API_KEY=your-key-here    (Windows)
export ANTHROPIC_API_KEY=your-key-here  (Mac/Linux)
```

## Running

**Windows:**
```
run_register.bat
```

**Mac/Linux:**
```bash
chmod +x run_register.sh
./run_register.sh
```

Then open `output/dashboard.html` in a browser.

## Pipeline steps

1. **fetch_policies.py** — Scrapes both sites using Playwright, downloads all PDFs.
2. **process_policies.py** — Extracts metadata from each PDF using Claude API.
3. **build_register.py** — Computes review status, builds the authoritative register.
4. **analyze_policies.py** — Three-tier analysis (compliance, comparisons, review suggestions).
5. **generate_dashboard.py** — Produces a self-contained HTML dashboard.

## Status legend

| Status | Meaning | Colour |
|--------|---------|--------|
| OVERDUE | Review date has passed | Red |
| DUE_SOON | Review due within 90 days | Amber |
| CURRENT | Review date in the future | Green |
| MISSING_DATA | No review date found in document | Grey |

## Adding internal (Google Drive) policies

1. Get the Google Drive folder ID containing the internal policies.
2. In `config/sources.json`, set `internal.google_drive.folder_id` to the folder ID.
3. Set `active: true`.
4. Place your OAuth credentials as `credentials.json` in the project root.
5. Re-run the pipeline. All later stages handle internal policies automatically.

## Notes

- The register (`data/register/policies_register.json`) is designed for human correction. Fields marked `manually_verified: true` are preserved on re-runs.
- Tier 3 analysis items are AI-generated review prompts, not verified findings. They always carry a disclaimer and require human review.
- A large proportion of "MISSING_DATA" entries is expected — many published policy PDFs do not include review date metadata.
