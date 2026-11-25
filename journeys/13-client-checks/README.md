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
| `fixture-noint/` | Fixture protocol with no integer parameter, and the input fixture for its `transfer`. |
| `journey.sh` | Positive and negative harness tests, run through `run.sh`. |

## Running a release check

The input fixture is a JSON object mapping each operation parameter and each party the profile
does not bind to its value, in the `invoke-args/` format the protocol repositories use. Integers,
booleans, `Bytes` (hex), `Address` (bech32) and `UtxoRef` (`<tx-hash>#<index>`) parameters are
supported. A parameter of another type (record, variant, list, map) fails the record with
"a type the harness cannot bind yet". Protocol, operation, profile, parameter and party names
become identifiers in the consumer source, so a name that is not a plain identifier fails the
record before anything is generated, and so does a `UtxoRef` whose tx part is not hex.

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
to keep the consumer for inspection. The directory of `--out` is created if missing, and a record
that cannot be written fails the check. The recorded `tx3c_version` is that of the tx3c trix
runs: `TX3_TX3C_PATH` when set, otherwise `default/bin/tx3c` under `TX3_HOME` (default
`~/.tx3`). `PYTHON` selects the interpreter for the Python consumer.
The host needs the language's toolchain: `cargo`; Python 3.10 or later; Go 1.24; Node with npm;
Java 21 with Maven 3.9; or Swift 6.1 on macOS.

The CI entry point is `.github/workflows/client-checks.yml`. Dispatch it, or call it from
another workflow, with `release`, `manifest_digest`, `tii_digest`, `git_sha`, `network`,
`profile`, `operation`, `args` (the input fixture as a JSON string) and `channel` (default
`stable`). An empty `network` defaults to `profile`. Callers outside this repository also pass
`harness_ref`. It runs one job per language, Swift on macOS and the rest on Ubuntu. Artifact
names carry a `<key>`, a short hash of the call's inputs, so one caller run can check several
releases or operations. Each job uploads its record as `client-check-record-<key>-<language>`.
The `combined result` job reads only `<language>.json` from each language's own artifact and
folds the records into `result.json`, which it uploads with the records as
`client-check-result-<key>`. It also returns that file as the `result` output and prints a
summary table. The combined result passes only when all six languages have a passing record
whose identity fields are all present and match the release, and which this run attempt wrote.
Re-running only the failed jobs leaves the other languages' records from the earlier attempt,
which combine rejects, so re-run all jobs to get a combined result.
A release run executes code the release generates, so its jobs restore the toolchain cache but
never save it, and they check out without credentials.

Each record carries `scope`, `name`, `version`, `manifest_digest`, `tii_digest`, `git_sha`,
`release_date` (the release's publication time, UTC), `network`, `operation`, `language`, `runtime_package`, `runtime_version`, `tx3c_version`,
`trix_version`, `run_url`, `date` (the run's time, UTC), `result` and `reason`. The combined
result carries the same identity, `release_date` included. The public inventory owns
retention and permalinks for these results.

## Harness tests

Pull requests run `journey.sh` and the six language jobs against the fixture release served by
`fixture_registry.py`. Each language job also checks `transfer` on `fixture-noint/`, an
interface with no integer parameter. A fixture pass proves the harness and is never an
onboarding record. The journey asserts these outcomes:

- **Positive.** Python and TypeScript pass `settle`, Python passes `place_order` (`Bytes` and
  multi-word names) and `transfer` on the no-integer interface. A record carries the release's
  publication date, and its directory is created when missing.
- **Wrong release.** A wrong manifest digest, TII digest or source commit fails.
- **Wrong operation or input.** An operation the interface does not declare fails, and so does a
  `UtxoRef` whose tx part is not hex.
- **Missing pieces.** A missing client, a tx3c without a version, an unreachable runtime index
  and a wrongly typed fixture that fails the typed build all fail. A record that cannot be
  written fails an otherwise passing check.
- **Toolchain identity.** The recorded tx3c is the one under `TX3_HOME` when `TX3_TX3C_PATH`
  is unset, not one on `PATH`.
- **Request check.** The check rejects a recording of another operation, of another value for
  each parameter kind (integer, boolean, `Bytes`, `Address`, `UtxoRef`), of a swapped or missing
  party, of a value tagged as another kind, and of an integer sent for a boolean or the reverse.
- **Hostile names.** Rendering rejects a party or parameter name that is not a plain identifier.
- **Combined result.** Six passing records pass, also with the workflow's identity and an empty
  network. A failed, blank, mismatched, undated or missing Swift record, one from another run
  attempt, and another language's record in Swift's place each leave five successful rows and
  a failed overall result.

The generated TypeScript client sends multi-word parameter names in camelCase and bytes as raw
arrays, so it fails `place_order` at the request check. The journey expects this failure until
the `ts-client` template is fixed. A pass prints `XPASS` as the cue to drop the expectation.

- **Toolchain gate:** `#@ min-tx3c: 0.25.0`, the first tx3c with all six built-in client
  templates. The journey needs `python3` (3.10 or later for the Python consumer), `node` and
  `npm`.
