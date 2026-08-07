#!/usr/bin/env bash
#
# Journey 10 — live network. See README.md for what this covers.
# Run via e2e/run.sh, which provides $TRIX and an isolated working directory.

source "${E2E_LIB:?E2E_LIB not set — run this journey via e2e/run.sh}"

journey_begin "10-live-network" "resolve a transfer against a live preprod TRP endpoint (secrets-gated)"

# Secrets gate: without the live env this journey skips green, so it can sit
# in the auto-discovered suite without poisoning offline runs. A *partially*
# configured env is a misconfiguration and fails loudly instead.
if [[ -z "${TRP_ENDPOINT_PREPROD:-}" ]]; then
  skip "TRP_ENDPOINT_PREPROD not set — skipping live-network journey (secrets-gated)"
  journey_end
  exit 0
fi
for v in TRP_API_KEY_PREPROD TEST_PARTY_A_ADDRESS TEST_PARTY_B_ADDRESS; do
  [[ -n "${!v:-}" ]] || die "TRP_ENDPOINT_PREPROD is set but ${v} is missing — refusing a half-configured live env"
done

# 1. Scaffold, then point the preprod network at the provided TRP endpoint.
# The u5c endpoint stays on the public preprod one stock trix ships for the
# known network (URL and key are public constants baked into the binary).
run_cmd "trix init -y — scaffold a new project" "${TRIX}" init -y
cat >> trix.toml <<EOF

[networks.preprod]
is_testnet = true

[networks.preprod.trp]
url = "${TRP_ENDPOINT_PREPROD}"

[networks.preprod.trp.headers]
dmtr-api-key = "${TRP_API_KEY_PREPROD}"

[networks.preprod.u5c]
url = "https://preprod.utxorpc-v0.demeter.run"

[networks.preprod.u5c.headers]
dmtr-api-key = "trpjodqbmjblunzpbikpcrl"
EOF
ok "preprod network pointed at the provided TRP endpoint"

# 2. Resolve a transfer between the funded test parties against the live
# testnet. --skip-submit keeps it headless (invoke never signs without a TTY)
# and leaves no on-chain footprint — real UTxO state in, unsigned tx out.
run_cmd "trix invoke -p preprod — resolve against live preprod" \
  "${TRIX}" invoke -p preprod --skip-submit \
  --args-json "{\"sender\":\"${TEST_PARTY_A_ADDRESS}\",\"receiver\":\"${TEST_PARTY_B_ADDRESS}\",\"quantity\":1000000}"
assert_output_contains '"cbor"' "resolved to an unsigned transaction from live chain state"
assert_output_contains '"hash"' "resolved tx carries a hash"

journey_end
