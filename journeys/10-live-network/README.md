# 10-live-network

A real transfer resolved against a **live Cardano preprod** network through a Demeter TRP
endpoint: scaffold, point the `preprod` network at the provided endpoint, and
`trix invoke -p preprod --skip-submit` a transfer between two funded test parties. This is the
only journey that touches real chain state — everything the offline journeys resolve comes from
a throwaway devnet.

- **Scope:** runtime against a live network. **Secrets-gated** — never on the fast offline gate.
  Scheduled + manually dispatched via `.github/workflows/dx-e2e-live.yml`.
- **Env contract** (mirrors `sdks/scripts/run-e2e-tests.sh`, reuse the same GitHub secrets):
  - `TRP_ENDPOINT_PREPROD` — Demeter TRP endpoint. Unset ⇒ the journey **skips green**.
  - `TRP_API_KEY_PREPROD` — sent as the `dmtr-api-key` header.
  - `TEST_PARTY_A_ADDRESS` / `TEST_PARTY_B_ADDRESS` — funded preprod addresses (sender/receiver).
  - Set-but-incomplete env fails loudly rather than half-running.
- **Resolve-only, by design:** `trix invoke` never signs without a TTY, so `--skip-submit` is the
  headless mode — the journey validates live UTxO selection and tx construction without leaving
  an on-chain footprint or needing keys. The sdks' own live e2e suite covers sign/submit through
  the SDKs (that's what the `TEST_PARTY_*_MNEMONIC` secrets are for; this journey deliberately
  doesn't consume them).

## Arming it in CI

The workflow runs on schedule/dispatch and forwards the four secrets. Until
`TRP_ENDPOINT_PREPROD` & co. are configured as repository (or org) secrets on this repo, the
scheduled run is a green no-op whose log says the journey was skipped.
