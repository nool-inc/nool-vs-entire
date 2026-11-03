# Policy and provenance setup

This repository runs two tools side by side. Entire records agent sessions
as checkpoints. Nool coordinates agents and governs what lands and what is
pushed. This page describes how each is configured, which policy types are
live, and what each one enforces. Every claim has a reproduction step.
Verified on 3 November 2026 with Nool **7.24.0** (Enterprise) and Entire CLI
**0.12.2**.

## Entire

Configuration follows the Entire documentation at
[docs.entire.com](https://docs.entire.com/overview) (`docs.entire.io` redirects there).

| Setting | Value | Why |
|---|---|---|
| Agents | `antigravity`, `claude-code` (`entire agent add claude-code`) | Captures Claude Code sessions as well as the earlier Antigravity ones. The Claude Code hooks sit beside Nool's hooks in `.claude/settings.json`. |
| `checkpoints.primary.type` | `git-refs` | One ref per checkpoint, `refs/entire/checkpoints/<shard>/<26-char ULID>`. |
| `commit_linking` | `always` | Links agent commits to checkpoints without prompting. |
| `strategy_options.push_sessions` | `true` | `git push origin` also pushes checkpoint refs. `origin` is the Entire remote. |
| `redaction.betterleaks.enabled` | `true` | Default secret scanner for stored transcripts. |
| `redaction.pii` | email and phone on, address off | Redacts personal data in transcripts. |
| `redaction.custom_redactions` | `NOOL_IDENTITY_KEY`, `NOOL_HUB_TOKEN` | Keeps Nool signing keys and hub tokens out of transcripts. |

To check the setup, run `entire status --detailed` and `entire doctor`. A
clean `doctor` run reports OK hook configuration for both agents and no stuck
sessions.

Entire provides redaction and commit linking, but no gate that rejects a
change. Enforcement in this repository comes from Nool.

## Nool policy types

| Type | Where | Stage | What it does |
|---|---|---|---|
| Commit template | `[commit]` in `nool.toml` | seal | Requires a typed subject of 72 characters or fewer, plus Nool's identity and policy trailers. |
| Authority grants | `[governance] issuer_keys` | seal | Only a trusted issuer's editor or admin grants may land code or governance files. |
| Forbidden paths | `[rules] forbidden_paths` | pre-tool, seal | Refuses writes to `.entire/metadata`, `.entire/logs`, `.entire/tmp` and `.env`. |
| DSL content rule `SEC-1` | `policies/secrets.yaml` | pre-tool, propose, seal, push | Blocks known-format credentials: private keys, AWS and GitHub tokens, Anthropic keys and Nool identity keys. |
| DSL content rule `SEC-2` | `policies/secrets.yaml` | propose, seal | Warns on high-entropy tokens and records the warning in the gate receipt. |
| DSL evidence rule `ENTIRE-1` | `policies/provenance.yaml` | pre-push, doctor | Holds a push of `src/`, `tests/`, `benchmark/` or `scripts/` changes until a trusted `entire-checkpoint` pass is attested, or a `provenance-baseline` pass for history from before the rule. |
| Proof obligations | `[attestation.obligations]` | pre-push | Requires a trusted `unit-tests` pass for code and test paths. |
| Relational invariant | `[invariants] require_entire_provenance` | `nool verify` | Kept for comparison. Measured as **not enforced** (see below). |

The policy set is pinned by hash in `[[aram.policies]]`, so a clone enforces
the same files. Nool refuses a policy file that is edited, added or removed
without being landed (`POLICY_PIN_DRIFT`).

### Linking a landed change to its Entire checkpoint

Nool writes commits through libgit2, so Entire's git hooks never add an
`Entire-Checkpoint:` trailer to them. The link is made through a signed
attestation instead:

```sh
# after `nool propose … --solidify`
python3 scripts/attest_entire_checkpoint.py                      # uses an Entire-Checkpoint trailer if present
python3 scripts/attest_entire_checkpoint.py --checkpoint <ULID>  # or name the checkpoint
nool push origin
```

For each named checkpoint, the checker confirms three things: the ID has
Entire's format, `refs/entire/checkpoints/*/<id>` exists locally, and the
checkpoint's recorded `files_touched` overlaps the commit's files. It records
the result as `nool attest record --assertion entire-checkpoint` with the
evidence as JSON. The attestation counts as trusted only when the signing key
is in `[attestation] checker_keys`. With `--dry-run` it prints the evidence
and records nothing.

To create a checkpoint for work that did not go through a git commit, Entire
documents `entire session attach <session-id> --commit <sha>`. If that commit
has not been pushed, `attach` adds the trailer by rewriting it, which would
move a Nool-exported commit. Name the checkpoint with `--checkpoint` instead,
or attach after the commit is pushed, when Entire records the link in a new
checkpoint.

**History before the rule.** Knots landed before `ENTIRE-1` was adopted at
`cb936a4` have no checkpoint. They pass only with an audited exemption. The
checker records it only for commits that name no checkpoint and are either
ancestors of that commit or side-branch commits made before it:

```sh
python3 scripts/attest_entire_checkpoint.py --commit <sha> --baseline-before cb936a4
```

It records a signed `provenance-baseline` pass that gives the reason, and it
refuses any later commit. `nool attest show <knot>` lists the exemption.

**Limits.** The checker shows that a checkpoint exists and touched the same
files. It does not show that the session wrote those exact lines, or that the
agent was honest about its tag. Anyone holding a trusted checker key can
record either assertion.

### Reproduce

```sh
python3 benchmark/check_policy_types.py      # sandboxed: every policy type above
python3 -m unittest tests.test_entire_checkpoint
nool admin plugin list && nool doctor
```

The probe writes [policy-types.json](../benchmark/results/policy-types.json).
Scenario 5 of the [benchmark report](../BENCHMARK_COMPARISON.md) renders the
same results.

## Remotes

| Remote | URL | Carries |
|---|---|---|
| `nool` | `https://github.com/nool-inc/nool-vs-entire.git` | Branch, `refs/knots/*`, `refs/nool/*`, attestations (`nool push nool`) |
| `origin` | `entire://aws-eu-central-1.entire.io/et/nool-vs-entire/nool-vs-entire` | Entire checkpoints (`git push origin`), and Nool refs (`nool push origin`) |

`[bridge] auto_push_remotes` lists both remotes. `ENTIRE-1` and the
`unit-tests` obligations are checked on every `nool push`.

## Recovery note (3 November 2026)

Before this setup, the pinned policy was `entire_provenance.wasm`, which
needs an unreleased host. Released 7.24.0 could not load it, and Nool enforces
the landed policy set on every seal, including the change that would replace
it. The two knots that swapped the policy set (`04e7bc0`, `cb936a4`) were
therefore sealed with a one-off host. That host was built in a scratch
directory from the `aram-proposal-context` patch applied to Nool 7.24.0 and was
never installed. Every later knot was sealed with the released binary.

## Measured gaps

- **The invariant does not enforce.** `require_entire_provenance` (`when
  has_metadata('is_ai_agent') then has_link('entire_checkpoint')`) let an
  AI-tagged change with no link land. `nool verify --all` then reported zero
  violations, even with `[gating] relational_controls = "block"`. Two
  expected-failure tests keep the gap visible.
- **The WASM provenance policy needs an unreleased host.**
  `policies-src/entire_provenance` imports `get-proposal-context`, which exists
  only on the Nool `aram-proposal-context` development branch. Released 7.24.0
  fails to link it. See [its README](../policies-src/entire_provenance/README.md).
