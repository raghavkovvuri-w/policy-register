"""
generate_dashboard.py - Generates a self-contained HTML dashboard from the register and analysis data.
Tabbed, action-oriented layout with PDF links and human-friendly labels.
"""

import json
import html
import re
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
REGISTER_PATH = BASE_DIR / "data" / "register" / "policies_register.json"
ANALYSIS_PATH = BASE_DIR / "data" / "register" / "analysis.json"
OUTPUT_PATH = BASE_DIR / "output" / "dashboard.html"

SOURCE_LABELS = {"ieg_central": "IEG Group", "ucp": "UCP (HE)"}
FALSE_MATCH_KEYWORDS = ["entirely different", "not comparable", "unrelated", "entirely unrelated",
                         "different subject matter", "do not overlap"]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def esc(text):
    if text is None:
        return ""
    return html.escape(str(text))


def friendly_source(source):
    return SOURCE_LABELS.get(source, source)


def friendly_days(days):
    if days is None:
        return "No date"
    abs_days = abs(days)
    if abs_days < 30:
        label = f"{abs_days} days"
    elif abs_days < 365:
        months = abs_days // 30
        label = f"{months} month{'s' if months != 1 else ''}"
    else:
        years = abs_days // 365
        months = (abs_days % 365) // 30
        if months > 0:
            label = f"{years}y {months}m"
        else:
            label = f"{years} year{'s' if years != 1 else ''}"
    if days < 0:
        return f"{label} overdue"
    elif days <= 90:
        return f"{label} left"
    else:
        return f"{label} left"


def status_colour(status):
    return {"OVERDUE": "#d32f2f", "DUE_SOON": "#f57c00", "CURRENT": "#388e3c", "MISSING_DATA": "#9e9e9e"}.get(status, "#9e9e9e")


def status_label(status):
    return {"OVERDUE": "Overdue", "DUE_SOON": "Due Soon", "CURRENT": "Current", "MISSING_DATA": "No Date"}.get(status, status)


def is_false_match(comparison):
    summary = comparison.get("comparison", {}).get("summary", "").lower()
    return any(kw in summary for kw in FALSE_MATCH_KEYWORDS)


def generate_html(register, analysis):
    meta = register["register_metadata"]
    policies = register["policies"]
    counts = meta["status_counts"]

    # Completeness stats
    completeness = {}
    for p in policies:
        src = p["source"]
        if src not in completeness:
            completeness[src] = {"total": 0, "missing_review": 0, "missing_owner": 0}
        completeness[src]["total"] += 1
        if not p.get("next_review_date") or p["next_review_date"] == "not found":
            completeness[src]["missing_review"] += 1
        if not p.get("owner") or p["owner"] == "not found":
            completeness[src]["missing_owner"] += 1

    # --- REGISTER TAB: Policy table rows ---
    table_rows = ""
    for p in policies:
        status = p["status"]
        colour = status_colour(status)
        days_text = friendly_days(p.get("days_until_review"))
        cats = ", ".join(p.get("categories", [])[:3]) if p.get("categories") else ""
        review_date = p.get("next_review_date", "")
        if review_date == "not found":
            review_date = "—"

        table_rows += f"""<tr class="policy-row" data-source="{esc(p['source'])}" data-status="{status}" onclick="toggleDetail(this)">
  <td class="pol-name">{esc(p.get('policy_name', p['filename']))}</td>
  <td class="pol-source">{friendly_source(p['source'])}</td>
  <td><span class="status-badge" style="background:{colour}">{status_label(status)}</span></td>
  <td class="pol-days">{days_text}</td>
  <td class="pol-link"><a href="{esc(p.get('url', ''))}" target="_blank" rel="noopener">View PDF</a></td>
</tr>
<tr class="detail-row" style="display:none">
  <td colspan="5">
    <div class="detail-grid">
      <div><strong>Owner:</strong> {esc(p.get('owner', '—'))}</div>
      <div><strong>Review date:</strong> {review_date}</div>
      <div><strong>Approval date:</strong> {esc(p.get('approval_date', '—')) if p.get('approval_date') != 'not found' else '—'}</div>
      <div><strong>Version:</strong> {esc(p.get('version', '—')) if p.get('version') != 'not found' else '—'}</div>
      <div><strong>Frequency:</strong> {esc(p.get('review_frequency', '—')) if p.get('review_frequency') != 'not found' else '—'}</div>
      <div><strong>Categories:</strong> {esc(', '.join(p.get('categories', [])))}</div>
      <div><strong>File:</strong> {esc(p.get('filename', ''))}</div>
    </div>
  </td>
</tr>\n"""

    # --- ACTION TAB: Overdue and due soon ---
    overdue_critical = [p for p in policies if p["status"] == "OVERDUE" and p.get("days_until_review") and p["days_until_review"] < -365]
    overdue_recent = [p for p in policies if p["status"] == "OVERDUE" and p.get("days_until_review") and p["days_until_review"] >= -365]
    due_soon = [p for p in policies if p["status"] == "DUE_SOON"]

    def action_card(p):
        colour = status_colour(p["status"])
        days_text = friendly_days(p.get("days_until_review"))
        owner = p.get("owner", "—") if p.get("owner") != "not found" else "No owner listed"
        return f"""<div class="action-card" style="border-left-color:{colour}">
  <div class="action-header">
    <span class="action-name">{esc(p.get('policy_name', p['filename']))}</span>
    <span class="action-badge" style="background:{colour}">{days_text}</span>
  </div>
  <div class="action-meta">
    <span>{friendly_source(p['source'])}</span>
    <span>Owner: {esc(owner)}</span>
    <a href="{esc(p.get('url', ''))}" target="_blank" rel="noopener">View PDF &rarr;</a>
  </div>
</div>\n"""

    action_html = ""
    if overdue_critical:
        action_html += f'<h3 class="urgency-header urgency-critical">Over 1 Year Overdue ({len(overdue_critical)})</h3>\n'
        for p in overdue_critical:
            action_html += action_card(p)
    if overdue_recent:
        action_html += f'<h3 class="urgency-header urgency-overdue">Under 1 Year Overdue ({len(overdue_recent)})</h3>\n'
        for p in overdue_recent:
            action_html += action_card(p)
    if due_soon:
        action_html += f'<h3 class="urgency-header urgency-soon">Due Within 90 Days ({len(due_soon)})</h3>\n'
        for p in due_soon:
            action_html += action_card(p)

    # --- COMPARISONS TAB: Filter out false matches ---
    comparisons_html = ""
    if analysis:
        tier2 = analysis.get("tier2_observations", {}).get("findings", [])
        group_vs_he = [f for f in tier2 if f["type"] == "group_vs_he_comparison" and not is_false_match(f)]

        if group_vs_he:
            comparisons_html += f'<p class="tab-intro">{len(group_vs_he)} genuine Group vs HE policy comparisons found.</p>\n'
            for i, comp in enumerate(group_vs_he):
                c = comp["comparison"]
                diffs = "".join(f"<li>{esc(d)}</li>" for d in c.get("substantive_differences", []))
                contras = "".join(f"<li>{esc(d)}</li>" for d in c.get("contradictions", []))
                comparisons_html += f"""<details class="comparison-card">
  <summary><strong>{esc(comp['ieg_policy'])}</strong> vs <strong>{esc(comp['ucp_policy'])}</strong></summary>
  <p class="comp-summary">{esc(c.get('summary', ''))}</p>
  {"<h5>Key Differences</h5><ul>" + diffs + "</ul>" if diffs else ""}
  {"<h5>Contradictions</h5><ul class='contradictions'>" + contras + "</ul>" if contras else "<p class='no-issues'>No contradictions identified.</p>"}
</details>\n"""
        else:
            comparisons_html = "<p>No genuine Group vs HE comparisons found.</p>"
    else:
        comparisons_html = "<p>Analysis data not available.</p>"

    # --- REVIEW TAB: Tier 3 items as JSON for pagination ---
    tier3_items = []
    if analysis:
        for item in analysis.get("tier3_suggestions", {}).get("findings", []):
            tier3_items.append({
                "policy": item.get("policy_name", ""),
                "category": item.get("category", ""),
                "observation": item.get("observation", ""),
                "confidence": item.get("confidence", "low"),
                "source": item.get("source", ""),
                "file": item.get("source_file", ""),
            })

    tier3_json = json.dumps(tier3_items, ensure_ascii=False)
    tier3_counts = analysis.get("tier3_suggestions", {}).get("by_confidence", {}) if analysis else {}

    # Completeness bar
    comp_bar = ""
    for src, data in completeness.items():
        if data["total"] == 0:
            continue
        comp_bar += f'<span class="comp-stat"><strong>{friendly_source(src)}:</strong> {data["missing_review"]} missing review date, {data["missing_owner"]} missing owner (of {data["total"]})</span>'

    generated_date = datetime.now().strftime("%d %B %Y")

    dashboard_html = f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Policy Register - Inspire Education Group</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 16px; }}
header {{ background: #1a237e; color: white; padding: 20px 0; }}
header .container {{ display: flex; justify-content: space-between; align-items: center; }}
h1 {{ font-size: 1.4rem; font-weight: 600; }}
.subtitle {{ opacity: 0.8; font-size: 0.85rem; }}

/* Summary cards */
.summary-cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 20px 0; }}
.summary-card {{ background: white; border-radius: 8px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.08); cursor: pointer; transition: transform 0.1s; }}
.summary-card:hover {{ transform: translateY(-2px); box-shadow: 0 3px 8px rgba(0,0,0,0.12); }}
.summary-card .count {{ font-size: 2rem; font-weight: 700; }}
.summary-card .label {{ font-size: 0.8rem; color: #666; }}

/* Tabs */
.tabs {{ display: flex; gap: 0; margin-bottom: 0; background: white; border-radius: 8px 8px 0 0; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }}
.tab-btn {{ padding: 14px 24px; border: none; background: transparent; font-size: 0.9rem; font-weight: 500; cursor: pointer; color: #666; border-bottom: 3px solid transparent; transition: all 0.2s; }}
.tab-btn:hover {{ color: #1a237e; background: #f8f9ff; }}
.tab-btn.active {{ color: #1a237e; border-bottom-color: #1a237e; background: white; }}
.tab-content {{ display: none; background: white; border-radius: 0 0 8px 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.tab-content.active {{ display: block; }}

/* Completeness bar */
.comp-bar {{ background: #fff3e0; border-radius: 6px; padding: 10px 16px; margin-bottom: 16px; font-size: 0.82rem; display: flex; gap: 20px; flex-wrap: wrap; }}
.comp-stat {{ color: #e65100; }}

/* Table */
.filters {{ display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }}
.filters select, .filters input {{ padding: 7px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.85rem; }}
.filters input {{ min-width: 200px; flex: 1; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ background: #f8f9fa; padding: 10px 8px; text-align: left; font-weight: 600; border-bottom: 2px solid #e0e0e0; cursor: pointer; user-select: none; }}
th:hover {{ background: #e8eaf6; }}
td {{ padding: 10px 8px; border-bottom: 1px solid #f0f0f0; }}
.policy-row {{ cursor: pointer; }}
.policy-row:hover {{ background: #f8f9ff; }}
.pol-link a {{ color: #1565c0; text-decoration: none; font-size: 0.8rem; }}
.pol-link a:hover {{ text-decoration: underline; }}
.status-badge {{ display: inline-block; padding: 3px 10px; border-radius: 12px; color: white; font-size: 0.72rem; font-weight: 600; }}
.detail-row td {{ padding: 0; }}
.detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; padding: 12px 16px; background: #fafbfc; border-left: 3px solid #1a237e; font-size: 0.82rem; }}

/* Action tab */
.urgency-header {{ font-size: 0.95rem; padding: 12px 0 8px; border-bottom: 1px solid #eee; margin-top: 16px; }}
.urgency-header:first-child {{ margin-top: 0; }}
.urgency-critical {{ color: #b71c1c; }}
.urgency-overdue {{ color: #d32f2f; }}
.urgency-soon {{ color: #f57c00; }}
.action-card {{ border: 1px solid #eee; border-left: 4px solid #d32f2f; border-radius: 6px; padding: 12px 16px; margin: 8px 0; }}
.action-header {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; }}
.action-name {{ font-weight: 600; font-size: 0.9rem; }}
.action-badge {{ padding: 3px 10px; border-radius: 12px; color: white; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }}
.action-meta {{ display: flex; gap: 16px; margin-top: 6px; font-size: 0.8rem; color: #666; flex-wrap: wrap; }}
.action-meta a {{ color: #1565c0; text-decoration: none; }}
.action-meta a:hover {{ text-decoration: underline; }}

/* Comparisons */
.tab-intro {{ color: #666; font-size: 0.85rem; margin-bottom: 16px; }}
.comparison-card {{ border: 1px solid #e0e0e0; border-radius: 6px; margin-bottom: 10px; }}
.comparison-card summary {{ padding: 12px 16px; cursor: pointer; font-size: 0.9rem; }}
.comparison-card summary:hover {{ background: #f8f9ff; }}
.comparison-card[open] summary {{ border-bottom: 1px solid #eee; background: #f8f9ff; }}
.comparison-card > *:not(summary) {{ padding: 0 16px; }}
.comparison-card h5 {{ margin-top: 12px; font-size: 0.85rem; color: #1a237e; }}
.comparison-card ul {{ margin: 6px 0 12px 20px; font-size: 0.82rem; }}
.comparison-card li {{ margin-bottom: 4px; }}
.contradictions li {{ color: #c62828; }}
.comp-summary {{ color: #555; font-style: italic; font-size: 0.83rem; margin: 10px 0; padding: 0 16px; }}
.no-issues {{ color: #388e3c; font-style: italic; font-size: 0.83rem; padding: 8px 16px; }}

/* Review suggestions */
.review-controls {{ display: flex; gap: 10px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
.review-controls select {{ padding: 7px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.85rem; }}
.review-controls .page-info {{ margin-left: auto; font-size: 0.82rem; color: #666; }}
.review-controls button {{ padding: 6px 14px; border: 1px solid #ddd; border-radius: 4px; background: white; cursor: pointer; font-size: 0.85rem; }}
.review-controls button:hover {{ background: #f0f0f0; }}
.review-controls button:disabled {{ opacity: 0.4; cursor: default; }}
.review-item {{ border: 1px solid #eee; border-radius: 6px; padding: 12px 16px; margin-bottom: 8px; border-left: 4px solid #9e9e9e; }}
.review-item.conf-high {{ border-left-color: #d32f2f; }}
.review-item.conf-medium {{ border-left-color: #f57c00; }}
.review-item .ri-header {{ display: flex; gap: 8px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }}
.review-item .ri-cat {{ background: #e3f2fd; color: #1565c0; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }}
.review-item .ri-conf {{ font-size: 0.72rem; padding: 2px 6px; border-radius: 3px; background: #f5f5f5; color: #666; }}
.review-item .ri-policy {{ font-weight: 500; font-size: 0.85rem; }}
.review-item .ri-obs {{ font-size: 0.83rem; color: #333; }}
.review-item .ri-disclaimer {{ font-size: 0.72rem; color: #999; font-style: italic; margin-top: 6px; }}

footer {{ text-align: center; padding: 20px; color: #999; font-size: 0.75rem; margin-top: 20px; }}

@media (max-width: 768px) {{
  .summary-cards {{ grid-template-columns: repeat(3, 1fr); }}
  .tabs {{ overflow-x: auto; }}
  .tab-btn {{ padding: 12px 16px; font-size: 0.8rem; white-space: nowrap; }}
  .detail-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<header>
<div class="container">
  <div><h1>Policy Register</h1><p class="subtitle">Inspire Education Group</p></div>
  <div class="subtitle">{generated_date}</div>
</div>
</header>

<div class="container">

<!-- Summary -->
<div class="summary-cards">
  <div class="summary-card" onclick="filterByStatus('')"><div class="count">{meta['total_policies']}</div><div class="label">Total</div></div>
  <div class="summary-card" onclick="filterByStatus('OVERDUE')"><div class="count" style="color:#d32f2f">{counts.get('OVERDUE', 0)}</div><div class="label">Overdue</div></div>
  <div class="summary-card" onclick="filterByStatus('DUE_SOON')"><div class="count" style="color:#f57c00">{counts.get('DUE_SOON', 0)}</div><div class="label">Due Soon</div></div>
  <div class="summary-card" onclick="filterByStatus('CURRENT')"><div class="count" style="color:#388e3c">{counts.get('CURRENT', 0)}</div><div class="label">Current</div></div>
  <div class="summary-card" onclick="filterByStatus('MISSING_DATA')"><div class="count" style="color:#9e9e9e">{counts.get('MISSING_DATA', 0)}</div><div class="label">No Date</div></div>
</div>

<!-- Tabs -->
<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('register')">Register</button>
  <button class="tab-btn" onclick="switchTab('action')">Action Required <span style="background:#d32f2f;color:white;padding:1px 6px;border-radius:8px;font-size:0.7rem;margin-left:4px">{counts.get('OVERDUE', 0) + counts.get('DUE_SOON', 0)}</span></button>
  <button class="tab-btn" onclick="switchTab('comparisons')">Comparisons</button>
  <button class="tab-btn" onclick="switchTab('review')">Review Suggestions</button>
</div>

<!-- Register Tab -->
<div id="tab-register" class="tab-content active">
  <div class="comp-bar">{comp_bar}</div>
  <div class="filters">
    <input type="text" id="searchInput" placeholder="Search policies..." oninput="filterTable()">
    <select id="sourceFilter" onchange="filterTable()">
      <option value="">All Sources</option>
      <option value="ieg_central">IEG Group</option>
      <option value="ucp">UCP (HE)</option>
    </select>
    <select id="statusFilter" onchange="filterTable()">
      <option value="">All Statuses</option>
      <option value="OVERDUE">Overdue</option>
      <option value="DUE_SOON">Due Soon</option>
      <option value="CURRENT">Current</option>
      <option value="MISSING_DATA">No Date</option>
    </select>
  </div>
  <div style="overflow-x:auto;">
  <table id="policyTable">
    <thead><tr>
      <th onclick="sortTable(0)">Policy</th>
      <th onclick="sortTable(1)">Source</th>
      <th onclick="sortTable(2)">Status</th>
      <th onclick="sortTable(3)">Review</th>
      <th>PDF</th>
    </tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
  </div>
</div>

<!-- Action Tab -->
<div id="tab-action" class="tab-content">
  <p class="tab-intro">Policies requiring immediate attention, grouped by urgency.</p>
  {action_html}
</div>

<!-- Comparisons Tab -->
<div id="tab-comparisons" class="tab-content">
  {comparisons_html}
</div>

<!-- Review Tab -->
<div id="tab-review" class="tab-content">
  <p class="tab-intro">AI-generated prompts for governance review. These are suggestions for human checking, not verified findings. {len(tier3_items)} items total.</p>
  <div class="review-controls">
    <select id="confFilter" onchange="renderReview()">
      <option value="">All Confidence</option>
      <option value="high">High</option>
      <option value="medium">Medium</option>
      <option value="low">Low</option>
    </select>
    <select id="catFilter" onchange="renderReview()">
      <option value="">All Categories</option>
      <option value="superseded_reference">Superseded Reference</option>
      <option value="ambiguity">Ambiguity</option>
      <option value="contradiction">Contradiction</option>
      <option value="missing_cross_reference">Missing Cross-Reference</option>
    </select>
    <button onclick="prevPage()" id="prevBtn" disabled>&laquo; Prev</button>
    <span class="page-info" id="pageInfo"></span>
    <button onclick="nextPage()" id="nextBtn">Next &raquo;</button>
  </div>
  <div id="reviewItems"></div>
</div>

</div>

<footer>Generated {generated_date} &middot; Policy Register v2 &middot; AI-assisted, for governance review only</footer>

<script>
// Tab switching
function switchTab(id) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  event.currentTarget.classList.add('active');
}}

// Summary card click -> switch to register + filter
function filterByStatus(status) {{
  switchTabDirect('register');
  document.getElementById('statusFilter').value = status;
  filterTable();
}}
function switchTabDirect(id) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  document.querySelector('.tab-btn').classList.add('active');
}}

// Table filter
function filterTable() {{
  const search = document.getElementById('searchInput').value.toLowerCase();
  const source = document.getElementById('sourceFilter').value;
  const status = document.getElementById('statusFilter').value;
  const rows = document.querySelectorAll('.policy-row');
  rows.forEach(row => {{
    const text = row.textContent.toLowerCase();
    const rSource = row.dataset.source;
    const rStatus = row.dataset.status;
    const show = (!search || text.includes(search)) && (!source || rSource === source) && (!status || rStatus === status);
    row.style.display = show ? '' : 'none';
    row.nextElementSibling.style.display = 'none'; // hide detail
  }});
}}

// Row expand
function toggleDetail(row) {{
  const detail = row.nextElementSibling;
  detail.style.display = detail.style.display === 'none' ? '' : 'none';
}}

// Sort
function sortTable(col) {{
  const table = document.getElementById('policyTable');
  const tbody = table.querySelector('tbody');
  const pairs = [];
  const rows = tbody.querySelectorAll('.policy-row');
  rows.forEach(r => pairs.push([r, r.nextElementSibling]));
  const dir = table.dataset.sortDir === 'asc' ? 'desc' : 'asc';
  table.dataset.sortDir = dir;
  pairs.sort((a, b) => {{
    let av = a[0].cells[col].textContent.trim();
    let bv = b[0].cells[col].textContent.trim();
    return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  pairs.forEach(([r, d]) => {{ tbody.appendChild(r); tbody.appendChild(d); }});
}}

// Review suggestions pagination
const tier3Data = {tier3_json};
let reviewPage = 0;
const PAGE_SIZE = 20;

function getFiltered() {{
  const conf = document.getElementById('confFilter').value;
  const cat = document.getElementById('catFilter').value;
  return tier3Data.filter(item => (!conf || item.confidence === conf) && (!cat || item.category === cat));
}}

function renderReview() {{
  reviewPage = 0;
  showPage();
}}

function showPage() {{
  const filtered = getFiltered();
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE) || 1;
  const start = reviewPage * PAGE_SIZE;
  const page = filtered.slice(start, start + PAGE_SIZE);

  let html = '';
  page.forEach(item => {{
    html += '<div class="review-item conf-' + item.confidence + '">';
    html += '<div class="ri-header"><span class="ri-cat">' + esc(item.category) + '</span>';
    html += '<span class="ri-conf">' + item.confidence + '</span>';
    html += '<span class="ri-policy">' + esc(item.policy) + '</span></div>';
    html += '<p class="ri-obs">' + esc(item.observation) + '</p>';
    html += '<p class="ri-disclaimer">AI-generated prompt for governance review. Requires human verification.</p>';
    html += '</div>';
  }});

  document.getElementById('reviewItems').innerHTML = html || '<p style="color:#666">No items match the current filters.</p>';
  document.getElementById('pageInfo').textContent = 'Page ' + (reviewPage + 1) + ' of ' + totalPages + ' (' + filtered.length + ' items)';
  document.getElementById('prevBtn').disabled = reviewPage === 0;
  document.getElementById('nextBtn').disabled = reviewPage >= totalPages - 1;
}}

function prevPage() {{ reviewPage--; showPage(); }}
function nextPage() {{ reviewPage++; showPage(); }}
function esc(s) {{ const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }}

renderReview();
</script>
</body>
</html>"""
    return dashboard_html


def main():
    register = load_json(REGISTER_PATH)
    analysis = None
    if ANALYSIS_PATH.exists():
        analysis = load_json(ANALYSIS_PATH)

    dashboard = generate_html(register, analysis)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(dashboard)

    logger.info(f"Dashboard generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
