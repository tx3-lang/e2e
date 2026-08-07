#!/usr/bin/env bash
#
# Journey 09 — protocol fixture. See README.md for what this covers.
# Run via e2e/run.sh, which provides $TRIX and an isolated working directory.
#
#@ min-tx3c: 0.23.0

source "${E2E_LIB:?E2E_LIB not set — run this journey via e2e/run.sh}"

JOURNEY_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

journey_begin "09-protocol-fixture" "a real protocol (hydra-heads) through check → build → inspect tir"

# 1. Copy the production-scale fixture into the workdir for hermeticity.
cp "${JOURNEY_HOME}/protocol/"* .
cp "${JOURNEY_HOME}/protocol/".env.* .
assert_exists "trix.toml" "protocol fixture in place"

# 2. Analyze: ~1000 lines of production-shaped tx3 (validators, env blocks,
# minting policies, the full Hydra L1 lifecycle) through real tx3c.
run_cmd "trix check — analyze the hydra-heads protocol" "${TRIX}" check
assert_output_contains "check passed"

# 3. Compile to TII — the scope/name/version from trix.toml shape the tree.
run_cmd "trix build — compile to TII" "${TRIX}" build
assert_exists ".tx3/tii/open-tx3/hydra-heads/0.0.0/main.tii" "TII at <scope>/<name>/<version> from trix.toml"

# 4. Lower a lifecycle tx to TIR and confirm protocol-specific constructs
# made it through — not just that the build exited 0.
run_cmd "trix inspect tir --tx init — lower the head-init tx" "${TRIX}" inspect tir --tx init
assert_output_contains '"participant"' "participant party lowered"
assert_output_contains "head_utxo_lovelace" "protocol parameter lowered"
assert_output_contains '"collateral"' "collateral input lowered"

journey_end
