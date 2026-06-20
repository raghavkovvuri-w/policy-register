#!/bin/bash
set -e

echo "============================================"
echo " Policy Register - Inspire Education Group"
echo "============================================"
echo ""

echo "[1/5] Fetching policies from public sources..."
python scripts/fetch_policies.py
echo ""

echo "[2/5] Extracting metadata from PDFs..."
python scripts/process_policies.py
echo ""

echo "[3/5] Building register..."
python scripts/build_register.py
echo ""

echo "[4/5] Running analysis..."
python scripts/analyze_policies.py
echo ""

echo "[5/5] Generating dashboard..."
python scripts/generate_dashboard.py
echo ""

echo "============================================"
echo " COMPLETE. Open output/dashboard.html"
echo "============================================"
