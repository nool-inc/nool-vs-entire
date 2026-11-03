# Playbooks used to complete repository goals

These workflows were exercised on 2 November 2026. The aim was to produce
evidence and fix a reproducibility problem, rather than just define recipes.

This is a historical account of those runs. The later authority, policy, and
attestation repairs are described in [policy and provenance setup](POLICY_SETUP.md).
The original untrusted-attestation and incompatible-host observations below
remain part of the evidence; they do not describe the repaired configuration.

## Goal 1: make a fresh clone verifiable

The `verified-change` workflow supplied the sequence: reproduce, make a
focused change, run checks, then document the result. Its check commands were
run directly; no separate `nool code` model session was started.

An independent clone reproduced a failure in
`GitRefsCoexistenceTests.test_nool_refs_present`. The test demanded
`refs/nool/git-mirror`, a legacy alias absent from the clone, even though the
current per-branch pointer `refs/nool/mirror/main` existed.

The test now requires a per-branch mirror pointer and no longer requires
the legacy alias. It still fails when no per-branch mirror pointer exists.
The focused ref tests passed, followed by Nool's full landing validation.

The new [clone verifier](../benchmark/check_fresh_clone.py) clones committed
`HEAD` over local Git transport and runs the complete verification runbook.
The clone generates its own benchmark evidence and is removed afterwards.
Its [recorded result](../benchmark/results/fresh-clone.json) identifies the
exact tested revision, exit status, and command output. It does not test
uncommitted edits, remote authentication, or hosted Entire services.

The fresh run passed at commit `8ed6f778b5dc00e4b1568702b63074d4d9309b85`:
90 tests ran, with five skips and the two documented expected failures.
Skipped checks are not counted as verified behavior. The result covers the
committed test fix and verifier; subsequent documentation commits are outside
that snapshot.

## Goal 2: distinguish policy health from policy enforcement

```sh
nool playbook run policy-audit
```

The playbook successfully ran three existing Nool commands:

1. `commit-template check`: the blocking commit-message policy was valid.
2. `verify --all`: two structural controls were evaluated with zero violations.
3. `admin plugin list`: the old `entire_policy_test` module was still flagged
   as predating the current knot model.

The useful result is the distinction between those signals. A zero-violation
structural scan does not prove that an AI-tagged change must carry an Entire
checkpoint. The original benchmark already demonstrated that rule is not
enforced as configured. Plugin warnings do not produce a failing exit code,
so successful playbook execution does not certify plugin compatibility.

The development policy's seven Rust unit tests were also rerun and passed,
including missing/malformed checkpoint rejection, valid-link acceptance,
and ULID overflow rejection. These are pure decision tests, not proof that
the installed host can load the component. The [integration status](../policies-src/entire_provenance/README.md)
and its unresolved host requirement remain unchanged.

## Goal 3: produce review context and validate publication inputs

```sh
nool playbook run study-review
nool playbook run commit-preflight
```

`study-review` validated the signed identity of `HEAD` and generated Nool's
review summary relative to study knot `7d6dccc0`. That fixed baseline is
intentional: it reviews work since the original benchmark study, rather than
silently selecting a moving base. The output includes landed knots, blast
radius, and recorded justifications. It is review context, not an independent
correctness verdict or a GitHub PR review.

`commit-preflight` checked the effective commit template and validated
the latest commit against its embedded signed Knot. Both steps passed.
The playbooks do not publish, send messages, or create approvals. Publication
is a separate `nool push` action under the user's existing authorization.

Raw output for all three command playbooks is in
[playbook-audit.json](../benchmark/results/playbook-audit.json). The snapshot
records its source revision and does not claim to audit later commits.

## Signed attestations and audit trails

Nool's trail is more than the Markdown summaries: signed Knots record
changes and causality, gate attestations record validation, and detached
verification attestations can bind an external result to an exact Knot and
Git revision without adding an application commit.

The clone-verifier change already had automatically minted `compile` and
`unit-tests` attestations from its landing checks. A separate local
`fresh-clone-verification` pass was recorded for subject Knot
`6349acab3892ca6b61f056cf52d9d4d2214564d74042540d1b966dc5335a216a`,
at tested Git revision `8ed6f778b5dc00e4b1568702b63074d4d9309b85`.
Its attestation ID is
`7d26debeed56382e65d70fc57a888bb8b2115eff56a555e14b9b7d9754bb2ff6`.
It binds the [fresh-clone evidence](../benchmark/results/fresh-clone.json)
by hash and explicitly records 90 tests, five skips, and two expected failures.
It does not attest the correctness of later commits or provenance enforcement.

Inspect it with:

```sh
nool attest show 6349acab --json
nool attest obligations 6349acab --json
nool why 6349acab
```

The [inspection snapshot](../benchmark/results/attestation-audit.json)
also records the trust limits. This repository has no configured
`[attestation] checker_keys` or assertion obligations, so signatures are
present but the attestations report `trusted: false`. The empty obligation
matrix reports `unverified-pass`; it is not an independent approval.
Trust anchors were not changed to make these results appear trusted.

`nool audit verify --source git --json` returned an inconclusive result:
no audit framework is configured. Structural checks, a signed local test
result, trusted verification, and framework compliance are distinct claims.
The evidence JSON is committed separately because the attestation's evidence
store is local and its replicated record refers to the evidence by hash.

## Reuse

```sh
# Start a guided coding session when one is needed:
nool code --playbook verified-change "Describe a concrete goal"

# Inspect and execute diagnostics without starting a model session:
nool playbook plan policy-audit
nool playbook run policy-audit
nool playbook run study-review
nool playbook run commit-preflight

# Check an already-landed revision in an independent clone:
python3 benchmark/check_fresh_clone.py
```

Command playbooks stop on the first nonzero exit. They cannot turn advisory
warnings into failures unless the invoked command itself returns a failure.
Required code-playbook checks run when that playbook is selected; they are
not a global replacement for Nool's policy gates or server-side checks.
