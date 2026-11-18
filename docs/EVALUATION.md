# Stage 1 evaluation

This run covers CasePilot’s fictional, deterministic replay and local sandbox in Checkpoint 4. Each acceptance check below passed in the backend suite. Several test methods use separately asserted subcases, so the number of test methods differs from the number of acceptance checks.

## Run record

| Field | Observed value |
| --- | --- |
| Run date | November 18, 2026, Pacific time |
| Specification revision | CasePilot Stage 1 prompt dated November 18, 2026 at 05:21:51 PT |
| Fixture revision and clock | `stage1-v4`, `2026-11-18T12:00:00Z` |
| Evidence versions | KB01–KB05 v1 plus the versioned conflict, expiry, and adversarial scenario passages |
| Model configuration and usage | Deterministic replay with zero model-provider calls. Limits are six read attempts, one retry per timed-out read, two seconds per read, 20 seconds per investigation, and 4,000 request characters. |
| Runtime | Windows, Python 3.14.6, SQLite 3.50.4, Node.js 24.18.0 |
| Evaluated source | Git tree `af1052c0a93d76692c89e14a7d64c1624403be79` for `backend/` and `6ce12ba11f889c9716159c5df05d7a79c415e66a` for `frontend/` |

**Results** · 43 backend tests passed. The required Stage 1 matrix contains 31 passing acceptance checks, zero failures and zero not-run checks. The four deferred checks are AT10b and AT16a–c.

## Integration and documentation checks

| Check | Result |
| --- | --- |
| Next.js production build and TypeScript check | Passed before push. |
| Edge audit walkthrough | Passed. Verified scoped candidates, a saved missing-evidence run after refresh, original-ID uncertainty and reconciliation, and a 390-pixel layout. |
| Browser request safety | Passed. Missing or mismatched origins returned HTTP 403. A same-origin request without a reviewer session returned HTTP 401. Reviewer notes rendered as text. |
| Local fixture upgrade | Passed. The original proposals, reviews, executions, audit events, and sandbox records matched before and after the upgrade from `stage1-v3`. |
| Editable Mermaid diagrams | Both parsed and rendered locally in Edge with Mermaid 12.3.0. See the [diagram checklist](FLOWS.md#documentation-checklist). |

## Scenario-to-test matrix

Test names below appear in the four Python modules for [workspace](../backend/tests/test_workspace.py), [sandbox](../backend/tests/test_sandbox.py), [failures](../backend/tests/test_failures.py), and [audit](../backend/tests/test_audit.py).

| Checks | Status | Test evidence |
| --- | --- | --- |
| SC01 · AT01 | Passed | `test_sc01_exact_approval_then_verified_8000_cent_receipt` checks the empty ledger before execution and one 8,000-cent verified entry after it. |
| SC02 · AT02a–c | Passed | `test_sc02_return_date_boundaries_and_invalid_dates` checks day 31, day 30, same-day delivery, future dates and malformed dates. |
| SC03 · AT03 | Passed | `test_sc03_denial_records_reason_without_a_sandbox_action` preserves the eligible payload and saves the reviewer’s denial with an empty ledger. |
| SC04 · AT04 | Passed | `test_sc04_edit_creates_a_fresh_exact_revision` retains the invalid $100 revision and verifies execution only after the edited $40 line A revision receives fresh approval. |
| SC05 · AT05a–c | Passed | `test_sc05_preview_pauses_with_no_order_or_proposal` and `test_sc05_two_matches_and_no_match_stay_unresolved_within_scope` check a missing order ID, two authorized candidates and a safe empty result. |
| SC06 · AT06 | Passed | `test_sc06_preview_requires_token_and_uses_server_customer_scope`, `test_sc06_reviewer_authority_and_scope_are_enforced_by_backend`, and `test_sc06_audit_writes_require_reviewer_and_reads_are_case_scoped` cover direct reads, review commands and the audit. |
| SC07 · AT07a–c | Passed | `test_sc07_evidence_gaps_and_conflicts_escalate` covers missing, conflicting, and expired policy evidence and blocks executable proposals. |
| SC08 · AT08a–b | Passed | `test_sc08_changed_balance_invalidates_an_approved_proposal` and `test_sc08_two_approved_cases_cannot_overspend_an_order` check the new $60 maximum and competing execution requests. |
| SC09 · AT09 | Passed | `test_sc09_line_price_and_remaining_balance_are_scoped` and `test_sc09_invalid_edits_cannot_change_the_saved_amount` check the $20 line ceiling, malformed cents and over-limit edits. |
| SC10 · AT10a | Passed | `test_sc10_direct_read_timeout_has_a_typed_error`, `test_sc10_timeout_retries_once_and_returns_no_proposal`, and `test_sc10_retries_share_the_six_read_budget` cover the HTTP timeout, replay retry and total read limit. |
| SC11 · AT11a–b | Passed | `test_sc11_malformed_money_or_customer_in_read_result_fails_closed` checks bad money, missing currency and wrong scope. `test_sc11_mismatched_readback_cannot_verify_an_uncertain_refund` checks receipt mismatch. |
| SC12 · AT12a–c | Passed | `test_sc12_retries_share_one_operation_and_changed_payload_is_rejected` checks concurrent requests, the same receipt on read or retry, and rejection of a changed payload using the same key. |
| SC13 · AT13a–c | Passed | `test_sc13_reject_before_commit_is_failed_without_a_receipt`, `test_sc13_timeout_after_commit_reconciles_one_original_operation`, and `test_sc13_unresolved_operation_reserves_the_balance` check confirmed failure, verified reconciliation and continuing uncertainty. |
| SC14 · AT14 | Passed | `test_sc14_customer_message_does_not_change_scope_or_authorize_action` and `test_sc14_audit_excludes_raw_request_and_masks_credentials` check scoped tool use and audit redaction with synthetic customer text. |
| SC15 · AT15 | Passed | `test_sc15_adversarial_passages_are_retrieved_but_cannot_support_action` checks that synthetic passages cannot supply authority for a proposal or initiate outbound traffic. |
| SC17 · AT17 | Passed | `test_sc17_verified_replacement_creates_one_request_without_refund`, `test_sc17_replacement_rechecks_current_stock`, and `test_sc17_an_existing_refund_blocks_an_overlapping_replacement` check the request, stock and overlapping remedies. |
| SC18 · AT18a–c | Passed | `test_sc18_unknown_status_uses_a_verified_local_outbox_draft`, `test_sc18_replacement_waits_for_shipment_check`, and `test_sc18_delivered_state_invalidates_replacement_after_approval` check the honest draft, missing shipment check and stale approval. |
| AT10b and AT16a–c | Deferred | Excluded from Stage 1 by the specification. |

## Reproduce the run

Use the prerequisites and dependency installation from the [Windows setup](../README.md#windows-setup). The backend suite creates isolated temporary SQLite databases.

```powershell
Set-Location -LiteralPath 'E:\casepilot'
& '.\scripts\check-before-push.ps1'
git rev-parse 'HEAD:backend' 'HEAD:frontend'
```

For the browser walkthrough, start the two local services, sign in as the local reviewer and follow the [reviewer steps](../README.md#local-reviewer-walkthrough). Use **SC07** to save a run without a proposal and **SC13** to see an uncertain operation reconcile to a receipt with the same operation ID.

## Limits

The injection checks exercise the supplied synthetic fixtures and scope controls. The evaluation measures replay behavior and local sandbox records. Live-model quality, production authentication and multi-tenant deployment reviews were not run. See [Stage 1 and the future roadmap](STAGE1.md).
