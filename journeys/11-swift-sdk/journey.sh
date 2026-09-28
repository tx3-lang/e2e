#!/usr/bin/env bash
#
# Journey 11 — Swift SDK generated-client DX. See README.md for coverage.
# Run via e2e/run.sh, which provides $TRIX and an isolated working directory.
#
#@ min-tx3c: 0.25.0

source "${E2E_LIB:?E2E_LIB not set — run this journey via e2e/run.sh}"

JOURNEY_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

journey_begin "11-swift-sdk" "generate a Swift client → compile a clean consumer → sign, submit, and confirm on devnet"

TRIX_VERSION="$("${TRIX}" --version | sed -n 's/^trix //p')"
version_ge "${TRIX_VERSION}" "0.28.0" \
  || die "journey 11 requires trix >= 0.28.0 with the built-in swift-client plugin"

command -v swift >/dev/null 2>&1 \
  || die "swift not found — journey 11 requires the approved macOS/Xcode runner"
command -v git >/dev/null 2>&1 || die "git not found — SwiftPM package resolution requires git"

# 1. Scaffold under the stable protocol name `demo`, then drive trix into the
# built-in tx3c swift-client template. The output is a standalone SwiftPM
# package, unlike the bare-module TypeScript output exercised by journey 07.
mkdir demo && cd demo
run_cmd "trix init -y — scaffold a new project" "${TRIX}" init -y
run_cmd "trix codegen --plugin swift-client — generate bindings" \
  "${TRIX}" codegen --plugin swift-client
assert_output_contains "Added [[codegen]]" "plugin entry seeded into trix.toml"
assert_output_contains "Bindgen successful for 'demo'"
grep -qiF "Reading template from" "${LAST_OUTPUT_FILE}" \
  && die "built-in plugin downloaded templates instead of using tx3c's built-in template"
ok "built-in swift-client template rendered by tx3c, no template download"

GENERATED="${PWD}/.tx3/codegen/swift-client/demo"
assert_exists "${GENERATED}/Package.swift" "generated SwiftPM package manifest"
assert_exists "${GENERATED}/Sources/DemoClient/Client.swift" "generated typed client"
assert_exists "${GENERATED}/Sources/DemoClient/Types.swift" "generated parameter types"
[[ -e "${PWD}/.tx3/codegen/swift-client/Package.swift" ]] \
  && die "generated package leaked outside the per-protocol subdirectory"

run_cmd "read the generated client" cat "${GENERATED}/Sources/DemoClient/Client.swift"
assert_output_contains 'PROTOCOL_NAME = "demo"' "protocol identity embedded"
assert_output_contains "TRANSFER_TIR" "transfer TIR envelope embedded"
assert_output_contains "struct DemoClient" "typed Swift client emitted"
assert_output_contains "func withSender" "sender party setter emitted"
assert_output_contains "func transfer" "typed transfer builder emitted"

# 2. Compile a separate host package. Its direct exact SDK requirement pins the
# generated package's compatible `from: 0.15.0` constraint to precisely 0.15.0.
mkdir -p app/Sources/SwiftSDKJourney
sed "s|__GENERATED__|${GENERATED}|g" "${JOURNEY_HOME}/Package.swift" > app/Package.swift
cp "${JOURNEY_HOME}/main.swift" app/Sources/SwiftSDKJourney/main.swift

# Pre-publication runs may point at a reviewed SDK checkout without mutating it.
# Clone it inside the disposable journey workdir, add the release-equivalent
# tag there, and use SwiftPM's official mirror mechanism. Released-channel CI
# leaves this unset and therefore resolves the real public 0.15.0 tag.
if [[ -n "${TX3_SWIFT_SDK_PATH:-}" ]]; then
  [[ -f "${TX3_SWIFT_SDK_PATH}/Package.swift" ]] \
    || die "TX3_SWIFT_SDK_PATH must name a Swift SDK checkout"
  run_cmd "clone reviewed Swift SDK checkout for local package resolution" \
    git clone --quiet "${TX3_SWIFT_SDK_PATH}" .tx3/swift-sdk-mirror
  run_cmd "tag the disposable mirror as the release-equivalent 0.15.0" \
    git -C .tx3/swift-sdk-mirror tag 0.15.0
  run_cmd "configure the consumer to use the local SDK mirror" \
    swift package --package-path app config set-mirror \
      --original https://github.com/tx3-lang/swift-sdk.git \
      --mirror "file://${PWD}/.tx3/swift-sdk-mirror"
fi

run_cmd "swift build --configuration debug — compile generated client and consumer" \
  swift build --package-path app --configuration debug
assert_exists "app/.build/debug/SwiftSDKJourney" "host consumer compiled"

# 3. Fund the canonical CIP-1852 signer vector in this disposable devnet.
# trix's alice uses an underived Icarus root key, so it cannot be bound to
# CardanoSigner. These public SDK vector credentials are devnet-only fixtures.
cp "${JOURNEY_HOME}/devnet.toml" devnet.toml
ALICE="addr_test1vq8ac7qqy0vtulyl7wntmsxc6wex80gvcyjy33qffrhm7ss9hjl0y"
BOB="$("${TRIX}" identities bob address-testnet 2>/dev/null | grep '^addr' | head -n1)"
[[ -n "${BOB}" ]] || die "could not resolve bob's testnet address"
ALICE_MNEMONIC="abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

DEVNET_HOME="${PWD}/.tx3/dolos"
cleanup_devnet() {
  # Install before startup and match only this journey's unique config path.
  pkill -f "dolos.*${DEVNET_HOME}/dolos[.]toml daemon" >/dev/null 2>&1 || true
}
trap cleanup_devnet EXIT
run_cmd "trix devnet --background — start a local devnet" "${TRIX}" devnet --background
assert_output_contains "devnet started in background"
for _ in $(seq 1 30); do
  (exec 3<>/dev/tcp/127.0.0.1/8164) 2>/dev/null && { exec 3>&- 3<&-; break; }
  sleep 1
done
sleep 3

run_cmd "SwiftSDKJourney — resolve, sign, submit, and confirm a transfer" \
  app/.build/debug/SwiftSDKJourney \
    "http://127.0.0.1:8164" "${ALICE}" "${BOB}" "${ALICE_MNEMONIC}"
assert_output_contains '"hash"' "submitted transaction hash returned"
if grep -Eq '"status":"(confirmed|finalized)"' "${LAST_OUTPUT_FILE}"; then
  ok "submitted transaction confirmed"
else
  die "submitted transaction did not reach confirmed or finalized status"
fi

journey_end
