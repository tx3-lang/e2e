# 08-interface-consume

The consumer half of the interface story with real binaries, no registry: build a publisher
protocol's TII with the real toolchain, prime a consumer project's
`.tx3/tii/<scope>/<name>/<version>/` cache by hand (byte-for-byte what `trix use` writes:
`main.tii`, informative `main.tx3`, `metadata.json` with a matching digest), declare it under
`[interfaces]`, then drive `trix inspect tir` and `trix codegen` through it.

Since tx3-lang/trix#129 hermeticized trix's local suite, the interface plumbing there (digest
gate, alias → cached-TII routing) runs against a fake `tx3c` and a canned TII fixture. What only
this journey validates is the *real* half: `tx3c decode` of a genuinely published-shaped TII, and
real codegen from a cached interface artifact — the interface is consumed, never recompiled.

- **Scope:** compile/lower (no devnet). Offline except the codegen templates download (GitHub,
  anonymous). No secrets, no registry infrastructure.
- **Toolchain gate:** `#@ min-tx3c: 0.23.0` (matches the verified toolchain).
- **Fixtures:** `trix.toml` + `main.tx3` — the publisher protocol (`acme/widget:0.1.0`, one
  `widget_transfer` tx with distinctive party names to assert on).

## What's asserted

1. `trix build` puts the publisher TII at `<scope>/<name>/<version>` in the TII tree.
2. `inspect tir --tx widget::widget_transfer` (alias) and
   `inspect tir --tx acme/widget:0.1.0::widget_transfer` (full ref) both decode the cached TII —
   asserted on the publisher's party/parameter names appearing in the TIR.
3. `trix codegen --plugin ts-client` generates bindings for the interface from its cached TII into
   `.tx3/codegen/ts-client/widget/`, embedding the interface's identity and TIR envelope.

The **full cut** (publish to a real registry, `trix use` pull path, auth) is a separate, heavier
journey tracked in the umbrella plans.
