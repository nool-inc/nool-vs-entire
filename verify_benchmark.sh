#!/usr/bin/env bash
# Nool vs Entire vs Plain Git — benchmark verification runbook.
#
# Re-runs the sandboxed benchmark, regenerates BENCHMARK_COMPARISON.md from
# the recorded results, and runs the test suite. Scenarios execute in
# throwaway sandboxes; this repository is only read.
set -euo pipefail
cd "$(dirname "$0")"

echo "================================================================="
echo "  NOOL vs ENTIRE vs PLAIN GIT — BENCHMARK VERIFICATION"
echo "  Repository: $(pwd)"
echo "  Timestamp:  $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "================================================================="
echo ""

echo "[1/6] Tool versions"
echo "  • Nool:   $(nool --version 2>&1 | head -n 1)"
echo "  • Entire: $(entire --version 2>&1 | head -n 1)"
echo "  • Git:    $(git --version)"
echo "  • Python: $(python3 --version 2>&1)"
echo ""

echo "[2/6] Live repository state (read-only)"
git log --oneline --decorate -n 5
echo "  refs/entire/*: $(git show-ref | grep -c 'refs/entire/' || true)   refs/nool/*: $(git show-ref | grep -c 'refs/nool/' || true)"
echo ""

echo "[3/6] Entire line attribution (entire why src/auth.py)"
entire why src/auth.py || true
echo ""

echo "[4/6] Sandboxed benchmark scenarios"
python3 benchmark/run_benchmark.py
echo ""

echo "[5/6] Regenerating BENCHMARK_COMPARISON.md from benchmark/results/latest.json"
python3 benchmark/render_report.py
echo ""

echo "[6/6] Test suite (evidence assertions reuse the run from step 4)"
BENCH_REUSE_RESULTS=1 python3 -m unittest tests.test_auth tests.test_benchmark
echo ""

echo "================================================================="
echo "  Done. Evidence: benchmark/results/latest.json"
echo "  Report:   BENCHMARK_COMPARISON.md"
echo "  Two expected failures mark known Nool gaps (provenance rule not"
echo "  enforced; semantic same-symbol false negative) — see the report."
echo "================================================================="
