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

# field_is <record> <field> <value> — one field of a record.
field_is() {
  local got; got="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$1" "$2")"
  [[ "${got}" == "$3" ]] || die "$(basename "$1"): expected $2 '$3', got '${got}'"
  ok "$(basename "$1" .json): $2 ${got}"
}

# 1. Positive: the typed Python client binds every primitive parameter kind and
# resolves the requested operation with the fixture's arguments. The record's
# directory does not exist yet; check.sh creates it.
run_cmd "python settle — positive" bash "${FIXTURE}" --lang python --operation settle --out "${PWD}/records/py-settle.json" --workdir "${PWD}/py-settle"
record_is records/py-settle.json pass
cp records/py-settle.json py-settle.json
field_is py-settle.json release_date 2025-01-01T00:00:00Z
run_cmd "python transfer — an interface with no integer parameter" bash "${FIXTURE}" --fixture fixture-noint \
  --lang python --operation transfer --out "${PWD}/py-noint.json" --workdir "${PWD}/py-noint"
record_is py-noint.json pass
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
python3 -c 'import json,sys; a=json.load(open(sys.argv[1])); a["anchor"]="00\"+x+\"#0"; print(json.dumps(a))' \
  "${JOURNEY_HOME}/fixture/settle.json" > hostile-anchor.json
negative bad-anchor.json --lang python --args "${PWD}/hostile-anchor.json"
record_is bad-anchor.json fail "expected a UtxoRef"

# A tx3c that reports its version but renders nothing leaves no client to build.
if [[ -n "${TX3_TX3C_PATH+set}" ]]; then REAL_TX3C="${TX3_TX3C_PATH}"; else REAL_TX3C="${TX3_HOME:-${HOME}/.tx3}/default/bin/tx3c"; fi
printf '#!/bin/sh\n[ "$1" = --version ] && echo "%s"\nexit 0\n' "$("${REAL_TX3C}" --version)" > fake-tx3c
chmod +x fake-tx3c
CHECK_TX3C_PATH="${PWD}/fake-tx3c" negative no-client.json --lang python
record_is no-client.json fail "no generated client at"

# The recorded tx3c is the one trix runs: TX3_TX3C_PATH, else TX3_HOME's default
# channel, never another tx3c on PATH. A tx3c without a version fails the check.
direct() { ! bash "${JOURNEY_HOME}/check.sh" --lang python --ref e2e/client-check:0.1.0 --manifest-digest "${ZERO}" \
  --tii-digest "${ZERO}" --git-sha 0 --profile preprod --operation settle --args "${JOURNEY_HOME}/fixture/settle.json" \
  --registry http://127.0.0.1:9 --workdir "${PWD}/direct-$1" --out "${PWD}/$1.json" >"$1.log" 2>&1 || die "$1: check.sh exited 0"; }
mkdir -p tx3-home/default/bin
printf '#!/bin/sh\necho "tx3c 9.9.9"\n' > tx3-home/default/bin/tx3c
chmod +x tx3-home/default/bin/tx3c
(unset TX3_TX3C_PATH; TX3_HOME="${PWD}/tx3-home" direct tx3c-home) || exit 1
field_is tx3c-home.json tx3c_version 9.9.9
printf '#!/bin/sh\nexit 0\n' > silent-tx3c
chmod +x silent-tx3c
TX3_TX3C_PATH="${PWD}/silent-tx3c" direct no-version
record_is no-version.json fail "cannot read a version from tx3c"

# A record that cannot be written makes an otherwise passing check exit non-zero.
mkdir -p unwritable.json
bash "${FIXTURE}" --lang python --out "${PWD}/unwritable.json" --workdir "${PWD}/unwritable" >unwritable.log 2>&1 \
  && die "check.sh exited 0 without writing its record"
grep -q "could not write the record" unwritable.log || die "unwritable record: no write error in the log"
ok "an unwritable record fails the check"

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
    "swapped-party": {**good, "args": {**args, "sender": args["receiver"], "receiver": args["sender"]}},
    "missing-party": {**good, "args": {k: v for k, v in args.items() if k != "receiver"}},
    "other-anchor": {**good, "args": {**args, "anchor": "00" * 32 + "#1"}},
    "other-refund": {**good, "args": {**args, "refund": args["receiver"]}},
    "flipped-urgent": {**good, "args": {**args, "urgent": False}},
    "int-urgent": {**good, "args": {**args, "urgent": 1}},
}.items():
    open(f"rec-{name}.jsonl", "w").write(json.dumps({"method": "trp.resolve", "params": params}) + "\n")
PY
python3 - "${TII}" "${JOURNEY_HOME}/fixture/place_order.json" <<'PY'
import json, sys
tii, args = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
good = {"tir": tii["transactions"]["place_order"]["tir"], "args": dict(args)}
for name, params in {
    "order-ok": good,
    "other-bytes": {**good, "args": {**args, "datum_tag": "c0ffef"}},
}.items():
    open(f"rec-{name}.jsonl", "w").write(json.dumps({"method": "trp.resolve", "params": params}) + "\n")
PY
verify() { python3 "${HELPER}" verify --tii "${TII}" --operation "$1" --profile preprod \
  --args "${JOURNEY_HOME}/fixture/$1.json" --record "$2"; }
run_cmd "request check accepts the matching recording" verify settle rec-ok.jsonl
run_cmd "request check accepts the matching place_order recording" verify place_order rec-order-ok.jsonl
# Each case: operation, recording, and the name the rejection must carry.
while read -r op bad field; do
  verify "${op}" "rec-${bad}.jsonl" >"rec-${bad}.log" 2>&1 && die "request check accepted rec-${bad}.jsonl"
  grep -q "${field}" "rec-${bad}.log" || die "rec-${bad}: rejection does not name ${field}: $(cat "rec-${bad}.log")"
  ok "request check rejects ${bad}"
done <<'CASES'
settle other-tx TIR
settle other-args quantity
settle wrong-tag quantity
settle swapped-party receiver
settle missing-party receiver
settle other-anchor anchor
settle other-refund refund
settle flipped-urgent urgent
settle int-urgent urgent
place_order other-bytes datum_tag
CASES
python3 - "${JOURNEY_HOME}" <<'PY' || die "the request check confuses booleans and integers"
import sys
sys.path.insert(0, sys.argv[1])
from client_check import wire_matches
for kind, expected, actual in [("boolean", True, 1), ("boolean", True, {"bool": 1}), ("boolean", False, 0),
                               ("integer", 1, True), ("integer", 0, {"int": False})]:
    assert not wire_matches(kind, expected, actual), (kind, expected, actual)
assert wire_matches("boolean", True, {"bool": True}) and wire_matches("integer", 1, {"int": "1"})
PY
ok "request check keeps booleans and integers apart"

# Release-supplied names must be plain identifiers before they reach consumer source.
python3 - "${TII}" "${JOURNEY_HOME}/fixture/settle.json" <<'PY'
import json, sys
tii, args = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
hostile = "Sender(null); Runtime.getRuntime(); Object o = String.valueOf"
party = json.loads(json.dumps(tii))
party["parties"][hostile] = party["parties"].pop("sender")
json.dump(party, open("hostile-party.tii", "w"))
json.dump({**{k: v for k, v in args.items() if k != "sender"}, hostile: args["sender"]}, open("hostile-party.json", "w"))
param = json.loads(json.dumps(tii))
schema = param["transactions"]["settle"]["params"]
schema["properties"][hostile] = schema["properties"].pop("quantity")
schema["required"] = [hostile if r == "quantity" else r for r in schema["required"]]
json.dump(param, open("hostile-param.tii", "w"))
json.dump({**{k: v for k, v in args.items() if k != "quantity"}, hostile: args["quantity"]}, open("hostile-param.json", "w"))
PY
for what in party param; do
  for lang in java python; do
    python3 "${HELPER}" render --tii "hostile-${what}.tii" --operation settle --profile preprod \
      --args "hostile-${what}.json" --lang "${lang}" --out "hostile-${what}.${lang}" >"hostile-${what}.log" 2>&1 \
      && die "render accepted a hostile ${what} name for ${lang}"
    grep -q "is not a plain identifier" "hostile-${what}.log" || die "hostile ${what}: $(cat "hostile-${what}.log")"
  done
  ok "render rejects a hostile ${what} name"
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
    json.dump({**row, "language": lang, "network": "preprod"}, open(f"preprod-{lang}.json", "w"))
json.dump({**row, "language": "swift", "result": "fail", "reason": "host build failed"}, open("row-swift-fail.json", "w"))
json.dump({**row, "language": "swift", "runtime_version": ""}, open("row-swift-blank.json", "w"))
json.dump({**row, "language": "swift", "tii_digest": "sha256:other"}, open("row-swift-other.json", "w"))
json.dump({**row, "language": "swift", "release_date": ""}, open("row-swift-undated.json", "w"))
json.dump({**row, "language": "swift", "run_url": "https://ci.example/runs/1/attempts/1"}, open("row-swift-earlier.json", "w"))
PY
combine() { local out="$1"; shift; python3 "${HELPER}" combine "${IDENTITY[@]}" --date now --run-url local --out "${out}" "$@"; }
FIVE=(rust=row-rust.json python=row-python.json go=row-go.json typescript=row-typescript.json java=row-java.json)
run_cmd "combine — six passing languages" combine all.json "${FIVE[@]}" swift=row-swift.json
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert r["result"]=="pass" and r["passed"]==6 and r["release_date"], r' all.json \
  || die "six passing rows did not combine to a pass"
ok "six passing rows combine to an overall pass"
python3 "${HELPER}" combine --identity-from py-settle.json --date now --run-url local --out from.json \
  "${FIVE[@]}" swift=row-swift.json >/dev/null || die "combine --identity-from did not pass six rows"
run_cmd "summary — Markdown table of the combined result" python3 "${HELPER}" summary from.json
assert_output_contains "| swift | pass |" "summary lists every language"
# The workflow passes the release reference and the raw network input; an empty
# network defaults to the profile, as in check.sh.
pick() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' py-settle.json "$1"; }
python3 "${HELPER}" combine --release e2e/client-check:0.1.0 --network "" --profile preprod --operation settle \
  --manifest-digest "$(pick manifest_digest)" --tii-digest "$(pick tii_digest)" --git-sha "$(pick git_sha)" \
  --date now --run-url local --out workflow.json \
  rust=preprod-rust.json python=preprod-python.json go=preprod-go.json typescript=preprod-typescript.json \
  java=preprod-java.json swift=preprod-swift.json >/dev/null || die "combine with the workflow's identity and an empty network failed"
ok "an empty network defaults to the profile"
for variant in fail blank other undated earlier wrong-language missing; do
  rows=("${FIVE[@]}")
  case "${variant}" in
    missing) ;;
    wrong-language) rows+=(swift=row-python.json) ;;
    *) rows+=("swift=row-swift-${variant}.json") ;;
  esac
  combine "five-${variant}.json" "${rows[@]}" >/dev/null && die "combine passed with swift ${variant}"
  python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert r["result"]=="fail" and r["passed"]==5 and len(r["languages"])==6, r' \
    "five-${variant}.json" || die "swift ${variant}: expected five successful rows and a failed result"
  ok "swift ${variant}: five successful rows, overall fail"
done

journey_end
