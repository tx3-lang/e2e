#!/usr/bin/env bash
#
# Run check.sh against the controlled fixture release instead of a public one:
# build fixture/ with the released trix, serve it from a local OCI registry and
# pass its identity. Later arguments override the fixture's (a wrong digest, a
# different operation), which is how the negative harness tests are written.
# A fixture pass proves the harness only; it is never an onboarding record.
#
# Usage: fixture.sh --lang <language> --operation <tx> --out <record.json> [check.sh args...]
# Env: CHECK_TX3C_PATH replaces tx3c for the check only, not the fixture build.

set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../lib/common.sh
source "${HERE}/../../lib/common.sh"
TRIX="${TRIX:-trix}"
OPERATION="settle"
for ((i = 1; i < $#; i++)); do [[ "${!i}" == "--operation" ]] && { j=$((i + 1)); OPERATION="${!j}"; }; done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/client-check-fixture.XXXXXX")"
REGISTRY_PID=""
cleanup() { [[ -n "${REGISTRY_PID}" ]] && kill "${REGISTRY_PID}" 2>/dev/null; rm -rf "${WORK}"; }
trap cleanup EXIT

cp "${HERE}/fixture/trix.toml" "${HERE}/fixture/main.tx3" "${WORK}/"
(cd "${WORK}" && "${TRIX}" build >/dev/null 2>&1) || die "trix build of the fixture protocol failed"
TII="${WORK}/.tx3/tii/e2e/client-check/0.1.0/main.tii"
[[ -f "${TII}" ]] || die "fixture TII missing at ${TII}"
FIXTURE_SHA="fixture-$(git -C "${HERE}" rev-parse HEAD 2>/dev/null || echo local)"

python3 "${HERE}/fixture_registry.py" --tii "${TII}" --source "${WORK}/main.tx3" \
  --scope e2e --name client-check --version 0.1.0 --commit-sha "${FIXTURE_SHA}" \
  --port-file "${WORK}/registry.port" --digest-file "${WORK}/registry.digest" &
REGISTRY_PID=$!
for _ in $(seq 1 50); do [[ -s "${WORK}/registry.port" ]] && break; sleep 0.1; done
[[ -s "${WORK}/registry.port" ]] || die "fixture registry did not start"

[[ -n "${CHECK_TX3C_PATH:-}" ]] && export TX3_TX3C_PATH="${CHECK_TX3C_PATH}"
TII_DIGEST="sha256:$(if command -v sha256sum >/dev/null; then sha256sum "${TII}"; else shasum -a 256 "${TII}"; fi | cut -d' ' -f1)"
bash "${HERE}/check.sh" --ref e2e/client-check:0.1.0 \
  --manifest-digest "$(cat "${WORK}/registry.digest")" --tii-digest "${TII_DIGEST}" \
  --git-sha "${FIXTURE_SHA}" --profile preprod --network fixture --operation "${OPERATION}" \
  --args "${HERE}/fixture/${OPERATION}.json" \
  --registry "http://127.0.0.1:$(cat "${WORK}/registry.port")" "$@"
