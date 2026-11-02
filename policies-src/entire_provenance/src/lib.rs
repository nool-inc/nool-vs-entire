//! Aram policy `entire_provenance`.
//!
//! Rule: a change the proposer tags `is_ai_agent` must link the Entire
//! checkpoint (the recorded agent session) that produced it, as an
//! `--issue entire_checkpoint:<ULID>` reference.
//!
//! ```sh
//! nool propose --path src/auth.py --intent "..." \
//!     --tag is_ai_agent --issue entire_checkpoint:01M6CS3FS2N4A78RSW30YMYK87
//! ```
//!
//! What it does not do: confirm the checkpoint exists. A policy runs in a
//! sandbox with no git or filesystem access, so it checks that a well-formed
//! checkpoint id is linked, not that `refs/entire/checkpoints/<id>` is present.
//!
//! No proposal context (a pulled or ingested knot, an audit re-run, an older
//! host) → allow: the rule governs what a proposer attaches, and denying on
//! absence would refuse every replicated knot.

#![allow(unsafe_op_in_unsafe_fn)]

use nool_aram_policy_sdk::{PolicyResult, reason_codes};
use nool_policy_abi::proposal_context::ProposalContext;

pub const AI_TAG: &str = "is_ai_agent";
pub const LINK_SCHEME: &str = "entire_checkpoint";

/// An Entire checkpoint id: a 26-character ULID in Crockford base32.
pub fn is_checkpoint_id(id: &str) -> bool {
    id.len() == 26
        && matches!(id.as_bytes()[0], b'0'..=b'7')
        && id
            .bytes()
            .all(|b| b.is_ascii_digit() || (b.is_ascii_uppercase() && !b"ILOU".contains(&b)))
}

/// The whole decision, kept pure so it is testable without a WASM host.
pub fn decide(context: Option<&ProposalContext>) -> PolicyResult {
    let Some(ctx) = context else {
        return PolicyResult::allow();
    };
    if !ctx.has_tag(AI_TAG) {
        return PolicyResult::allow();
    }
    let links: Vec<&str> = ctx.links(LINK_SCHEME).collect();
    if links.iter().any(|id| is_checkpoint_id(id)) {
        return PolicyResult::allow();
    }
    let found = if links.is_empty() {
        "no entire_checkpoint link".to_string()
    } else {
        format!("malformed entire_checkpoint link(s): {}", links.join(", "))
    };
    PolicyResult::deny_with_evidence(
        reason_codes::CUSTOM_VIOLATION,
        format!(
            "AI-authored change (tag `{AI_TAG}`) must link its Entire session: \
             add --issue {LINK_SCHEME}:<checkpoint id> (see `entire checkpoint list`)"
        ),
        found,
    )
}

#[cfg(target_arch = "wasm32")]
mod wasm {
    use nool_aram_policy_sdk::{Policy, PolicyContext, PolicyResult, policy};

    struct EntireProvenance;

    policy!(EntireProvenance);

    impl Policy for EntireProvenance {
        fn name() -> &'static str {
            "entire_provenance"
        }

        fn evaluate(_ctx: &PolicyContext) -> PolicyResult {
            super::decide(PolicyContext::proposal_context().as_ref())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const CP: &str = "01M6CS3FS2N4A78RSW30YMYK87";

    fn ctx(tags: &[&str], issues: &[&str]) -> ProposalContext {
        ProposalContext {
            intent: "change".into(),
            metadata_tags: tags.iter().map(|s| s.to_string()).collect(),
            related_issues: issues.iter().map(|s| s.to_string()).collect(),
        }
    }

    #[test]
    fn no_context_is_allowed() {
        assert!(decide(None).is_allowed());
    }

    #[test]
    fn untagged_change_is_allowed() {
        assert!(decide(Some(&ctx(&[], &[]))).is_allowed());
    }

    #[test]
    fn ai_change_without_link_is_denied() {
        assert!(!decide(Some(&ctx(&[AI_TAG], &[]))).is_allowed());
    }

    #[test]
    fn ai_change_with_checkpoint_link_is_allowed() {
        let link = format!("entire_checkpoint:{CP}");
        assert!(decide(Some(&ctx(&[AI_TAG], &[&link]))).is_allowed());
    }

    #[test]
    fn malformed_or_wrong_scheme_links_are_denied() {
        assert!(!decide(Some(&ctx(&[AI_TAG], &["entire_checkpoint:not-a-ulid"]))).is_allowed());
        assert!(!decide(Some(&ctx(&[AI_TAG], &[&format!("jira:{CP}")]))).is_allowed());
        // Crockford base32 excludes I, L, O, U.
        assert!(
            !decide(Some(&ctx(
                &[AI_TAG],
                &["entire_checkpoint:01M6CS3FS2N4A78RSW30YMYKIL"]
            )))
            .is_allowed()
        );
    }

    #[test]
    fn any_one_valid_link_suffices() {
        let good = format!("entire_checkpoint:{CP}");
        assert!(decide(Some(&ctx(&[AI_TAG], &["entire_checkpoint:bad", &good]))).is_allowed());
    }

    #[test]
    fn checkpoint_id_rejects_overflow_and_noncanonical_values() {
        assert!(is_checkpoint_id("7ZZZZZZZZZZZZZZZZZZZZZZZZZ"));
        for id in [
            "8ZZZZZZZZZZZZZZZZZZZZZZZZZ",
            "",
            "01m6cs3fs2n4a78rsw30ymyk87",
            "01M6CS3FS2N4A78RSW30YMYK8",
        ] {
            assert!(!is_checkpoint_id(id), "accepted invalid checkpoint: {id}");
        }
    }
}
