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

echo "[1/7] Tool versions"
echo "  • Nool:   $(nool --version 2>&1 | head -n 1)"
echo "  • Entire: $(entire --version 2>&1 | head -n 1)"
echo "  • Git:    $(git --version)"
echo "  • Python: $(python3 --version 2>&1)"
echo ""

echo "[2/7] Live repository state (read-only)"
git log --oneline --decorate -n 5
echo "  refs/entire/*: $(git show-ref | grep -c 'refs/entire/' || true)   refs/nool/*: $(git show-ref | grep -c 'refs/nool/' || true)"
echo ""

echo "[3/7] Entire line attribution (entire why src/auth.py)"
entire why src/auth.py || true
echo ""

echo "[4/7] Sandboxed benchmark scenarios"
python3 benchmark/run_benchmark.py
echo ""

echo "[5/7] Policy-type probe (secrets, forbidden paths, invariant, Entire checkpoint evidence)"
python3 benchmark/check_policy_types.py
echo ""

echo "[6/7] Regenerating BENCHMARK_COMPARISON.md from the recorded results"
python3 benchmark/render_report.py
echo ""

echo "[7/7] Test suite (evidence assertions reuse the runs from steps 4 and 5)"
BENCH_REUSE_RESULTS=1 python3 -m unittest tests.test_auth tests.test_benchmark tests.test_commit_template tests.test_governance tests.test_entire_checkpoint
echo ""

echo "================================================================="
echo "  Done. Evidence: benchmark/results/latest.json"
echo "  Report:   BENCHMARK_COMPARISON.md"
echo "  Policy probe: benchmark/results/policy-types.json"
echo "  Three expected failures mark known Nool gaps (the provenance"
echo "  invariant, measured twice, is not enforced; semantic same-symbol"
echo "  false negative) — see the report."
echo "================================================================="
