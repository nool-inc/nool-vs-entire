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

    def test_attached_checkpoint_uses_transcript_writes(self):
        root = os.path.realpath(self.repo)
        lines = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": os.path.join(root, "src/a.py")}},
                {"type": "tool_use", "name": "Read",
                 "input": {"file_path": os.path.join(root, "src/b.py")}}]}},
        ]
        meta = git(self.repo, "hash-object", "-w", "--stdin",
                   input=json.dumps({"checkpoint_id": ULID_ID}))
        log = git(self.repo, "hash-object", "-w", "--stdin",
                  input="\n".join(json.dumps(x) for x in lines))
        sub = git(self.repo, "mktree",
                  input=f"100644 blob {log}\tfull.jsonl\n100644 blob {meta}\tmetadata.json\n")
        tree = git(self.repo, "mktree",
                   input=f"040000 tree {sub}\t0\n100644 blob {meta}\tmetadata.json\n")
        commit = git(self.repo, "commit-tree", tree, "-m", "attached session")
        git(self.repo, "update-ref", f"refs/entire/checkpoints/{ULID_ID[-2:]}/{ULID_ID}", commit)
        written = self.commit("src/a.py", "feat: written by the session")
        evidence = checker.evaluate(self.repo, written, [ULID_ID])
        self.assertEqual(evidence["verdict"], "pass", evidence)
        self.assertEqual(evidence["checkpoints"][0]["files_source"], "transcript")
        self.assertEqual(evidence["checkpoints"][0]["files_touched"], ["src/a.py"])
        only_read = self.commit("src/b.py", "feat: only read by the session")
        self.assertEqual(checker.evaluate(self.repo, only_read, [ULID_ID])["verdict"], "fail")

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

    def test_baseline_covers_side_branch_commits_made_before_adoption(self):
        base = self.commit("src/a.py", "feat: base")
        git(self.repo, "checkout", "-q", "-b", "side")
        side = self.commit("src/c.py", "feat: side branch work")
        git(self.repo, "checkout", "-q", "main")
        env = {**os.environ, "GIT_COMMITTER_DATE": "2099-01-01T00:00:00Z"}
        Path(self.repo, "src/b.py").write_text("y = 2\n")
        git(self.repo, "add", "src/b.py")
        subprocess.run(["git", *GIT_ID, "commit", "-qm", "chore: adopt"], cwd=self.repo,
                       env=env, check=True)
        adopted = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(checker.baseline(self.repo, side, adopted)["verdict"], "pass")
        self.assertEqual(checker.baseline(self.repo, base, adopted)["verdict"], "pass")


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
