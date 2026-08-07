#!/usr/bin/env bash
#
# Journey 07 — codegen consume. See README.md for what this covers.
# Run via e2e/run.sh, which provides $TRIX and an isolated working directory.
#
#@ min-tx3c: 0.23.0

source "${E2E_LIB:?E2E_LIB not set — run this journey via e2e/run.sh}"

JOURNEY_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

journey_begin "07-codegen-consume" "codegen a ts client → compile it → resolve a transfer through it (devnet)"

# The journey compiles and runs the generated TypeScript client, so a Node
# toolchain is infrastructure here — gate on it like 06 gates on docker.
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  skip "node/npm not found — skipping codegen-consume journey"
  journey_end
  exit 0
fi

# 1. Scaffold under a stable directory name: the project name is inferred from
# it, and it doubles as the per-protocol output subdir we assert on below.
mkdir demo && cd demo
run_cmd "trix init -y — scaffold a new project" "${TRIX}" init -y

# 2. Generate the ts client: real `tx3c codegen` against the published
# codegen-v1beta0 templates (downloaded from tx3-lang/web-sdk).
run_cmd "trix codegen --plugin ts-client — generate bindings" "${TRIX}" codegen --plugin ts-client
assert_output_contains "Added [[codegen]]" "plugin entry seeded into trix.toml"
assert_output_contains "Bindgen successful for 'demo'"
assert_exists ".tx3/codegen/ts-client/demo/protocol.ts" "per-protocol layout: .tx3/codegen/ts-client/demo/"
[[ -e ".tx3/codegen/ts-client/protocol.ts" ]] && die "bindings leaked outside the per-protocol subdir"
ok "no flat protocol.ts outside the per-protocol subdir"

run_cmd "read the generated client" cat .tx3/codegen/ts-client/demo/protocol.ts
assert_output_contains 'PROTOCOL_NAME = "demo"' "protocol identity embedded"
assert_output_contains "TRANSFER_TIR" "transfer TIR envelope embedded"
assert_output_contains "class Client" "typed client wrapper emitted"

# 3. Compile it in a host package. The templates emit a bare module — the
# consuming application provides package.json/tsconfig, exactly what the
# fixture models. npm install talks to the public npm registry (no secrets).
mkdir app
cp .tx3/codegen/ts-client/demo/protocol.ts app/
cp "${JOURNEY_HOME}/package.json" "${JOURNEY_HOME}/tsconfig.json" "${JOURNEY_HOME}/resolve.ts" app/
cd app
run_cmd "npm install — fetch tx3-sdk + typescript" npm install --no-fund --no-audit --loglevel=error
run_cmd "tsc — compile the generated client + host consumer" npx tsc
assert_exists "dist/protocol.js" "generated client compiled"
assert_exists "dist/resolve.js" "host consumer compiled"
cd ..

# 4. Round-trip: resolve a transfer *through the generated client* against a
# local devnet. 05-invoke covers the `trix invoke` path; this is the
# generated-SDK path over the same TRP. Resolve-only — no signing, headless.
ALICE="$("${TRIX}" identities alice address-testnet 2>/dev/null | grep '^addr' | head -n1)"
BOB="$("${TRIX}" identities bob address-testnet 2>/dev/null | grep '^addr' | head -n1)"
[[ -n "${ALICE}" && -n "${BOB}" ]] || die "could not resolve alice/bob testnet addresses"

run_cmd "trix devnet --background — start a local devnet" "${TRIX}" devnet --background
assert_output_contains "devnet started in background"
DEVNET_PIDS="$(pgrep -f 'dolos.*daemon' | tr '\n' ' ')"
# shellcheck disable=SC2064
trap "[[ -n \"${DEVNET_PIDS}\" ]] && kill -9 ${DEVNET_PIDS} 2>/dev/null" EXIT
for _ in $(seq 1 30); do
  (exec 3<>/dev/tcp/127.0.0.1/8164) 2>/dev/null && { exec 3>&- 3<&-; break; }
  sleep 1
done
sleep 3

run_cmd "node resolve.js — resolve a transfer through the generated client" \
  node app/dist/resolve.js "http://127.0.0.1:8164" "${ALICE}" "${BOB}"
assert_output_contains '"cbor"' "generated client resolved to an unsigned transaction"
assert_output_contains '"hash"' "resolved tx carries a hash"

journey_end
