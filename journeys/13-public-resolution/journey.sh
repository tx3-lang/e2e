#!/usr/bin/env bash
#
# Journey 13 — public resolution. See README.md for what this covers.
# Run via e2e/run.sh, which provides $TRIX and an isolated working directory.

source "${E2E_LIB:?E2E_LIB not set — run this journey via e2e/run.sh}"

JOURNEY_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY="${JOURNEY_HOME}/../../inventory/lib/inventory.py"

journey_begin "13-public-resolution" "pull a released interface, verify its digests, resolve its example on the public TRP"

# The inventory refresh supplies one release's spec; without it there is
# nothing to verify, so the journey skips green in the offline suite.
SPEC="${PUBLIC_RESOLUTION_SPEC:-}"
if [[ -z "${SPEC}" ]]; then
  skip "PUBLIC_RESOLUTION_SPEC not set — skipping (inventory/REFRESH.md supplies it per release)"
  journey_end
  exit 0
fi
[[ -f "${SPEC}" ]] || die "PUBLIC_RESOLUTION_SPEC=${SPEC} is not a file"
command -v jq >/dev/null 2>&1 || die "jq is required to read the spec"
command -v python3 >/dev/null 2>&1 || die "python3 is required to decode the result"
OUT="${PUBLIC_RESOLUTION_OUT:-${PWD}/evidence}"
mkdir -p "${OUT}"
rm -f "${OUT}/resolution.json" "${OUT}/registry.json"

field() { jq -r "$1 // empty" "${SPEC}"; }
scope="$(field .identity.scope)"; name="$(field .identity.name)"
version="$(field .identity.version)"; network="$(field .identity.network)"
ref="${scope}/${name}:${version}"

# A refresh after the release's resolution passed keeps that evidence and
# rechecks only the registry entry (inventory/REFRESH.md), so a later failure
# is recorded against the registry.
KIND=resolution
[[ "$(jq -r '.resolve' "${SPEC}")" == "false" ]] && KIND=registry

# last_line <file> — the last non-blank line, without diagnostic box drawing.
last_line() { grep -v '^[[:space:]]*$' "$1" | tail -n1 | sed 's/^[^[:alnum:]]*//'; }

# Every failure leaves a dated record that keeps the row outstanding with the reason.
record_error() { python3 "${INVENTORY}" "$1" --spec "${SPEC}" --out "${OUT}" --error "$2" >/dev/null; }
outstanding() { record_error "${KIND}" "$1"; die "$1"; }

# check <kind> <args…> — write one record; a check that leaves none still records why.
check() {
  local kind="$1"; shift
  if python3 "${INVENTORY}" "${kind}" --spec "${SPEC}" --out "${OUT}" "$@" > "${LAST_OUTPUT_FILE}" 2>&1; then
    ok "$(cat "${LAST_OUTPUT_FILE}")"
    return 0
  fi
  err "$(cat "${LAST_OUTPUT_FILE}")"
  [[ -f "${OUT}/${kind}.json" ]] \
    || record_error "${kind}" "the ${kind} check left no record: $(last_line "${LAST_OUTPUT_FILE}")"
  return 1
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# 1. A fresh consumer: an empty project and cache, then an anonymous pull.
mkdir consumer && cd consumer
info "→ trix use ${ref} — pull the release into an empty cache"
if ! "${TRIX}" use "${ref}" > "${LAST_OUTPUT_FILE}" 2>&1; then
  cat "${LAST_OUTPUT_FILE}" >&2
  outstanding "registry pull of ${ref} failed: $(last_line "${LAST_OUTPUT_FILE}")"
fi
CACHE=".tx3/tii/${scope}/${name}/${version}"
[[ -f "${CACHE}/main.tii" && -f "${CACHE}/metadata.json" ]] || outstanding "the pull left no cached TII for ${ref}"
ok "pulled ${ref}"

# 2. Both digests, and the commit when the registry records one, are the release's.
manifest="$(jq -r '.digest // empty' "${CACHE}/metadata.json")"
[[ "${manifest}" == "$(field .identity.manifest_digest)" ]] \
  || outstanding "manifest digest ${manifest} differs from the release's"
tii="sha256:$(sha256_of "${CACHE}/main.tii")"
[[ "${tii}" == "$(field .identity.tii_digest)" ]] || outstanding "TII digest ${tii} differs from the release's"
commit="$(jq -r '.commit_sha // empty' "${CACHE}/metadata.json")"
[[ -z "${commit}" || "${commit}" == "$(field .identity.git_sha)" ]] \
  || outstanding "published commit ${commit} differs from the release's"
ok "manifest ${manifest} and TII ${tii} match the release"

# 3. Resolve the example twice on the network's public TRP: live chain state
# in, unsigned CBOR out, nothing signed or submitted. The key is the public
# one trix ships for that endpoint.
failed=0
if [[ "${KIND}" == "resolution" ]]; then
  trp="$(python3 "${INVENTORY}" endpoint --network "${network}" 2> endpoint.err)" \
    || outstanding "$(last_line endpoint.err)"
  endpoint="${TRP_ENDPOINT:-${trp% *}}"
  python3 "${INVENTORY}" request --spec "${SPEC}" --tii "${CACHE}/main.tii" > request.json 2> request.err \
    || outstanding "$(last_line request.err)"
  for n in 1 2; do
    info "→ trp.resolve ${n}/2 on ${endpoint}"
    curl -sS --max-time 120 -X POST "${endpoint}" -H 'content-type: application/json' \
      -H "dmtr-api-key: ${TRP_API_KEY:-${trp#* }}" --data @request.json -o "response-${n}.json" || true
  done
  check resolution --endpoint "${endpoint}" --response response-1.json --response response-2.json || failed=1
else
  info "the release's resolution already passed; rechecking only its registry entry"
fi

# 4. The registry entry: the README's bundle references, and every link answers.
check registry --readme "${CACHE}/README.md" || failed=1

info "evidence records written to ${OUT}"
[[ "${failed}" == "0" ]] || die "${ref} stays outstanding; the records say why"
journey_end
