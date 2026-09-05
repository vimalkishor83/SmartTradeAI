# SmartTrade AI Enterprise Transformation Plan

**Status:** Phase 0 plan
**Baseline:** `docs/ARCHITECTURE.md` and `docs/IMPROVEMENT_AUDIT.md`

The plan is deliberately incremental. Each phase should produce a small, reviewable commit, regression tests, updated audit evidence and a production verification record before the next phase begins.

## Priority Order

| Priority | Phase | Outcome | First deliverables |
|---|---|---|---|
| P0 | Security and correctness | Prevent unsafe actions and incorrect user-facing numbers | Auth/input/IDOR audit, metric contracts, security regressions |
| P0 | Data quality | Make stale, corrupt or incomplete data visible and able to produce `NO_SIGNAL` | Provider health contract, freshness metadata, feature completeness checks |
| P0 | Backtest integrity | Make results reproducible and statistically honest | Dataset/strategy hashes, spread assumptions, metric edge cases |
| P1 | API and domain boundaries | Reduce duplicated business logic without breaking clients | Shared response/error helpers, request IDs, service extraction |
| P1 | ML/AI accountability | Separate model probability, calibration, agreement, regime and signal quality | Model registry metadata, chronological evaluation, calibration report |
| P1 | Signal quality and audit trail | Explain every accepted or rejected decision with real inputs | Decision record, quality score contract, explicit no-signal reasons |
| P1 | Portfolio and analytics | Make money, currency, exposure and performance calculations trustworthy | Currency policy, transaction-ledger audit, aggregation tests |
| P2 | Frontend design system | Make dashboard and terminal feel like one accessible product | Shared tokens, navigation model, state components, responsive QA |
| P2 | Observability and admin operations | Detect failures, drift and provider degradation before users report them | Structured logs, request/job timing, provider dashboards, AI quality page |
| P2 | Testing and delivery | Make regressions cheap to catch and releases repeatable | Frontend tests, E2E critical paths, CI gates, deployment checklist |
| P3 | Performance and scale | Improve latency and throughput based on measured bottlenecks | Query/index profiling, cache policy, payload pagination, job controls |

## Execution Rules

For every change:

1. Read the implementation and its consumers.
2. State the defect or measurable outcome.
3. Add the smallest compatible code change.
4. Add a regression test for changed behavior.
5. Run the relevant local baseline and full suite.
6. Verify the API/UI behavior with real evidence where applicable.
7. Review the diff and update `docs/IMPROVEMENT_AUDIT.md`.
8. Deploy only the scoped commit after checking for parallel repository/container changes.

## Phase Gates

### Phase 0: Audit and architecture map

Completed by this document and `docs/ARCHITECTURE.md`. Existing findings remain tracked in `docs/IMPROVEMENT_AUDIT.md`.

### Phase 1: Security and correctness

Start with protected-route ownership checks, registration/profile validation, secret/log review, and remaining high-impact calculation defects. Do not redesign confidence or add AI features in this phase.

### Phase 2: Data-quality infrastructure

Extend the existing quality engine into a stable response contract with provider, freshness, candle-count and warning metadata. Add endpoint and signal-pipeline tests before surfacing new UI badges.

### Phase 3: ML pipeline and leakage prevention

Inventory actual model implementations, feature/target timestamps and chronological splits. Add metadata and leakage tests before changing ensemble behavior.

### Phase 4: Confidence and signal quality

Define separate contracts for raw probability, calibrated probability, agreement, regime fit, historical reliability, data quality and final signal quality. Implement `NO_SIGNAL` reasons as a first-class response state.

### Phase 5: Backtesting and analytics

Continue the existing backtest audit through spread, sizing, open/expired trades, reproducibility and portfolio analytics. Preserve both existing engines until their contracts are explicitly reconciled.

### Phase 6+: Platform modernization

Standardize API envelopes, extract shared services, consolidate the design system, add observability/admin operations, build frontend/E2E CI, then optimize measured bottlenecks.

## Explicit Non-Goals

- Increasing confidence percentages or signal volume.
- Claiming LSTM, calibration, agreement or provider health without implementation evidence.
- Rewriting the application into a new framework before current behavior has compatibility coverage.
- Adding Redis queues, microservices or new model infrastructure without measured need.
- Removing working routes, fields or integrations without migration and rollback plans.
