#!/usr/bin/env bash
#
# Journey 08 — interface consume. See README.md for what this covers.
# Run via e2e/run.sh, which provides $TRIX and an isolated working directory.
#
#@ min-tx3c: 0.23.0

source "${E2E_LIB:?E2E_LIB not set — run this journey via e2e/run.sh}"

JOURNEY_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

journey_begin "08-interface-consume" "build a real TII → prime the interface cache → inspect + codegen through it"

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# 1. Publisher side: compile the interface's TII with the real toolchain — the
# same normative artifact `trix publish` would push to the registry.
mkdir widget && cd widget
cp "${JOURNEY_HOME}/trix.toml" trix.toml
cp "${JOURNEY_HOME}/main.tx3" main.tx3
run_cmd "trix build — compile the publisher protocol" "${TRIX}" build
TII_SRC=".tx3/tii/acme/widget/0.1.0/main.tii"
assert_exists "${TII_SRC}" "publisher TII at <scope>/<name>/<version>"
DIGEST="sha256:$(sha256_of "${TII_SRC}")"
cd ..

# 2. Consumer side: a separate project that declares acme/widget:0.1.0 and
# consumes it from a hand-primed cache — byte-for-byte the layout `trix use`
# writes (main.tii + informative main.tx3 + metadata.json whose digest matches
# the trix.toml pin). No registry involved: a cached interface works offline.
mkdir consumer && cd consumer
run_cmd "trix init -y — scaffold the consumer project" "${TRIX}" init -y
CACHE=".tx3/tii/acme/widget/0.1.0"
mkdir -p "${CACHE}"
cp "../widget/${TII_SRC}" "${CACHE}/main.tii"
cp ../widget/main.tx3 "${CACHE}/main.tx3"
cat > "${CACHE}/metadata.json" <<EOF
{
  "scope": "acme",
  "name": "widget",
  "version": "0.1.0",
  "digest": "${DIGEST}",
  "published_date": 0,
  "fetched_at": 0,
  "has_readme": false
}
EOF
cat >> trix.toml <<EOF

[interfaces.widget]
ref = "acme/widget:0.1.0"
digest = "${DIGEST}"
EOF
ok "interface cache primed and declared (${DIGEST})"

# 3. Real decode: an interface tx is served from its cached published TII via
# `tx3c decode` — never recompiled from source. Both reference forms must
# address the same cache.
run_cmd "trix inspect tir --tx widget::widget_transfer — decode by alias" \
  "${TRIX}" inspect tir --tx widget::widget_transfer
assert_output_contains '"owner"' "publisher's Owner party in the decoded TIR"
assert_output_contains '"buyer"' "publisher's Buyer party in the decoded TIR"
assert_output_contains '"quantity"' "tx parameter in the decoded TIR"

run_cmd "trix inspect tir --tx acme/widget:0.1.0::widget_transfer — decode by full ref" \
  "${TRIX}" inspect tir --tx acme/widget:0.1.0::widget_transfer
assert_output_contains '"buyer"' "full registry ref routes to the same cached TII"

# 4. Codegen for the interface: bindings are generated from the cached TII
# (real `tx3c codegen`), alongside the consumer's own protocol.
run_cmd "trix codegen --plugin ts-client — generate for project + interface" \
  "${TRIX}" codegen --plugin ts-client
assert_output_contains "Bindgen successful for 'widget'"
assert_exists ".tx3/codegen/ts-client/widget/protocol.ts" "interface bindings in their own subdir"

run_cmd "read the interface client" cat .tx3/codegen/ts-client/widget/protocol.ts
assert_output_contains 'PROTOCOL_NAME = "widget"' "interface identity embedded from the cached TII"
assert_output_contains "WIDGET_TRANSFER_TIR" "interface tx TIR envelope embedded"

journey_end
