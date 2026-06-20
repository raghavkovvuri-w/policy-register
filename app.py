"""
Policy Register Dashboard - Flask Web Application
Serves the policy register dashboard on localhost with authentication.
"""

import json
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, abort

app = Flask(__name__)
app.secret_key = "ieg-policy-register-2026-secret-key"

BASE_DIR = Path(__file__).resolve().parent
REGISTER_PATH = BASE_DIR / "data" / "register" / "policies_register.json"
ANALYSIS_PATH = BASE_DIR / "data" / "register" / "analysis.json"
POLICIES_DIR = BASE_DIR / "data" / "policies"

CREDENTIALS = {"username": "Raghav", "password": "Raghav@123"}

SOURCE_LABELS = {"ieg_central": "IEG", "ucp": "UCP"}
FALSE_MATCH_KEYWORDS = ["entirely different", "not comparable", "unrelated",
                         "different subject matter", "do not overlap"]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def load_json(path):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def deduplicate_policies(policies):
    """Remove exact duplicates only (same name + same source)."""
    seen = set()
    result = []
    for p in policies:
        name = p.get("policy_name", p.get("filename", ""))
        source = p.get("source", "")
        key = (name.strip().lower(), source)
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


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
        label = f"{years}y {months}m" if months > 0 else f"{years} year{'s' if years != 1 else ''}"
    return f"{label} overdue" if days < 0 else f"{label} left"


def is_false_match(comparison):
    summary = comparison.get("comparison", {}).get("summary", "").lower()
    return any(kw in summary for kw in FALSE_MATCH_KEYWORDS)


def get_dashboard_data():
    register = load_json(REGISTER_PATH)
    analysis = load_json(ANALYSIS_PATH)
    if not register:
        return None, None

    policies = deduplicate_policies(register["policies"])
    # Recompute counts after dedup
    counts = {"OVERDUE": 0, "DUE_SOON": 0, "CURRENT": 0, "MISSING_DATA": 0}
    for p in policies:
        counts[p["status"]] = counts.get(p["status"], 0) + 1

    register["policies"] = policies
    register["register_metadata"]["total_policies"] = len(policies)
    register["register_metadata"]["status_counts"] = counts

    return register, analysis


@app.route("/")
def index():
    if session.get("authenticated"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == CREDENTIALS["username"] and password == CREDENTIALS["password"]:
            session["authenticated"] = True
            session["username"] = username
            return redirect(url_for("dashboard"))
        error = "Invalid credentials. Please try again."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    register, analysis = get_dashboard_data()
    if not register:
        return "No register data found. Run the pipeline first.", 500

    policies = register["policies"]
    counts = register["register_metadata"]["status_counts"]

    # Completeness
    completeness = {}
    for p in policies:
        src = friendly_source(p["source"])
        if src not in completeness:
            completeness[src] = {"total": 0, "missing_review": 0, "missing_owner": 0}
        completeness[src]["total"] += 1
        if not p.get("next_review_date") or p["next_review_date"] == "not found":
            completeness[src]["missing_review"] += 1
        if not p.get("owner") or p["owner"] == "not found":
            completeness[src]["missing_owner"] += 1

    # Overdue by source
    overdue_by_source = {}
    for p in policies:
        if p["status"] == "OVERDUE":
            src = friendly_source(p["source"])
            overdue_by_source[src] = overdue_by_source.get(src, 0) + 1

    # Comparisons (filter false matches)
    comparisons = []
    if analysis:
        tier2 = analysis.get("tier2_observations", {}).get("findings", [])
        comparisons = [f for f in tier2 if f["type"] == "group_vs_he_comparison" and not is_false_match(f)]

    # Tier 3 counts
    tier3_items = []
    if analysis:
        tier3_items = analysis.get("tier3_suggestions", {}).get("findings", [])

    # Category breakdown with source split
    categories = {}
    for p in policies:
        for cat in (p.get("categories") or []):
            cat_lower = cat.lower()
            if cat_lower not in categories:
                categories[cat_lower] = {"total": 0, "overdue": 0, "ieg": 0, "ucp": 0}
            categories[cat_lower]["total"] += 1
            if p["status"] == "OVERDUE":
                categories[cat_lower]["overdue"] += 1
            if p.get("source") == "ieg_central":
                categories[cat_lower]["ieg"] += 1
            else:
                categories[cat_lower]["ucp"] += 1

    # Group suggestions by policy
    suggestions_by_policy = {}
    tier3_confidence = {"high": 0, "medium": 0, "low": 0}
    for item in tier3_items:
        key = item.get("policy_name", item.get("source_file", "Unknown"))
        if key not in suggestions_by_policy:
            # Find policy categories from register
            policy_cats = []
            for p in policies:
                if p.get("policy_name") == key or p.get("filename") == item.get("source_file"):
                    policy_cats = p.get("categories", [])
                    break
            suggestions_by_policy[key] = {
                "policy_name": key,
                "source": item.get("source", ""),
                "source_file": item.get("source_file", ""),
                "categories": policy_cats,
                "count": 0,
                "by_confidence": {"high": 0, "medium": 0, "low": 0},
            }
        suggestions_by_policy[key]["count"] += 1
        conf = item.get("confidence", "low")
        suggestions_by_policy[key]["by_confidence"][conf] += 1
        tier3_confidence[conf] += 1

    # Sort by count descending
    suggestions_grouped = sorted(
        suggestions_by_policy.values(), key=lambda x: x["count"], reverse=True
    )

    return render_template("dashboard.html",
                           policies=policies,
                           counts=counts,
                           completeness=completeness,
                           overdue_by_source=overdue_by_source,
                           comparisons=comparisons,
                           tier3_count=len(tier3_items),
                           tier3_confidence=tier3_confidence,
                           suggestions_grouped=suggestions_grouped,
                           categories=categories,
                           friendly_source=friendly_source,
                           friendly_days=friendly_days,
                           username=session.get("username", ""))


@app.route("/api/policies")
@login_required
def api_policies():
    register, _ = get_dashboard_data()
    if not register:
        return jsonify([])
    return jsonify(register["policies"])


@app.route("/api/review")
@login_required
def api_review():
    analysis = load_json(ANALYSIS_PATH)
    if not analysis:
        return jsonify([])
    items = analysis.get("tier3_suggestions", {}).get("findings", [])
    return jsonify(items)


@app.route("/pdf/<source>/<path:filename>")
@login_required
def serve_pdf(source, filename):
    pdf_path = POLICIES_DIR / source / filename
    if not pdf_path.exists():
        abort(404)
    return send_file(pdf_path, mimetype="application/pdf")


@app.route("/viewer")
def view_pdf():
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    source = request.args.get("source", "")
    filename = request.args.get("file", "")
    search_text = request.args.get("search", "")
    if not source or not filename:
        return "Missing source or file parameter", 400
    pdf_url = f"/pdf/{source}/{filename}"
    return render_template("pdfviewer.html",
                           pdf_url=pdf_url,
                           search_text=search_text)


if __name__ == "__main__":
    print("\n  Policy Register Dashboard")
    print("  http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
