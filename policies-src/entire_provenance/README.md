# Entire provenance policy (WASM, development host only)

This Aram WASM policy is **not installed**. It was pinned in `policies/` until
3 November 2026. It was replaced after the released Nool 7.24.0 could not
link it. The live repository now enforces provenance with the `ENTIRE-1`
evidence rule in [`policies/provenance.yaml`](../../policies/provenance.yaml)
(see [policy setup](../../docs/POLICY_SETUP.md)).

## Why it was removed

The policy imports `get-proposal-context` from the Nool development branch
`aram-proposal-context`. Released Nool 7.24.0 does not provide that import.
Every proposal failed with:

```text
component imports instance `nool:aram/host@0.1.0`, but a matching implementation was not found in the linker
```

Nool also enforces the landed policy set whatever the working tree holds.
That included the change that would remove the policy, so the repository
could not land anything on the released host. To recover, a one-off host was
built from the proposal-context patch applied to Nool `main` (7.24.0). It was
built in a scratch directory and was never installed. That host landed only
the policy-set replacement. All later work used the released binary.

The released policy ABI (`nool:aram@0.1.0`) gives a policy the knot, its
diff, contracts, announcements, invariants, facts and evidence. It does not
give the proposal's tags or issue references, so a released-host WASM policy
cannot read a proposer-supplied `entire_checkpoint:<id>` link at all.

## What it checked

A proposal tagged `is_ai_agent` needed an issue reference of the form
`entire_checkpoint:<26-character uppercase ULID>`. Missing and malformed
links were denied, as was ULID overflow; one valid link was enough.
Untagged proposals and evaluations without proposal context were allowed.
It checked only the shape of the reference, not that the checkpoint existed
or matched the change. The released-host replacement checks both.

## Reproduce

On a host with the proposal-context API, and with the `Cargo.toml` path
dependencies pointing at that host's SDK and ABI:

```sh
cargo test --manifest-path policies-src/entire_provenance/Cargo.toml
nool admin plugin build policies-src/entire_provenance
python3 benchmark/check_provenance_policy.py
```

The probe runs in a temporary repository and writes
[host-probe.json](host-probe.json). The recorded run used released 7.24.0, so
all four cases report `host_incompatible: true`.

## Preserved baseline

The original `entire_policy_test` scaffold is kept in
`benchmark/fixtures/legacy-policy/` so the benchmark's Scenario 3 stays
reproducible. Its results do not describe either replacement.
