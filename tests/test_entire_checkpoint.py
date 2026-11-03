"""The Entire checkpoint checker and the recorded policy-type probe."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "attest_entire_checkpoint", REPO / "scripts" / "attest_entire_checkpoint.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

ULID_ID = "01M6CRZR6WVBD2GAEE84042PZA"
GIT_ID = ["-c", "user.name=checker-test", "-c", "user.email=test@example.invalid"]


def git(repo, *args, **kw):
    return subprocess.run(["git", *GIT_ID, *args], cwd=repo, capture_output=True, text=True,
                          check=True, **kw).stdout.strip()


class CheckpointCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="entire-checker-test-")
        self.addCleanup(self.temp.cleanup)
        self.repo = self.temp.name
        git(self.repo, "init", "-q", "-b", "main")
        os.makedirs(Path(self.repo) / "src")

    def commit(self, rel, message):
        path = Path(self.repo) / rel
        with open(path, "a") as f:
            f.write("x = 1\n")
        git(self.repo, "add", rel)
        git(self.repo, "commit", "-qm", message)
        return git(self.repo, "rev-parse", "HEAD")

    def checkpoint(self, checkpoint_id, files):
        meta = json.dumps({"checkpoint_id": checkpoint_id, "files_touched": files})
        blob = git(self.repo, "hash-object", "-w", "--stdin", input=meta)
        tree = git(self.repo, "mktree", input=f"100644 blob {blob}\tmetadata.json\n")
        commit = git(self.repo, "commit-tree", tree, "-m", "checkpoint")
        git(self.repo, "update-ref",
            f"refs/entire/checkpoints/{checkpoint_id[-2:]}/{checkpoint_id}", commit)

    def test_id_formats(self):
        self.assertTrue(checker.valid_id(ULID_ID))
        self.assertTrue(checker.valid_id("8a513f56ed70"))
        self.assertFalse(checker.valid_id("bad"))
        self.assertFalse(checker.valid_id("81M6CRZR6WVBD2GAEE84042PZA"))  # ULID overflow
        self.assertFalse(checker.valid_id("01M6CRZR6WVBD2GAEE84042PZI"))  # I is not Crockford

    def test_commit_without_link_fails(self):
        sha = self.commit("src/a.py", "feat: no link")
        evidence = checker.evaluate(self.repo, sha)
        self.assertEqual(evidence["verdict"], "fail")
        self.assertIn("no Entire-Checkpoint trailer", evidence["reason"])

    def test_trailer_to_overlapping_checkpoint_passes(self):
        self.checkpoint(ULID_ID, ["src/a.py"])
        sha = self.commit("src/a.py", f"feat: linked\n\nEntire-Checkpoint: {ULID_ID}")
        evidence = checker.evaluate(self.repo, sha)
        self.assertEqual(evidence["verdict"], "pass", evidence)
        self.assertEqual(evidence["checkpoints"][0]["source"], "trailer")
        self.assertEqual(evidence["checkpoints"][0]["overlap"], ["src/a.py"])

    def test_link_to_missing_checkpoint_fails(self):
        sha = self.commit("src/a.py", f"feat: dangling\n\nEntire-Checkpoint: {ULID_ID}")
        evidence = checker.evaluate(self.repo, sha)
        self.assertEqual(evidence["verdict"], "fail")
        self.assertIsNone(evidence["checkpoints"][0]["ref"])

    def test_checkpoint_for_other_files_fails(self):
        self.checkpoint(ULID_ID, ["docs/other.md"])
        sha = self.commit("src/a.py", "feat: unrelated")
        evidence = checker.evaluate(self.repo, sha, [ULID_ID])
        self.assertEqual(evidence["verdict"], "fail")
        self.assertEqual(evidence["checkpoints"][0]["overlap"], [])

    def test_operator_supplied_checkpoint_passes(self):
        self.checkpoint(ULID_ID, ["src/a.py"])
        sha = self.commit("src/a.py", "feat: landed by nool")
        evidence = checker.evaluate(self.repo, sha, [ULID_ID])
        self.assertEqual(evidence["verdict"], "pass")
        self.assertEqual(evidence["checkpoints"][0]["source"], "operator")

    def test_baseline_exemption_only_for_earlier_unlinked_commits(self):
        old = self.commit("src/a.py", "feat: before the rule")
        adopted = self.commit("src/b.py", "chore: adopt ENTIRE-1")
        new = self.commit("src/a.py", "feat: after the rule")
        self.assertEqual(checker.baseline(self.repo, old, adopted)["verdict"], "pass")
        self.assertEqual(checker.baseline(self.repo, adopted, adopted)["verdict"], "fail")
        self.assertEqual(checker.baseline(self.repo, new, adopted)["verdict"], "fail")
        self.assertEqual(checker.baseline(self.repo, old, adopted)["assertion"],
                         "provenance-baseline")


class PolicyTypeProbeEvidenceTests(unittest.TestCase):
    """Assertions over benchmark/results/policy-types.json (the last recorded probe)."""

    @classmethod
    def setUpClass(cls):
        path = REPO / "benchmark" / "results" / "policy-types.json"
        if not path.exists():
            raise unittest.SkipTest("run benchmark/check_policy_types.py first")
        cls.result = json.loads(path.read_text())
        cls.cases = {o["case"]: o for o in cls.result["outcomes"]}

    def test_enforced_policy_types_met_expectations(self):
        self.assertTrue(self.result["all_expectations_met"], self.result["outcomes"])
        for name in ("known-format secret", "forbidden path",
                     "push without checkpoint attestation", "push after failed attestation",
                     "push after checkpoint attestation", "high-entropy token"):
            self.assertTrue(self.cases[name]["expectation_met"], name)

    def test_push_is_held_until_a_checkpoint_is_attested(self):
        self.assertEqual(self.cases["push without checkpoint attestation"]["rc"], 3)
        self.assertEqual(self.cases["push after checkpoint attestation"]["rc"], 0)

    @unittest.expectedFailure
    def test_invariant_blocks_ai_tagged_change_without_link(self):
        """Measured gap: the `require_entire_provenance` invariant neither refuses nor reports."""
        self.assertTrue(self.cases["AI-tagged change without link"]["expectation_met"])


if __name__ == "__main__":
    unittest.main()
