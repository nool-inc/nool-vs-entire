"""Nool vs Entire CLI empirical benchmark tests.

Covers CLI availability, git refs coexistence, causal DAG traversal,
line-level attribution, conflict detection, and repository health.
Tests are defensive: network/login-dependent commands are skipped
gracefully when credentials are not configured.
"""

import json
import os
import subprocess
import unittest

NOOL = "nool"
ENTIRE = "entire"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, cwd=REPO, timeout=120):
    """Run a command, returning (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"command timed out: {' '.join(cmd)}"


# --- live-checkout preconditions -------------------------------------------
# Some checks are evidence about *this* working copy (its uncommitted nool.toml,
# untracked policies/, its knot ledger, its Entire refs). Nool's gate re-runs
# the suite in a shadow worktree built from the DAG, where those do not exist;
# there the checks skip with a stated reason instead of failing.
LIVE_KNOT = "77d3bf0c"


def _live_ledger_has_knot():
    rc, out, _ = run([NOOL, "log"])
    return rc == 0 and LIVE_KNOT in out


def _live_aram_configured():
    try:
        with open(os.path.join(REPO, "nool.toml")) as f:
            cfg = f.read()
    except OSError:
        return False
    return ("require_entire_provenance" in cfg
            and os.path.exists(os.path.join(REPO, "policies", "entire_policy_test.wasm")))


requires_live_ledger = unittest.skipUnless(
    _live_ledger_has_knot(), f"live ledger with knot {LIVE_KNOT} not present (e.g. Nool shadow worktree)")
requires_live_aram = unittest.skipUnless(
    _live_aram_configured(), "uncommitted provenance rule / untracked policies/ not present in this checkout")


def cli_available(name):
    rc, _, _ = run([name, "--version"])
    return rc == 0


class NoolCliTests(unittest.TestCase):
    """Nool CLI availability and core commands."""

    def test_nool_version(self):
        rc, out, err = run([NOOL, "--version"])
        self.assertEqual(rc, 0, f"`nool --version` failed: {err}")
        self.assertIn("7.23.0", out, f"unexpected nool version output: {out}")

    def test_nool_status(self):
        rc, out, err = run([NOOL, "status"])
        self.assertEqual(rc, 0, f"`nool status` failed: {err}")
        self.assertIn("Total Knots", out)
        self.assertIn("DAG Heads", out)

    @requires_live_ledger
    def test_nool_why_causal_dag(self):
        rc, out, err = run([NOOL, "why", "77d3bf0c"])
        self.assertEqual(rc, 0, f"`nool why` failed: {err}")
        self.assertIn("Causal Chain", out)
        self.assertIn("77d3bf0c", out)
        self.assertIn("unify OAuth2 and SAML authentication", out)

    def test_nool_doctor(self):
        rc, out, err = run([NOOL, "doctor"], timeout=180)
        # doctor may return non-zero when not releasable; that is acceptable
        # as long as the command runs and emits a health report.
        self.assertIn(rc, (0, 1, 2), f"`nool doctor` unexpected rc={rc}: {err}")
        combined = out + err
        self.assertIn("Health Grade", combined)


class EntireCliTests(unittest.TestCase):
    """Entire CLI availability and core commands."""

    def test_entire_version(self):
        rc, out, err = run([ENTIRE, "--version"])
        self.assertEqual(rc, 0, f"`entire --version` failed: {err}")
        self.assertIn("0.12.2", out, f"unexpected entire version output: {out}")

    def test_entire_status(self):
        rc, out, err = run([ENTIRE, "status"])
        self.assertEqual(rc, 0, f"`entire status` failed: {err}")
        self.assertIn("Enabled", out)

    def test_entire_doctor(self):
        rc, out, err = run([ENTIRE, "doctor"])
        self.assertEqual(rc, 0, f"`entire doctor` failed: {err}")
        self.assertIn("OK", out)

    def test_entire_why_line_attribution(self):
        rc, out, err = run([ENTIRE, "why", "src/auth.py"])
        self.assertEqual(rc, 0, f"`entire why` failed: {err}")
        self.assertIn("src/auth.py", out)
        self.assertIn("linked to a checkpoint", out)


class GitRefsCoexistenceTests(unittest.TestCase):
    """Both tools must coexist without polluting each other's git ref namespace."""

    def test_nool_refs_present(self):
        rc, out, err = run(["git", "show-ref"])
        self.assertEqual(rc, 0, f"`git show-ref` failed: {err}")
        self.assertIn("refs/nool", out, "expected refs/nool namespace")
        self.assertTrue(any(line.split()[-1].startswith("refs/nool/mirror/")
                            for line in out.splitlines()),
                        "expected a per-branch Nool mirror pointer")
        # refs/nool/git-mirror is a legacy alias, not required in a fresh clone.

    def test_entire_refs_present(self):
        rc, out, err = run(["git", "show-ref"])
        self.assertEqual(rc, 0, f"`git show-ref` failed: {err}")
        self.assertIn("refs/entire/checkpoints", out, "expected refs/entire/checkpoints namespace")

    def test_no_ref_namespace_collision(self):
        rc, out, err = run(["git", "show-ref"])
        self.assertEqual(rc, 0, f"`git show-ref` failed: {err}")
        nool_lines = [l for l in out.splitlines() if "refs/nool" in l]
        entire_lines = [l for l in out.splitlines() if "refs/entire" in l]
        self.assertGreater(len(nool_lines), 0, "no nool refs found")
        self.assertGreater(len(entire_lines), 0, "no entire refs found")
        # No shared ref paths between the two namespaces.
        nool_set = set(l.split()[-1] for l in nool_lines)
        entire_set = set(l.split()[-1] for l in entire_lines)
        self.assertEqual(nool_set & entire_set, set(), "ref namespace collision detected")


class ConflictDetectionTests(unittest.TestCase):
    """Nool proactive conflict detection vs Entire reactive attribution."""

    def test_nool_discover_conflicts_json(self):
        rc, out, err = run([NOOL, "discover", "conflicts", "file:src/auth.py",
                            "--as-agent", "benchmark-agent", "--json"])
        # rc==0 means no conflicts; rc==3 means conflicts detected (both valid)
        self.assertIn(rc, (0, 3), f"`nool discover conflicts` unexpected rc={rc}: {err}")
        data = json.loads(out)
        self.assertIn("has_conflicts", data)
        self.assertIn("target_nodes", data)
        self.assertIn("conflicts", data)
        self.assertIsInstance(data["conflicts"], list)
        # Consistency: has_conflicts must match whether any conflicts are listed
        self.assertEqual(data["has_conflicts"], len(data["conflicts"]) > 0)
        if rc == 3:
            # When conflicts exist, each conflict must name overlapping nodes
            for c in data["conflicts"]:
                self.assertIn("overlapping_nodes", c)
                self.assertIsInstance(c["overlapping_nodes"], list)
                self.assertIn("expires_hlc", c)

    def test_entire_why_stores_session_prompts(self):
        rc, out, err = run([ENTIRE, "why", "src/auth.py"])
        # line-level attribution may or may not resolve depending on checkpoint coverage
        self.assertIn(rc, (0, 1), f"`entire why <file>` unexpected rc={rc}: {err}")
        self.assertIn("src/auth.py", out)

    def test_entire_why_links_to_checkpoints(self):
        rc, out, err = run([ENTIRE, "why", "src/auth.py"])
        self.assertEqual(rc, 0, f"`entire why` failed: {err}")
        self.assertIn("linked to a checkpoint", out)


@requires_live_aram
class NoolAramEnforcementTests(unittest.TestCase):
    """Nool ARAM/WASM enforcement of Entire checkpoint provenance."""

    def test_aram_policy_loaded(self):
        """The Entire provenance WASM policy is detected at the configured policies_path."""
        rc, out, err = run([NOOL, "doctor"], timeout=180)
        # doctor returns non-zero when not releasable; what matters is policy detection in output
        self.assertIn(rc, (0, 1, 2), f"`nool doctor` unexpected rc={rc}: {err}")
        combined = out + err
        self.assertIn("entire_policy_test.wasm", combined,
                      "ARAM policy entire_policy_test.wasm not detected at policies_path")

    def test_aram_invariant_rule_configured(self):
        """The require_entire_provenance invariant rule is defined in nool.toml."""
        config_path = os.path.join(REPO, "nool.toml")
        with open(config_path) as f:
            config = f.read()
        self.assertIn("require_entire_provenance", config,
                      "require_entire_provenance invariant rule not defined in nool.toml")
        self.assertIn("has_metadata('is_ai_agent')", config,
                      "ARAM rule when_pattern not configured")
        self.assertIn("has_link('entire_checkpoint')", config,
                      "ARAM rule then_requirement not configured")
        self.assertIn('rules = ["require_entire_provenance"]', config,
                      "ARAM rule not added to active rules list")


class NoolTryBranchTests(unittest.TestCase):
    """Nool try branch lifecycle: new, list, show, worktree (with cleanup)."""

    TRY_NAME = "benchmark-try-branch"

    @classmethod
    def tearDownClass(cls):
        run([NOOL, "try", "discard", cls.TRY_NAME])

    def test_nool_try_new(self):
        # Clean up any leftover branch from a previous run
        run([NOOL, "try", "discard", self.TRY_NAME])
        rc, out, err = run([NOOL, "try", "new", self.TRY_NAME])
        self.assertEqual(rc, 0, f"`nool try new` failed: {err}")
        self.assertIn("Created try branch", out)
        self.assertIn(self.TRY_NAME, out)

    def test_nool_try_list_shows_branch(self):
        # Ensure branch exists
        run([NOOL, "try", "new", self.TRY_NAME])
        rc, out, err = run([NOOL, "try", "list"])
        self.assertEqual(rc, 0, f"`nool try list` failed: {err}")
        self.assertIn(self.TRY_NAME, out)
        self.assertIn("active", out.lower())

    def test_nool_try_show_details(self):
        run([NOOL, "try", "new", self.TRY_NAME])
        rc, out, err = run([NOOL, "try", "show", self.TRY_NAME])
        self.assertEqual(rc, 0, f"`nool try show` failed: {err}")
        self.assertIn("Try Branch:", out)
        self.assertIn(self.TRY_NAME, out)

    def test_nool_try_worktree_materializes(self):
        run([NOOL, "try", "new", self.TRY_NAME])
        rc, out, err = run([NOOL, "try", "worktree", self.TRY_NAME])
        self.assertEqual(rc, 0, f"`nool try worktree` failed: {err}")
        self.assertIn("Worktree:", out)
        self.assertIn(".nool/try", out)
        # Verify the git worktree exists
        rc2, out2, err2 = run(["git", "worktree", "list"])
        self.assertEqual(rc2, 0, f"`git worktree list` failed: {err2}")
        self.assertIn(f".nool/try/{self.TRY_NAME}", out2)

    def test_nool_try_discard_cleans_up(self):
        run([NOOL, "try", "new", self.TRY_NAME])
        run([NOOL, "try", "worktree", self.TRY_NAME])
        rc, out, err = run([NOOL, "try", "discard", self.TRY_NAME])
        self.assertEqual(rc, 0, f"`nool try discard` failed: {err}")
        self.assertIn("Discarded", out)
        # Verify worktree removed
        rc2, out2, err2 = run(["git", "worktree", "list"])
        self.assertEqual(rc2, 0, f"`git worktree list` failed: {err2}")
        self.assertNotIn(f".nool/try/{self.TRY_NAME}", out2)


class NoolFleetTests(unittest.TestCase):
    """Nool fleet planning: wave partition, capacity, architecture advice."""

    def test_nool_fleet_capacity(self):
        rc, out, err = run([NOOL, "fleet", "capacity"])
        self.assertEqual(rc, 0, f"`nool fleet capacity` failed: {err}")
        self.assertIn("Ceiling", out)
        self.assertIn("CPU", out)
        self.assertIn("Memory", out)
        self.assertIn("Disk", out)

    def test_nool_fleet_plan(self):
        rc, out, err = run([NOOL, "fleet", "plan",
                            "--task", "id=t1,nodes=src/auth.py: implement oauth helper"])
        self.assertEqual(rc, 0, f"`nool fleet plan` failed: {err}")
        self.assertIn("Fleet plan", out)
        self.assertIn("wave", out.lower())

    def test_nool_fleet_advise(self):
        rc, out, err = run([NOOL, "fleet", "advise",
                            "--task", "id=t1,nodes=src/auth.py: implement oauth helper",
                            "--task", "id=t2,nodes=src/auth.py: implement saml helper"])
        self.assertEqual(rc, 0, f"`nool fleet advise` failed: {err}")
        self.assertIn("Recommended architecture", out)


class UnitTestExecutionTests(unittest.TestCase):
    """The existing Python unit test suite must keep passing."""

    def test_auth_unit_tests_pass(self):
        rc, out, err = run(["python3", "-m", "unittest", "tests.test_auth", "-v"])
        self.assertEqual(rc, 0, f"unit tests failed rc={rc}: {err}")
        combined = out + err
        self.assertIn("OK", combined, f"no OK in unit test output: {combined}")


class CoexistenceE2ETests(unittest.TestCase):
    """End-to-end: both tools operate on the same repo without interference."""

    def test_both_clis_report_healthy(self):
        nool_rc, _, _ = run([NOOL, "status"])
        entire_rc, _, _ = run([ENTIRE, "status"])
        self.assertEqual(nool_rc, 0, "nool status not healthy")
        self.assertEqual(entire_rc, 0, "entire status not healthy")

    def test_entire_settings_file_exists(self):
        settings = os.path.join(REPO, ".entire", "settings.json")
        self.assertTrue(os.path.exists(settings), ".entire/settings.json missing")

    def test_nool_config_file_exists(self):
        config = os.path.join(REPO, "nool.toml")
        self.assertTrue(os.path.exists(config), "nool.toml missing")


class NoolReadOnlyCommandTests(unittest.TestCase):
    """Nool read-only CLI commands that don't require network or auth."""

    @requires_live_ledger
    def test_nool_log(self):
        rc, out, err = run([NOOL, "log"])
        self.assertEqual(rc, 0, f"`nool log` failed: {err}")
        self.assertIn("77d3bf0c", out)

    def test_nool_dag(self):
        rc, out, err = run([NOOL, "dag"])
        self.assertEqual(rc, 0, f"`nool dag` failed: {err}")

    @requires_live_ledger
    def test_nool_diff(self):
        rc, out, err = run([NOOL, "diff", "77d3bf0c"])
        self.assertEqual(rc, 0, f"`nool diff <knot>` failed: {err}")

    def test_nool_compare(self):
        rc, out, err = run([NOOL, "compare", "main", "feature-oauth"])
        # compare may fail if branches don't have comparable knots; valid either way
        self.assertIn(rc, (0, 1), f"`nool compare` unexpected rc={rc}: {err}")

    def test_nool_outline(self):
        rc, out, err = run([NOOL, "outline", "src/auth.py"])
        self.assertEqual(rc, 0, f"`nool outline` failed: {err}")
        self.assertIn("AuthService", out)

    def test_nool_show(self):
        rc, out, err = run([NOOL, "show", "src/auth.py::AuthService"])
        self.assertEqual(rc, 0, f"`nool show` failed: {err}")
        self.assertIn("authenticate", out.lower())

    def test_nool_context(self):
        rc, out, err = run([NOOL, "context", "OAuth2 authentication"])
        self.assertEqual(rc, 0, f"`nool context` failed: {err}")

    def test_nool_ground(self):
        rc, out, err = run([NOOL, "ground", "which command handles the deploy subcommand"])
        self.assertEqual(rc, 0, f"`nool ground` failed: {err}")

    def test_nool_debug(self):
        rc, out, err = run([NOOL, "debug", "--help"])
        self.assertEqual(rc, 0, f"`nool debug --help` failed: {err}")

    def test_nool_languages(self):
        rc, out, err = run([NOOL, "languages"])
        self.assertEqual(rc, 0, f"`nool languages` failed: {err}")

    def test_nool_prune(self):
        rc, out, err = run([NOOL, "prune", "--help"])
        self.assertEqual(rc, 0, f"`nool prune --help` failed: {err}")

    def test_nool_migrate(self):
        rc, out, err = run([NOOL, "migrate", "--help"])
        self.assertEqual(rc, 0, f"`nool migrate --help` failed: {err}")

    def test_nool_thread(self):
        rc, out, err = run([NOOL, "thread", "list"])
        self.assertEqual(rc, 0, f"`nool thread list` failed: {err}")

    def test_nool_task(self):
        rc, out, err = run([NOOL, "task", "list"])
        self.assertEqual(rc, 0, f"`nool task list` failed: {err}")

    def test_nool_checkpoint(self):
        rc, out, err = run([NOOL, "checkpoint", "--help"])
        self.assertEqual(rc, 0, f"`nool checkpoint --help` failed: {err}")

    def test_nool_tag(self):
        rc, out, err = run([NOOL, "tag", "--help"])
        self.assertEqual(rc, 0, f"`nool tag --help` failed: {err}")

    def test_nool_merge_help(self):
        rc, out, err = run([NOOL, "merge", "--help"])
        self.assertEqual(rc, 0, f"`nool merge --help` failed: {err}")

    def test_nool_validate(self):
        rc, out, err = run([NOOL, "validate", "--all"])
        self.assertEqual(rc, 0, f"`nool validate --all` failed: {err}")

    def test_nool_insights(self):
        rc, out, err = run([NOOL, "insights"])
        self.assertEqual(rc, 0, f"`nool insights` failed: {err}")

    def test_nool_usage(self):
        rc, out, err = run([NOOL, "usage"])
        self.assertEqual(rc, 0, f"`nool usage` failed: {err}")

    def test_nool_config(self):
        rc, out, err = run([NOOL, "config", "--help"])
        self.assertEqual(rc, 0, f"`nool config --help` failed: {err}")

    def test_nool_completion(self):
        rc, out, err = run([NOOL, "completion", "bash"])
        self.assertEqual(rc, 0, f"`nool completion bash` failed: {err}")

    def test_nool_help(self):
        rc, out, err = run([NOOL, "help"])
        self.assertEqual(rc, 0, f"`nool help` failed: {err}")


class NoolCandidateQueueTests(unittest.TestCase):
    """Nool candidate queue is inspectable (the propose/solidify write path is exercised in the sandboxed harness)."""

    def test_nool_candidate(self):
        rc, out, err = run([NOOL, "candidate", "list"])
        self.assertEqual(rc, 0, f"`nool candidate list` failed: {err}")


class EntireLocalCommandTests(unittest.TestCase):
    """Entire CLI commands that work locally without network/auth."""

    def test_entire_enable(self):
        rc, out, err = run([ENTIRE, "enable", "--help"])
        self.assertEqual(rc, 0, f"`entire enable --help` failed: {err}")

    def test_entire_agent_list(self):
        rc, out, err = run([ENTIRE, "agent", "list"])
        self.assertEqual(rc, 0, f"`entire agent list` failed: {err}")

    def test_entire_clean(self):
        rc, out, err = run([ENTIRE, "clean", "--help"])
        self.assertEqual(rc, 0, f"`entire clean --help` failed: {err}")

    def test_entire_configure(self):
        rc, out, err = run([ENTIRE, "configure", "--help"])
        self.assertEqual(rc, 0, f"`entire configure --help` failed: {err}")

    def test_entire_disable(self):
        rc, out, err = run([ENTIRE, "disable", "--help"])
        self.assertEqual(rc, 0, f"`entire disable --help` failed: {err}")

    def test_entire_plugin_list(self):
        rc, out, err = run([ENTIRE, "plugin", "list"])
        self.assertEqual(rc, 0, f"`entire plugin list` failed: {err}")

    def test_entire_checkpoint(self):
        rc, out, err = run([ENTIRE, "checkpoint", "list"])
        self.assertEqual(rc, 0, f"`entire checkpoint list` failed: {err}")

    def test_entire_dispatch(self):
        rc, out, err = run([ENTIRE, "dispatch", "--help"])
        self.assertEqual(rc, 0, f"`entire dispatch --help` failed: {err}")

    def test_entire_session(self):
        rc, out, err = run([ENTIRE, "session", "list"])
        self.assertEqual(rc, 0, f"`entire session list` failed: {err}")

    def test_entire_agent_help(self):
        rc, out, err = run([ENTIRE, "agent-help"])
        self.assertEqual(rc, 0, f"`entire agent-help` failed: {err}")

    def test_entire_help(self):
        rc, out, err = run([ENTIRE, "help"])
        self.assertEqual(rc, 0, f"`entire help` failed: {err}")


class BenchmarkEvidenceTests(unittest.TestCase):
    """Assertions over the sandboxed harness (benchmark/run_benchmark.py).

    The harness builds throwaway sandboxes; it never commits, merges, announces
    or proposes in this repository. Set BENCH_REUSE_RESULTS=1 to assert against
    the existing benchmark/results/latest.json instead of re-running it.
    """

    @classmethod
    def setUpClass(cls):
        results = os.path.join(REPO, "benchmark", "results", "latest.json")
        if os.environ.get("BENCH_REUSE_RESULTS") != "1" or not os.path.exists(results):
            rc, out, err = run(["python3", os.path.join(REPO, "benchmark", "run_benchmark.py")], timeout=900)
            if rc != 0:
                raise RuntimeError(f"benchmark harness failed rc={rc}: {err or out}")
        with open(results) as f:
            cls.s = json.load(f)["scenarios"]
        for key, val in cls.s.items():
            if "error" in val and "skipped" not in val:
                raise RuntimeError(f"scenario {key} errored: {val['error']}")

    def _need(self, key):
        if "skipped" in self.s[key]:
            self.skipTest(self.s[key]["skipped"])

    def _need_live_refs(self):
        if self.s["live_repo"].get("entire_ref_count", 0) == 0:
            self.skipTest("no refs/entire/* in this checkout (e.g. Nool shadow worktree)")

    # Merge after the fact ------------------------------------------------
    def test_plain_git_conflicts_on_concurrent_edits(self):
        g = self.s["plain_git_disjoint"]
        self.assertNotEqual(g["merge_rc"], 0)
        self.assertGreater(g["result"]["conflict_markers"], 0)
        self.assertTrue(g["manual_resolution_required"])

    def test_entire_adds_no_merge_hook_and_conflicts_like_git(self):
        e = self.s["entire_disjoint"]
        self.assertTrue(e["enabled"])
        self.assertFalse(e["has_merge_hook"])
        self.assertNotEqual(e["merge_rc"], 0)

    def test_nool_merges_disjoint_edits_without_markers(self):
        n = self.s["nool_merge_disjoint"]
        self.assertEqual(n["merge_rc"], [0, 0])
        self.assertEqual(n["result"]["conflict_markers"], 0)
        self.assertIn("authenticate_oauth", n["result"]["methods"])
        self.assertIn("authenticate_saml", n["result"]["methods"])
        self.assertTrue(n["tests_pass_without_manual_edit"])

    def test_nool_does_not_silently_union_same_symbol_edits(self):
        n = self.s["nool_merge_same_symbol"]
        self.assertTrue(n["manual_resolution_required"])
        self.assertFalse(n["union_reconciled"])

    @unittest.expectedFailure
    def test_nool_semantic_engine_flags_same_symbol_collision(self):
        """Known gap: the pre-merge semantic check reports no collision; git's textual layer catches it."""
        self.assertFalse(self.s["nool_merge_same_symbol"]["semantic_engine_reported_no_collision"])

    # Proactive coordination ----------------------------------------------
    def test_nool_discover_reports_other_agents_lease(self):
        c = self.s["nool_coordination"]
        self.assertTrue(c["lease_granted"])
        self.assertTrue(c["conflict_discovered"])
        self.assertEqual(c["discovered_holder"], ["agent-oauth"])

    def test_nool_refuses_second_exclusive_lease(self):
        self.assertTrue(self.s["nool_coordination"]["second_exclusive_announce_refused"])

    def test_nool_refuses_lease_violating_propose(self):
        self.assertTrue(self.s["nool_coordination"]["lease_violating_propose_refused"])

    def test_nool_scope_clears_after_release(self):
        self.assertTrue(self.s["nool_coordination"]["clear_after_release"])

    def test_nool_shared_identity_supersedes_rather_than_conflicts(self):
        """Agents without distinct identities are one agent to Nool: the re-announce replaces the lease."""
        c = self.s["nool_coordination"]
        self.assertTrue(c["shared_identity_second_announce_granted"])
        self.assertEqual(c["shared_identity_active_leases"], 1)

    # Aram -----------------------------------------------------------------
    def test_aram_gate_denies_agent_edit_without_editor_contract(self):
        self._need('nool_aram_provenance')
        self.assertTrue(self.s["nool_aram_provenance"]["gate_denies_without_editor_contract"])

    def test_aram_scenario_landed_rule_and_policy_before_testing(self):
        self._need('nool_aram_provenance')
        a = self.s["nool_aram_provenance"]
        self.assertTrue(a["invariant_config_landed"])
        self.assertTrue(a["policy_set_landed"])

    @unittest.expectedFailure
    def test_aram_blocks_ai_change_without_entire_link(self):
        self._need('nool_aram_provenance')
        """Known gap: require_entire_provenance does not stop an AI-tagged change with no Entire link."""
        self.assertTrue(self.s["nool_aram_provenance"]["provenance_rule_enforced"])

    # Workflow surface -------------------------------------------------------
    def test_nool_checkpoint_handoff_and_pr_artefacts(self):
        w = self.s["nool_workflow"]
        self.assertTrue(w["checkpoint_ok"])
        self.assertTrue(w["handoff_ok"])
        self.assertTrue(w["pr_summary_ok"])
        self.assertTrue(w["pr_summary_has_blast_radius"])
        self.assertTrue(w["pr_merge_ok"])
        self.assertTrue(w["pr_merge_method_present"])

    def test_nool_context_resolves_symbol_queries(self):
        w = self.s["nool_workflow"]
        self.assertTrue(w["context_symbol_matched_entities"])
        self.assertTrue(w["context_symbol_has_blast_radius"])

    def test_entire_captures_sessions_and_prompts(self):
        self._need_live_refs()
        live = self.s["live_repo"]
        self.assertTrue(live["entire_session_list_ok"])
        self.assertGreater(live["entire_sessions_listed"], 0)
        self.assertTrue(live["entire_explain_shows_prompt_intent"])
        self.assertTrue(live["entire_why_links_checkpoint"])

    def test_ref_namespaces_do_not_overlap(self):
        self._need_live_refs()
        live = self.s["live_repo"]
        self.assertGreater(live["entire_ref_count"], 0)
        self.assertGreater(live["nool_ref_count"], 0)
        self.assertEqual(live["ref_namespace_overlap"], [])


if __name__ == "__main__":
    unittest.main()
