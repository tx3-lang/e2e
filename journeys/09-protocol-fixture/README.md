# 09-protocol-fixture

A production-scale protocol through the toolchain: the `acme/hydra-heads` fixture (~1000 lines of
tx3 modeling the Hydra Head L1 lifecycle — validators, env blocks, minting, the full
`init`/`commit`/`close`/`fanout` family) driven through `trix check`, `trix build`, and
`trix inspect tir`. The scaffold-sized fixtures in journeys 01–05 can't represent this surface;
this journey is where "real protocols keep compiling" lives.

- **Scope:** compile/lower (no devnet). Fully offline, no secrets.
- **Toolchain gate:** `#@ min-tx3c: 0.23.0` (matches the verified toolchain).
- **Fixture:** `protocol/` — a snapshot of the umbrella's `protocols/acme/hydra-heads` (config,
  source, env files; the binary logo is omitted). Refresh the snapshot when the upstream fixture
  gains new language constructs.

## Why no `trix test` round-trip yet

The upstream `protocols/` fixtures all ship a `tests/basic.toml` that is a stale copy of the
scaffold template — it references a `transfer` tx none of these protocols define, so
`trix test` fails with `unknown tx: transfer` on every one of them. The round-trip slice of this
journey is blocked on the fixtures growing real test scenarios (tracked in the umbrella plans),
not on the toolchain: the scaffold round-trip itself is green on released channels (see
`04-devnet-roundtrip`). When a real scenario lands upstream, refresh the snapshot including
`tests/` and add a `trix test` step here.
