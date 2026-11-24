#!/usr/bin/env bash
#
# Journey 13 — client-check harness tests. See README.md for coverage.
# Run via e2e/run.sh, which provides $TRIX and an isolated working directory.
# The six-language release runs live in .github/workflows/client-checks.yml.
#
#@ min-tx3c: 0.25.0

source "${E2E_LIB:?E2E_LIB not set — run this journey via e2e/run.sh}"

JOURNEY_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE="${JOURNEY_HOME}/fixture.sh"
HELPER="${JOURNEY_HOME}/client_check.py"

journey_begin "13-client-checks" "release-scoped client checks: positive and negative harness tests on a controlled fixture"

for tool in python3 node npm; do
  command -v "${tool}" >/dev/null 2>&1 || die "${tool} is required for the client-check harness tests"
done

# record_is <record> <pass|fail> [<reason substring>] — the record's verdict.
record_is() {
  local file="$1" want="$2" reason="${3:-}" got why
  [[ -f "${file}" ]] || die "no record written at ${file}"
  got="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["result"])' "${file}")"
  why="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("reason",""))' "${file}")"
  [[ "${got}" == "${want}" ]] || die "$(basename "${file}"): expected ${want}, got ${got} (${why})"
  [[ -z "${reason}" || "${why}" == *"${reason}"* ]] \
    || die "$(basename "${file}"): expected reason containing '${reason}', got '${why}'"
  ok "$(basename "${file}" .json): ${want}${why:+ — ${why}}"
}

# 1. Positive: the typed Python client binds every primitive parameter kind and
# resolves the requested operation with the fixture's arguments.
run_cmd "python settle — positive" bash "${FIXTURE}" --lang python --operation settle --out "${PWD}/py-settle.json" --workdir "${PWD}/py-settle"
record_is py-settle.json pass
run_cmd "python place_order — bytes and multi-word names" \
  bash "${FIXTURE}" --lang python --operation place_order --out "${PWD}/py-order.json" --workdir "${PWD}/py-order"
record_is py-order.json pass
run_cmd "typescript settle — positive" bash "${FIXTURE}" --lang typescript --operation settle --out "${PWD}/ts-settle.json" --workdir "${PWD}/ts-settle"
record_is ts-settle.json pass

# 2. Negative: none of these may produce a successful record.
negative() { local out="$1"; shift; bash "${FIXTURE}" --out "${PWD}/${out}" --workdir "${PWD}/${out%.json}" "$@" >"${out%.json}.log" 2>&1 && die "${out}: check.sh exited 0"; }
ZERO="sha256:$(printf '0%.0s' $(seq 1 64))"
negative bad-manifest.json --lang python --manifest-digest "${ZERO}"
record_is bad-manifest.json fail "manifest digest"
negative bad-tii.json --lang python --tii-digest "${ZERO}"
record_is bad-tii.json fail "TII digest"
negative bad-commit.json --lang python --git-sha 0000000
record_is bad-commit.json fail "source commit"
negative bad-operation.json --lang python --operation withdraw --args "${JOURNEY_HOME}/fixture/settle.json"
record_is bad-operation.json fail "input fixture binding"

# A tx3c that reports its version but renders nothing leaves no client to build.
REAL_TX3C="${TX3_TX3C_PATH:-$(command -v tx3c 2>/dev/null || echo "${HOME}/.tx3/default/bin/tx3c")}"
printf '#!/bin/sh\n[ "$1" = --version ] && echo "%s"\nexit 0\n' "$("${REAL_TX3C}" --version)" > fake-tx3c
chmod +x fake-tx3c
CHECK_TX3C_PATH="${PWD}/fake-tx3c" negative no-client.json --lang python
record_is no-client.json fail "no generated client at"

# An unreachable package index leaves no runtime to build against.
PIP_INDEX_URL="http://127.0.0.1:9/simple" PIP_NO_CACHE_DIR=1 negative no-runtime.json --lang python
record_is no-runtime.json fail "public runtime"

# A fixture value of the wrong type fails the typed host build.
python3 -c 'import json,sys; a=json.load(open(sys.argv[1])); a["quantity"]="lots"; print(json.dumps(a))' \
  "${JOURNEY_HOME}/fixture/settle.json" > wrong-type.json
negative bad-build.json --lang typescript --args "${PWD}/wrong-type.json"
record_is bad-build.json fail "host build"

# The generated TypeScript client sends camelCase keys and raw byte arrays
# (tracked upstream in tx3c's ts-client template); the request check must catch it.
if bash "${FIXTURE}" --lang typescript --operation place_order --out "${PWD}/ts-order.json" --workdir "${PWD}/ts-order" >ts-order.log 2>&1; then
  warn "XPASS: typescript place_order now passes — drop this expected failure"
else
  record_is ts-order.json fail "argument 'datum_tag' was sent as"
fi

# 3. Request check: a recording for another operation or other arguments fails.
cp "${JOURNEY_HOME}/fixture/trix.toml" "${JOURNEY_HOME}/fixture/main.tx3" .
run_cmd "trix build — fixture TII for the request checks" "${TRIX}" build
TII=".tx3/tii/e2e/client-check/0.1.0/main.tii"
python3 - "${TII}" "${JOURNEY_HOME}/fixture/settle.json" <<'PY'
import json, sys
tii, args = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
good = {"tir": tii["transactions"]["settle"]["tir"], "args": dict(args)}
for name, params in {
    "ok": good,
    "other-tx": {**good, "tir": tii["transactions"]["place_order"]["tir"]},
    "other-args": {**good, "args": {**args, "quantity": 1}},
    "wrong-tag": {**good, "args": {**args, "quantity": {"bytes": "1e8480"}}},
}.items():
    open(f"rec-{name}.jsonl", "w").write(json.dumps({"method": "trp.resolve", "params": params}) + "\n")
PY
verify() { python3 "${HELPER}" verify --tii "${TII}" --operation settle --profile preprod \
  --args "${JOURNEY_HOME}/fixture/settle.json" --record "$1"; }
run_cmd "request check accepts the matching recording" verify rec-ok.jsonl
for bad in other-tx other-args wrong-tag; do
  verify "rec-${bad}.jsonl" >/dev/null 2>&1 && die "request check accepted rec-${bad}.jsonl"
  ok "request check rejects ${bad}"
done

# 4. Combined result: six passing languages pass; one incomplete language leaves
# five successful rows and a failed overall result.
IDENTITY=()
while IFS= read -r arg; do IDENTITY+=("${arg}"); done < <(python3 - py-settle.json <<'PY'
import json, sys
row = json.load(open(sys.argv[1]))
for key in ["scope", "name", "version", "manifest_digest", "tii_digest", "git_sha", "network", "operation"]:
    print("--" + key.replace("_", "-"))
    print(row[key])
PY
)
python3 - py-settle.json <<'PY'
import json, sys
row = json.load(open(sys.argv[1]))
for lang in ["rust", "python", "go", "typescript", "java", "swift"]:
    json.dump({**row, "language": lang}, open(f"row-{lang}.json", "w"))
json.dump({**row, "language": "swift", "result": "fail", "reason": "host build failed"}, open("row-swift-fail.json", "w"))
json.dump({**row, "language": "swift", "runtime_version": ""}, open("row-swift-blank.json", "w"))
json.dump({**row, "language": "swift", "tii_digest": "sha256:other"}, open("row-swift-other.json", "w"))
PY
combine() { local out="$1"; shift; python3 "${HELPER}" combine "${IDENTITY[@]}" --date now --run-url local --out "${out}" "$@"; }
FIVE=(row-rust.json row-python.json row-go.json row-typescript.json row-java.json)
run_cmd "combine — six passing languages" combine all.json "${FIVE[@]}" row-swift.json
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert r["result"]=="pass" and r["passed"]==6, r' all.json \
  || die "six passing rows did not combine to a pass"
ok "six passing rows combine to an overall pass"
python3 "${HELPER}" combine --identity-from py-settle.json --date now --run-url local --out from.json \
  "${FIVE[@]}" row-swift.json >/dev/null || die "combine --identity-from did not pass six rows"
run_cmd "summary — Markdown table of the combined result" python3 "${HELPER}" summary from.json
assert_output_contains "| swift | pass |" "summary lists every language"
for variant in fail blank other missing; do
  rows=("${FIVE[@]}"); [[ "${variant}" != missing ]] && rows+=("row-swift-${variant}.json")
  combine "five-${variant}.json" "${rows[@]}" >/dev/null && die "combine passed with swift ${variant}"
  python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert r["result"]=="fail" and r["passed"]==5 and len(r["languages"])==6, r' \
    "five-${variant}.json" || die "swift ${variant}: expected five successful rows and a failed result"
  ok "swift ${variant}: five successful rows, overall fail"
done

journey_end
