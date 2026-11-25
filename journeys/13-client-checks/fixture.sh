#!/usr/bin/env bash
#
# Run check.sh against the controlled fixture release instead of a public one:
# build fixture/ with the released trix, serve it from a local OCI registry and
# pass its identity. Later arguments override the fixture's (a wrong digest, a
# different operation), which is how the negative harness tests are written.
# A fixture pass proves the harness only; it is never an onboarding record.
#
# Usage: fixture.sh [--fixture <dir>] --lang <language> --operation <tx>
#          --out <record.json> [check.sh args...]
# --fixture names the fixture protocol directory here (default `fixture`); its
# input fixture for <tx> is <dir>/<tx>.json.
# Env: CHECK_TX3C_PATH replaces tx3c for the check only, not the fixture build.

set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../lib/common.sh
source "${HERE}/../../lib/common.sh"
TRIX="${TRIX:-trix}"
FIXTURE="fixture" OPERATION="settle" PASS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fixture) FIXTURE="$2"; shift 2 ;;
    --operation) OPERATION="$2"; shift 2 ;;
    *) PASS+=("$1"); shift ;;
  esac
done
DIR="${HERE}/${FIXTURE}"
field() { sed -n "s/^$1 = \"\(.*\)\"/\1/p" "${DIR}/trix.toml"; }
SCOPE="$(field scope)" NAME="$(field name)" VERSION="$(field version)"
[[ -n "${SCOPE}" && -n "${NAME}" && -n "${VERSION}" ]] || die "no fixture protocol at ${DIR}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/client-check-fixture.XXXXXX")"
REGISTRY_PID=""
cleanup() { [[ -n "${REGISTRY_PID}" ]] && kill "${REGISTRY_PID}" 2>/dev/null; rm -rf "${WORK}"; }
trap cleanup EXIT

cp "${DIR}/trix.toml" "${DIR}/main.tx3" "${WORK}/"
(cd "${WORK}" && "${TRIX}" build >/dev/null 2>&1) || die "trix build of the fixture protocol failed"
TII="${WORK}/.tx3/tii/${SCOPE}/${NAME}/${VERSION}/main.tii"
[[ -f "${TII}" ]] || die "fixture TII missing at ${TII}"
FIXTURE_SHA="fixture-$(git -C "${HERE}" rev-parse HEAD 2>/dev/null || echo local)"

python3 "${HERE}/fixture_registry.py" --tii "${TII}" --source "${WORK}/main.tx3" \
  --scope "${SCOPE}" --name "${NAME}" --version "${VERSION}" --commit-sha "${FIXTURE_SHA}" \
  --port-file "${WORK}/registry.port" --digest-file "${WORK}/registry.digest" &
REGISTRY_PID=$!
for _ in $(seq 1 50); do [[ -s "${WORK}/registry.port" ]] && break; sleep 0.1; done
[[ -s "${WORK}/registry.port" ]] || die "fixture registry did not start"

[[ -n "${CHECK_TX3C_PATH:-}" ]] && export TX3_TX3C_PATH="${CHECK_TX3C_PATH}"
TII_DIGEST="sha256:$(if command -v sha256sum >/dev/null; then sha256sum "${TII}"; else shasum -a 256 "${TII}"; fi | cut -d' ' -f1)"
bash "${HERE}/check.sh" --ref "${SCOPE}/${NAME}:${VERSION}" \
  --manifest-digest "$(cat "${WORK}/registry.digest")" --tii-digest "${TII_DIGEST}" \
  --git-sha "${FIXTURE_SHA}" --profile preprod --network fixture --operation "${OPERATION}" \
  --args "${DIR}/${OPERATION}.json" \
  --registry "http://127.0.0.1:$(cat "${WORK}/registry.port")" ${PASS[@]+"${PASS[@]}"}
