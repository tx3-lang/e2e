#!/usr/bin/env bash
#
# One language record for one published interface release: pull it with
# `trix use` into an empty consumer, check its manifest, TII and source
# identity, generate the typed client with the released first-party plugin,
# build a consumer against the public runtime package, and resolve the
# operation through a recording TRP. Always writes a record to --out; the
# record passes only when every step did. See README.md.
#
# Usage: check.sh --lang <rust|python|go|typescript|java|swift>
#          --ref <scope>/<name>:<version> --manifest-digest sha256:<hex>
#          --tii-digest sha256:<hex> --git-sha <sha> --profile <name>
#          --operation <tx> --args <input.json> --out <record.json>
#          [--network <name>] [--registry <url>] [--run-url <url>]
#          [--workdir <dir>]
# Env: TRIX (trix binary, default `trix`), TX3_TX3C_PATH or TX3_HOME (the
# tx3c trix runs, resolved as trix does), PYTHON (interpreter for the Python
# consumer, default `python3`).

set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../lib/common.sh
source "${HERE}/../../lib/common.sh"
HELPER="${HERE}/client_check.py"
# Keep the failing step in the record, not only in the log.
DETAIL=""
die() { DETAIL="$*"; err "$*"; exit 1; }
run() { DETAIL="$1"; run_cmd "$@"; DETAIL=""; }
TRIX="${TRIX:-trix}"

LANG_ID="" REF="" MANIFEST_DIGEST="" TII_DIGEST="" GIT_SHA="" PROFILE="" OPERATION=""
ARGS_FILE="" OUT="" NETWORK="" REGISTRY="" RUN_URL="${RUN_URL:-local}" WORKDIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang) LANG_ID="$2" ;;             --ref) REF="$2" ;;
    --manifest-digest) MANIFEST_DIGEST="$2" ;; --tii-digest) TII_DIGEST="$2" ;;
    --git-sha) GIT_SHA="$2" ;;           --profile) PROFILE="$2" ;;
    --operation) OPERATION="$2" ;;       --args) ARGS_FILE="$2" ;;
    --out) OUT="$2" ;;                   --network) NETWORK="$2" ;;
    --registry) REGISTRY="$2" ;;         --run-url) RUN_URL="$2" ;;
    --workdir) WORKDIR="$2" ;;
    *) die "unknown argument: $1" ;;
  esac
  shift 2
done
[[ -n "${OUT}" ]] || die "--out is required"
mkdir -p "$(dirname "${OUT}")" || die "cannot create the directory of --out ${OUT}"
OUT="$(cd "$(dirname "${OUT}")" && pwd)/$(basename "${OUT}")"
NETWORK="${NETWORK:-${PROFILE}}"
SCOPE="${REF%%/*}"; rest="${REF#*/}"; NAME="${rest%%:*}"; VERSION="${rest#*:}"

RUNTIME_PACKAGE="" RUNTIME_VERSION="" RELEASE_DATE="" STAGE="argument check" MOCK_PID="" OWN_WORKDIR=""
TRIX_VERSION="$("${TRIX}" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
# The tx3c trix runs: TX3_TX3C_PATH when set, else the default channel under TX3_HOME.
if [[ -n "${TX3_TX3C_PATH+set}" ]]; then TX3C="${TX3_TX3C_PATH}"; else TX3C="${TX3_HOME:-${HOME}/.tx3}/default/bin/tx3c"; fi
TX3C_VERSION="$("${TX3C}" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"

# The record is written on every exit, so a failure at any stage stays visible.
write_record() {
  local rc=$? result="pass" reason=""
  [[ -n "${MOCK_PID}" ]] && kill "${MOCK_PID}" 2>/dev/null
  [[ -n "${OWN_WORKDIR}" ]] && rm -rf "${OWN_WORKDIR}"
  if [[ "${rc}" -ne 0 ]]; then result="fail"; reason="${STAGE} failed${DETAIL:+: ${DETAIL}}"; fi
  python3 "${HELPER}" row --scope "${SCOPE}" --name "${NAME}" --version "${VERSION}" \
    --manifest-digest "${MANIFEST_DIGEST}" --tii-digest "${TII_DIGEST}" --git-sha "${GIT_SHA}" \
    --release-date "${RELEASE_DATE}" \
    --network "${NETWORK}" --operation "${OPERATION}" --language "${LANG_ID}" \
    --runtime-package "${RUNTIME_PACKAGE}" --runtime-version "${RUNTIME_VERSION}" \
    --tx3c-version "${TX3C_VERSION}" --trix-version "${TRIX_VERSION}" --run-url "${RUN_URL}" \
    --date "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --result "${result}" --reason "${reason}" --out "${OUT}" \
    || { err "${LANG_ID}: could not write the record to ${OUT}"; exit 1; }
  [[ "${result}" == "pass" ]] && ok "${LANG_ID}: record passed" || err "${LANG_ID}: ${reason}"
  exit "${rc}"
}
trap write_record EXIT

for v in LANG_ID REF MANIFEST_DIGEST TII_DIGEST GIT_SHA PROFILE OPERATION ARGS_FILE; do
  [[ -n "${!v}" ]] || die "missing required argument for ${v}"
done
[[ "${REF}" == */*:* ]] || die "--ref must be <scope>/<name>:<version>, got ${REF}"
ARGS_FILE="$(cd "$(dirname "${ARGS_FILE}")" && pwd)/$(basename "${ARGS_FILE}")"
case "${LANG_ID}" in
  rust) PLUGIN=rust-client TOOLS="cargo" ;;   python) PLUGIN=python-client TOOLS="${PYTHON:-python3}" ;;
  go) PLUGIN=go-client TOOLS="go" ;;           typescript) PLUGIN=ts-client TOOLS="node npm" ;;
  java) PLUGIN=java-client TOOLS="java mvn" ;; swift) PLUGIN=swift-client TOOLS="swift git" ;;
  *) die "unsupported language: ${LANG_ID}" ;;
esac

STAGE="host toolchain check"
for tool in ${TOOLS}; do command -v "${tool}" >/dev/null 2>&1 || die "${tool} not found"; done
[[ -n "${TRIX_VERSION}" ]] || die "cannot read a version from trix at ${TRIX}"
[[ -n "${TX3C_VERSION}" ]] || die "cannot read a version from tx3c at ${TX3C}"

# A workdir the caller names is kept for inspection; one made here is removed.
[[ -n "${WORKDIR}" ]] || { WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/client-check.XXXXXX")"; OWN_WORKDIR="${WORKDIR}"; }
mkdir -p "${WORKDIR}/consumer" && cd "${WORKDIR}/consumer" || die "cannot enter ${WORKDIR}"
[[ -e .tx3 || -e trix.toml ]] && die "consumer workdir is not empty: ${PWD}"
export LAST_OUTPUT_FILE="${WORKDIR}/.last_cmd_output"

STAGE="registry pull"
{
  printf '[protocol]\nname = "consumer"\nversion = "0.1.0"\nmain = "main.tx3"\n\n'
  printf '[ledger]\nfamily = "cardano"\n'
  [[ -n "${REGISTRY}" ]] && printf '\n[registry]\nurl = "%s"\n' "${REGISTRY}"
} > trix.toml
run "trix use ${REF} — pull into an empty cache" "${TRIX}" use "${REF}"

STAGE="release identity check"
CACHE=".tx3/tii/${SCOPE}/${NAME}/${VERSION}"
assert_exists "${CACHE}/main.tii" "interface cached at ${CACHE}"
pulled() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]) or "")' "${CACHE}/metadata.json" "$1"; }
sha256_of() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
[[ "$(pulled digest)" == "${MANIFEST_DIGEST}" ]] \
  || die "manifest digest $(pulled digest) does not match expected ${MANIFEST_DIGEST}"
grep -qF "digest = \"${MANIFEST_DIGEST}\"" trix.toml || die "trix.toml pin does not carry ${MANIFEST_DIGEST}"
[[ "sha256:$(sha256_of "${CACHE}/main.tii")" == "${TII_DIGEST}" ]] \
  || die "TII digest sha256:$(sha256_of "${CACHE}/main.tii") does not match expected ${TII_DIGEST}"
[[ "$(pulled commit_sha)" == "${GIT_SHA}" ]] \
  || die "release source commit '$(pulled commit_sha)' does not match expected ${GIT_SHA}"
RELEASE_DATE="$(python3 -c 'import datetime as d,sys; print(d.datetime.fromtimestamp(int(sys.argv[1]), d.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$(pulled published_date)" 2>/dev/null)" \
  || die "release carries no published date"
ok "manifest, TII and source commit match the release identity"
TII="${PWD}/${CACHE}/main.tii"

STAGE="input fixture binding"
render() { python3 "${HELPER}" render --tii "${TII}" --operation "${OPERATION}" \
  --profile "${PROFILE}" --args "${ARGS_FILE}" --lang "${LANG_ID}" "$@"; }
verdict="$(render --out "${WORKDIR}/binding-check" 2>&1)" || die "${verdict#client-check: }"

STAGE="client generation"
run "trix codegen --plugin ${PLUGIN}" "${TRIX}" codegen --plugin "${PLUGIN}"
grep -qiF "Reading template from" "${LAST_OUTPUT_FILE}" && die "${PLUGIN} was downloaded, not the released built-in"
GEN="${PWD}/.tx3/codegen/${PLUGIN}/${NAME}"
[[ -d "${GEN}" ]] && find "${GEN}" -type f | grep -q . || die "no generated client at ${GEN}"
ok "generated client at ${GEN}"

APP="${WORKDIR}/app"
mkdir -p "${APP}"
dep_line() { grep -m1 -E "$1" "$2" | sed 's/^[[:space:]]*//; s/,[[:space:]]*$//'; }

STAGE="host build"
case "${LANG_ID}" in
  rust)
    mkdir -p "${APP}/src"
    printf '[package]\nname = "client-check-consumer"\nversion = "0.0.0"\nedition = "2021"\n\n[workspace]\n\n[dependencies]\n%s = { path = "%s" }\n%s\ntokio = { version = "1", features = ["macros", "rt-multi-thread"] }\n' \
      "$(sed -n 's/^name = "\(.*\)"/\1/p' "${GEN}/Cargo.toml" | head -n1)" "${GEN}" \
      "$(dep_line '^tx3-sdk' "${GEN}/Cargo.toml")" > "${APP}/Cargo.toml"
    render --out "${APP}/src/main.rs"
    run "cargo build — generated client and consumer" cargo build --quiet --manifest-path "${APP}/Cargo.toml"
    RUNTIME_PACKAGE="crates.io/tx3-sdk"
    RUNTIME_VERSION="$(grep -A1 '^name = "tx3-sdk"' "${APP}/Cargo.lock" | sed -n 's/^version = "\(.*\)"/\1/p')"
    EXEC=("${APP}/target/debug/client-check-consumer") ;;
  python)
    cp -R "${GEN}" "${APP}/generated_client"
    render --out "${APP}/main.py"
    run "python venv" "${PYTHON:-python3}" -m venv "${APP}/.venv"
    run "pip install -r requirements.txt — public runtime" \
      "${APP}/.venv/bin/pip" install --quiet -r "${GEN}/requirements.txt"
    RUNTIME_PACKAGE="pypi.org/tx3-sdk"
    RUNTIME_VERSION="$("${APP}/.venv/bin/python" -c 'import importlib.metadata as m; print(m.version("tx3-sdk"))')"
    EXEC=("${APP}/.venv/bin/python" "${APP}/main.py") ;;
  go)
    MODULE="$(sed -n 's/^module //p' "${GEN}/go.mod")"
    printf 'module client-check-consumer\n\ngo %s\n\nrequire %s v0.0.0\n\nreplace %s => "%s"\n' \
      "$(sed -n 's/^go //p' "${GEN}/go.mod")" "${MODULE}" "${MODULE}" "${GEN}" > "${APP}/go.mod"
    render --module "${MODULE}" --out "${APP}/main.go"
    run "go mod tidy — public runtime" sh -c "cd '${APP}' && go mod tidy"
    run "go build — generated client and consumer" sh -c "cd '${APP}' && go build -o consumer ."
    RUNTIME_PACKAGE="proxy.golang.org/github.com/tx3-lang/go-sdk/sdk"
    RUNTIME_VERSION="$(cd "${APP}" && go list -m -f '{{.Version}}' github.com/tx3-lang/go-sdk/sdk)"
    EXEC=("${APP}/consumer") ;;
  typescript)
    cp "${GEN}/protocol.ts" "${APP}/"
    printf '{ "name": "client-check-consumer", "private": true, "type": "module" }\n' > "${APP}/package.json"
    render --out "${APP}/main.ts"
    run "npm install tx3-sdk — public runtime" sh -c \
      "cd '${APP}' && npm install --no-fund --no-audit --loglevel=error tx3-sdk typescript @types/node"
    run "tsc — generated client and consumer" sh -c "cd '${APP}' && npx tsc --strict \
      --target ES2022 --module node16 --moduleResolution node16 --types node --skipLibCheck --outDir dist protocol.ts main.ts"
    RUNTIME_PACKAGE="npmjs.com/tx3-sdk"
    RUNTIME_VERSION="$(node -p 'require(process.argv[1]).version' "${APP}/node_modules/tx3-sdk/package.json")"
    EXEC=(node "${APP}/dist/main.js") ;;
  java)
    pom() { python3 - "$1" "$2" <<'PY'
import sys, xml.etree.ElementTree as ET
ns = {"m": "http://maven.apache.org/POM/4.0.0"}
print(ET.parse(sys.argv[1]).getroot().findtext(sys.argv[2], namespaces=ns) or "")
PY
    }
    M2="${WORKDIR}/m2"
    RUNTIME_VERSION="$(pom "${GEN}/pom.xml" m:properties/m:tx3.sdk.version)"
    run "mvn install — generated client against the public runtime" \
      mvn -B -ntp -q -Dmaven.repo.local="${M2}" -DskipTests -f "${GEN}/pom.xml" install
    mkdir -p "${APP}/src/main/java/e2e"
    sed -e "s|__GROUP__|$(pom "${GEN}/pom.xml" m:groupId)|" -e "s|__ARTIFACT__|$(pom "${GEN}/pom.xml" m:artifactId)|" \
      -e "s|__VERSION__|$(pom "${GEN}/pom.xml" m:version)|" "${HERE}/consumer-pom.xml" > "${APP}/pom.xml"
    render --out "${APP}/src/main/java/e2e/Consumer.java"
    run "mvn verify — consumer" mvn -B -ntp -q -Dmaven.repo.local="${M2}" -f "${APP}/pom.xml" verify
    run "mvn dependency:build-classpath" mvn -B -ntp -q -Dmaven.repo.local="${M2}" \
      -Dmdep.outputFile=target/classpath.txt -f "${APP}/pom.xml" dependency:build-classpath
    RUNTIME_PACKAGE="central.sonatype.com/land.tx3/tx3-sdk"
    EXEC=(java -cp "${APP}/target/classes:$(cat "${APP}/target/classpath.txt")" e2e.Consumer) ;;
  swift)
    MODULE="$(sed -n 's/^ *name: "\(.*\)",$/\1/p' "${GEN}/Package.swift" | head -n1)"
    mkdir -p "${APP}/Sources/Consumer"
    # BigInt is a dependency only when the interface has integers (tx3c adds it then).
    BIGINT="$(dep_line 'github.com/attaswift/BigInt' "${GEN}/Package.swift")"
    BIGINT_PRODUCT='.product(name: "BigInt", package: "BigInt"),'
    cat > "${APP}/Package.swift" <<EOF
// swift-tools-version: 6.1
import PackageDescription

let package = Package(
  name: "Consumer",
  platforms: [.macOS(.v14)],
  dependencies: [
    .package(path: "${GEN}"),
    $(dep_line 'github.com/tx3-lang/swift-sdk' "${GEN}/Package.swift"),${BIGINT:+
    ${BIGINT},}
  ],
  targets: [
    .executableTarget(name: "Consumer", dependencies: [
      .product(name: "${MODULE}", package: "${NAME}"),
      .product(name: "Tx3SDK", package: "swift-sdk"),${BIGINT:+
      ${BIGINT_PRODUCT}}
    ])
  ]
)
EOF
    render ${BIGINT:+--bigint} --out "${APP}/Sources/Consumer/main.swift"
    run "swift build — generated client and consumer" swift build --package-path "${APP}" -c debug
    RUNTIME_PACKAGE="github.com/tx3-lang/swift-sdk"
    RUNTIME_VERSION="$(python3 -c 'import json,sys; print(next(p["state"].get("version","") for p in json.load(open(sys.argv[1]))["pins"] if p["identity"] == "swift-sdk"))' "${APP}/Package.resolved")"
    EXEC=("${APP}/.build/debug/Consumer") ;;
esac
[[ -n "${RUNTIME_VERSION}" ]] || die "could not identify the resolved runtime package version"
ok "built against ${RUNTIME_PACKAGE} ${RUNTIME_VERSION}"

STAGE="typed call"
python3 "${HELPER}" mock-trp --record "${WORKDIR}/trp.jsonl" --port-file "${WORKDIR}/trp.port" &
MOCK_PID=$!
for _ in $(seq 1 50); do [[ -s "${WORKDIR}/trp.port" ]] && break; sleep 0.1; done
[[ -s "${WORKDIR}/trp.port" ]] || die "recording TRP did not start"
run "${OPERATION} through the generated ${LANG_ID} client" \
  "${EXEC[@]}" "http://127.0.0.1:$(cat "${WORKDIR}/trp.port")"

STAGE="request check"
verdict="$(python3 "${HELPER}" verify --tii "${TII}" --operation "${OPERATION}" \
  --profile "${PROFILE}" --args "${ARGS_FILE}" --record "${WORKDIR}/trp.jsonl" 2>&1)" \
  || die "${verdict#client-check: }"
ok "${verdict}"
