# 13-client-checks

Release-scoped checks of the six typed clients (Rust, Python, Go, TypeScript, Java and Swift)
against one published interface. Each check starts from an empty consumer and runs these steps:

1. `trix use <scope>/<name>:<version>` pulls the release from the registry. The check compares
   the pinned OCI manifest digest, the cached TII's sha256 and the source commit the release
   recorded with the expected values.
2. `trix codegen --plugin <language>-client` generates the client with the released built-in
   template in `tx3c`.
3. The check builds a minimal consumer against the public runtime package the generated project
   names: crates.io `tx3-sdk`, PyPI `tx3-sdk`, the `github.com/tx3-lang/go-sdk/sdk` Go module, npm
   `tx3-sdk`, Maven Central `land.tx3:tx3-sdk` or the `tx3-lang/swift-sdk` SwiftPM package.
4. The consumer binds the input fixture's parties and arguments through the typed API and
   resolves the operation against a local recording TRP. The check then asserts that the
   request carries the operation's TIR and the fixture's values, bare or in the TRP's tagged
   form.

Every run writes one record, and the record passes only when every step passed. A failed,
skipped or unavailable environment produces a failed record that names the stage, so it stays
visible as incomplete.

## Files

| File | Role |
|---|---|
| `check.sh` | One language record for one release (the entry point). |
| `client_check.py` | Consumer rendering, recording TRP, request check, records, combined result and summary. |
| `consumer-pom.xml` | Maven consumer shell for the Java client. |
| `fixture.sh` | Runs `check.sh` against the controlled fixture release (harness tests only). |
| `fixture_registry.py` | Serves the fixture release over the OCI distribution API. |
| `fixture/` | Fixture protocol and input fixtures for its `settle` and `place_order` operations. |
| `journey.sh` | Positive and negative harness tests, run through `run.sh`. |

## Running a release check

The input fixture is a JSON object mapping each operation parameter and each party the profile
does not bind to its value, in the `invoke-args/` format the protocol repositories use. Integers,
booleans, `Bytes` (hex), `Address` (bech32) and `UtxoRef` (`<tx-hash>#<index>`) parameters are
supported. A parameter of another type (record, variant, list, map) fails the record with
"a type the harness cannot bind yet".

```sh
TRIX=~/.tx3/stable/bin/trix TX3_TX3C_PATH=~/.tx3/stable/bin/tx3c \
  journeys/13-client-checks/check.sh --lang rust \
    --ref open-tx3/minswap-v2:1.0.0 \
    --manifest-digest sha256:<manifest> --tii-digest sha256:<tii> --git-sha <commit> \
    --network preprod --profile preprod --operation place_exact_in_order \
    --args minswap-v2/invoke-args/place_exact_in_order.json \
    --out records/rust.json
```

Use `--registry <url>` to pull from a registry other than the public one. Use `--workdir <dir>`
to keep the consumer for inspection. `PYTHON` selects the interpreter for the Python consumer.
The host needs the language's toolchain: `cargo`; Python 3.10 or later; Go 1.24; Node with npm;
Java 21 with Maven 3.9; or Swift 6.1 on macOS.

The CI entry point is `.github/workflows/client-checks.yml`. Dispatch it, or call it from
another workflow, with `release`, `manifest_digest`, `tii_digest`, `git_sha`, `network`,
`profile`, `operation`, `args` (the input fixture as a JSON string) and `channel` (default
`stable`). Callers outside this repository also pass `harness_ref`. It runs one job per
language, Swift on macOS and the rest on Ubuntu, and each job uploads its record as
`client-check-record-<language>`. The `combined result` job folds the records into
`result.json`, which it uploads with the records as `client-check-result`. It also returns that
file as the `result` output and prints a summary table. The combined result passes only when
all six languages have a passing record whose identity fields are all present and match the
release.

Each record carries `scope`, `name`, `version`, `manifest_digest`, `tii_digest`, `git_sha`,
`network`, `operation`, `language`, `runtime_package`, `runtime_version`, `tx3c_version`,
`trix_version`, `run_url`, `date` (UTC), `result` and `reason`. The public inventory owns
retention and permalinks for these results.

## Harness tests

Pull requests run `journey.sh` and the six language jobs against the fixture release served by
`fixture_registry.py`. A fixture pass proves the harness and is never an onboarding record. The
journey asserts these outcomes:

- **Positive.** Python and TypeScript pass `settle`, and Python passes `place_order`
  (`Bytes` and multi-word names).
- **Wrong release.** A wrong manifest digest, TII digest or source commit fails.
- **Wrong operation.** An operation the interface does not declare fails.
- **Missing pieces.** A missing client, an unreachable runtime index and a wrongly typed
  fixture that fails the typed build all fail.
- **Request check.** The check rejects a recording of another operation, of other argument
  values or of a value tagged as another kind.
- **Combined result.** Six passing records pass. A failed, blank, mismatched or missing Swift
  record leaves five successful rows and a failed overall result.

The generated TypeScript client sends multi-word parameter names in camelCase and bytes as raw
arrays, so it fails `place_order` at the request check. The journey expects this failure until
the `ts-client` template is fixed. A pass prints `XPASS` as the cue to drop the expectation.

- **Toolchain gate:** `#@ min-tx3c: 0.25.0`, the first tx3c with all six built-in client
  templates. The journey needs `python3` (3.10 or later for the Python consumer), `node` and
  `npm`.
