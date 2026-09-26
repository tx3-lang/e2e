# 07-codegen-consume

The `trix codegen` → generated SDK path, end to end with real binaries: generate the
`ts-client` bindings (real `tx3c codegen` rendering the built-in `ts-client` template that ships
inside tx3c), compile them inside a host package, then resolve a transfer *through the generated
client* against a local devnet TRP.

Since tx3-lang/trix#129 hermeticized trix's local suite, its contract tests stub `tx3c` and
assert only argv + the per-protocol `.tx3/codegen/<plugin>/<name>/` layout, and tx3's own CI
compiles each built-in template's output against the published SDK. This journey is the only CI
that runs the whole path with real binaries: `trix codegen` → `tx3c`'s built-in template → a
compiled client that drives the TRP lifecycle.

- **Scope:** runtime (phase 4 needs a working devnet). Phases 1–3 are offline apart from one
  anonymous download: npm packages (registry). The template ships inside tx3c. No secrets.
- **Toolchain gate:** `#@ min-tx3c: 0.24.0`, the first tx3c with built-in templates, which trix
  0.27.0 and later require. Additionally requires `node`/`npm` on PATH — the journey *skips* cleanly when
  they're missing (all GitHub-hosted runners ship Node).
- **Fixtures:** `package.json` + `tsconfig.json` + `resolve.ts` — the host application shell the
  generated module is dropped into. The fixture pins the `tx3-sdk` range the `ts-client` template
  targets (`^0.15.0`); keep it in step with `tx3/bin/tx3c/templates/ts-client/package.json.hbs`. The
  template deliberately emits a bare `protocol.ts` (the
  standalone-package files are gated behind `options.standalone`), so a host package is the
  representative consumption mode.

## Phases

1. `trix init` + `trix codegen --plugin ts-client` — asserts the seeded `[[codegen]]` entry, the
   per-protocol output layout (no flat file), and the generated content (protocol identity,
   embedded TIR envelope, typed `Client` wrapper).
2. `npm install` + `tsc` — the generated client type-checks and compiles against the released
   `tx3-sdk` it imports.
3. `trix devnet --background` + `node resolve.js` — the compiled client binds parties
   (deterministic devnet identities), builds the scaffolded `transfer`, and resolves it over TRP
   to an unsigned tx (asserted on `cbor` + `hash`). Resolve-only: `trix invoke` semantics minus
   signing, same as `05-invoke`.
