# Entire provenance policy: development status

The policy builds as a WASM component and its seven Rust unit tests pass.
It is **not enabled in the live repository**: the installed Nool 7.23.0 host
cannot link the development SDK's `nool:aram/host@0.1.0` interface. The exact
commands and outputs are recorded in [host-probe.json](host-probe.json).
An interface-load failure is not evidence of provenance enforcement.

The existing benchmark intentionally continues to measure the original
`entire_policy_test` scaffold. Its findings remain applicable to that setup.

## Reproduce

From the repository root:

```sh
cargo test --manifest-path policies-src/entire_provenance/Cargo.toml
nool admin plugin build policies-src/entire_provenance
python3 benchmark/check_provenance_policy.py
```

The probe uses a temporary repository, grants an editor contract, installs
the development component there, and tests missing, malformed and valid
checkpoint links plus an untagged control. It exits nonzero until all four
behave as expected. It does not change the live policy configuration.

The Cargo dependencies currently reference the local Nool development
worktree `aram-proposal-context`; this is a development integration, not a
portable published package. A host built from that branch (including the
proposal-context engine wiring) is required before installation can be
validated. Repoint the two dependencies in Cargo.toml to the matching SDK
and ABI when that change lands upstream, then rerun the commands above.

A separate local build from that branch finished during this validation.
Its probe stopped at `admin contract grant`: the binary was built without
the Enterprise feature, although the installed license covers Enterprise.
It therefore did not reach the four policy cases. A compatible Enterprise
host build is still needed; the recorded four-case evidence is for the
installed CLI.

## Rule and limits

A proposal tagged `is_ai_agent` needs an issue reference of the form
`entire_checkpoint:<26-character uppercase ULID>`. Missing and malformed
links are denied. ULID overflow is rejected; any one valid link suffices.
Untagged proposals and evaluations without proposal context are allowed.

This checks the shape of a proposer-supplied reference. It does not verify
checkpoint existence, authorship, correspondence to the changed code, or
that an agent truthfully supplied the AI tag. The sandbox has no repository
access. Replication and historical audits lack proposal context and therefore
do not re-enforce the rule.

## Remaining integration work

1. Make the proposal-context host available and pass the four-case probe.
2. Replace the old policy through Nool's policy installation workflow, land
   the policy set, and rerun the benchmark against that explicit configuration.
3. Seal the pending task candidate and record completion. The existing stale
   `entire_policy_test` module currently refuses its newer Task payload.

Do not count the draft component or a linker error as a fixed benchmark gap.
