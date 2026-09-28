#!/usr/bin/env bash
#
# Journey 12 — generated Java SDK client. See README.md for coverage.
# Run via e2e/run.sh, which provides $TRIX and an isolated working directory.
#
#@ min-tx3c: 0.25.0

source "${E2E_LIB:?E2E_LIB not set — run this journey via e2e/run.sh}"

JOURNEY_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

journey_begin "12-java-sdk" "generate a Java client → compile a clean consumer → resolve, sign, submit, and confirm (devnet)"

# Java and Maven are host infrastructure. GitHub's selected job installs both;
# a missing CI prerequisite is a failure, while a developer without Java may
# still run the rest of the repository's journeys.
if ! command -v java >/dev/null 2>&1 || ! command -v mvn >/dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then
    die "java and Maven are required for the selected Java SDK CI journey"
  fi
  skip "java/Maven not found — skipping Java SDK journey"
  journey_end
  exit 0
fi

java -version 2>&1 | head -n1 | grep -Eq 'version "21([.]|\")' \
  || die "Java 21 is required for the Java SDK journey"
mvn -version | head -n1 | grep -Eq '^Apache Maven 3[.]9[.]' \
  || die "Maven 3.9 is required for the Java SDK journey"

# 1. Scaffold under a stable name so the generated package and artifact are
# deterministic (`land.tx3.generated.demo.DemoClient`, `demo-client`).
mkdir demo && cd demo
run_cmd "trix init -y — scaffold a new project" "${TRIX}" init -y

# 2. Generate through trix's built-in plugin registration. tx3c renders the
# built-in java-client template; a download would violate released-channel
# hermeticity.
run_cmd "trix codegen --plugin java-client — generate bindings" \
  "${TRIX}" codegen --plugin java-client
assert_output_contains "Added [[codegen]]" "plugin entry seeded into trix.toml"
assert_output_contains "Bindgen successful for 'demo'"
grep -qiF "Reading template from" "${LAST_OUTPUT_FILE}" \
  && die "built-in plugin downloaded templates instead of using tx3c's built-in template"
ok "built-in Java template rendered by tx3c, no template download"

GENERATED=".tx3/codegen/java-client/demo"
assert_exists "${GENERATED}/pom.xml" "generated Maven project exists"
assert_exists "${GENERATED}/src/main/java/land/tx3/generated/demo/DemoClient.java" \
  "typed DemoClient source exists"
[[ -e ".tx3/codegen/java-client/pom.xml" ]] \
  && die "generated Maven project leaked outside the per-protocol subdir"

run_cmd "read the generated Java client" \
  cat "${GENERATED}/src/main/java/land/tx3/generated/demo/DemoClient.java"
assert_output_contains 'PROTOCOL_NAME = "demo"' "protocol identity embedded"
assert_output_contains "TRANSFER_TIR" "transfer TIR envelope embedded"
assert_output_contains "class DemoClient" "typed Java client wrapper emitted"

# 3. Compile the generated project against the released SDK in a fresh local
# repository, then install only that generated artifact for the host fixture.
# An explicit override supports reviewed pre-publication snapshot validation.
M2_REPO="${TX3_JAVA_M2_REPO:-${PWD}/m2}"
SDK_VERSION="${TX3_JAVA_SDK_VERSION:-0.15.0}"
run_cmd "mvn verify — compile the generated Maven project" \
  mvn -B -ntp -Dmaven.repo.local="${M2_REPO}" \
    -Dtx3.sdk.version="${SDK_VERSION}" -f "${GENERATED}/pom.xml" verify
run_cmd "mvn install — stage generated client for a clean consumer" \
  mvn -B -ntp -Dmaven.repo.local="${M2_REPO}" \
    -Dtx3.sdk.version="${SDK_VERSION}" -DskipTests \
    -f "${GENERATED}/pom.xml" install

mkdir app
cp "${JOURNEY_HOME}/pom.xml" app/
mkdir -p app/src/main/java/e2e
cp "${JOURNEY_HOME}/JavaSdkJourney.java" app/src/main/java/e2e/
run_cmd "mvn verify — compile the clean host consumer" \
  mvn -B -ntp -Dmaven.repo.local="${M2_REPO}" \
    -Dtx3.sdk.version="${SDK_VERSION}" -f app/pom.xml verify
run_cmd "mvn dependency:build-classpath — resolve the consumer runtime" \
  mvn -B -ntp -Dmaven.repo.local="${M2_REPO}" \
    -Dtx3.sdk.version="${SDK_VERSION}" -Dmdep.outputFile=target/classpath.txt \
    -f app/pom.xml dependency:build-classpath

# 4. Fund the Java SDK's checksum-verified CIP-1852 test identity. trix's
# conventional wallets intentionally use a different root-key scheme, so this
# explicit fixture keeps signer/address binding honest while remaining local.
cp "${JOURNEY_HOME}/devnet.toml" devnet.toml
ALICE="addr_test1vq8ac7qqy0vtulyl7wntmsxc6wex80gvcyjy33qffrhm7ss9hjl0y"
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

CLASSPATH="app/target/classes:$(cat app/target/classpath.txt)"
run_cmd "JavaSdkJourney — resolve, sign, submit, and confirm through the generated client" \
  java -cp "${CLASSPATH}" e2e.JavaSdkJourney \
    "http://127.0.0.1:8164" "${ALICE}" "${BOB}"
assert_output_contains '"stage":"confirmed"' "submitted transaction confirmed"
assert_output_contains '"hash":' "confirmed transaction carries a hash"

journey_end
