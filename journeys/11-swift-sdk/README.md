# 11-swift-sdk

The generated Swift client developer journey against the real assembled toolchain: `trix`
scaffolds a project, its built-in `swift-client` plugin delegates to the real `tx3c` template,
SwiftPM compiles that generated package inside a clean host consumer, and the executable drives
resolve → sign → submit → confirmed against the disposable local Dolos devnet.

- **Scope:** native macOS runtime journey. It requires Swift 6.1/Xcode 16.4, Git, and the normal
  `trix`, `tx3c`, `dolos`, and `cshell` toolchain. No live-network secret is used.
- **Toolchain gate:** `#@ min-tx3c: 0.25.0`, the first tx3c release containing the built-in
  `swift-client` template. Older tx3c releases skip before checking the Swift prerequisite. The
  journey also fails explicitly
  if trix is older than `0.28.0`, the first release registering `swift-client`. Stable and beta
  manifests must supply tx3c `^0.25.0` and trix `^0.28.0` for CI to count as coverage.
- **Package pin:** the host package requires the public Swift SDK at exactly `0.15.0`
  (published annotated tag `v0.15.0`). The generated
  package's `from: 0.15.0` constraint therefore resolves to that exact version as well.
- **Fixtures:** `Package.swift` and `main.swift` model the host application. Generated files stay
  under `.tx3/codegen/swift-client/demo/` and are never checked in.

For pre-publication validation only, `TX3_SWIFT_SDK_PATH=/path/to/reviewed/swift-sdk` makes the
journey clone that checkout into its disposable workdir, tag the clone as `0.15.0`, and configure a
SwiftPM mirror. This exercises the same exact-version package graph without mutating the source
checkout. Released-channel CI intentionally leaves the override unset and resolves the public tag.

## Phases

1. `trix init -y` and `trix codegen --plugin swift-client` assert built-in rendering, per-protocol
   layout, the embedded TIR envelope, party setters, and the typed transaction method.
2. `swift build --configuration debug` compiles both the generated `DemoClient` library and an
   independent executable consumer against the exact SDK package requirement.
3. `devnet.toml` funds the canonical CIP-1852 signer vector from
   `sdk-spec/test-vectors/crypto/signer-vectors.json`; the consumer binds that vector's mnemonic
   and address with trix's deterministic `bob` receiver. trix's `alice` uses an underived Icarus
   root key and cannot be used with the SDK's CIP-1852 signer. The consumer resolves, signs, and
   submits a transfer, then waits for a confirmed status from the local devnet. The exit trap
   reaps only this journey's Dolos config path, including when devnet startup or the consumer fails.

## Verification

```sh
TX3_TRIX_PATH=/path/to/trix \
TX3_TX3C_PATH=/path/to/tx3c \
TX3_DOLOS_PATH=/path/to/dolos \
TX3_CSHELL_PATH=/path/to/cshell \
  ./run.sh --local --journey 11-swift-sdk

./run.sh --channel stable --journey 11-swift-sdk
./run.sh --channel beta --journey 11-swift-sdk
```

Both CI workflows select this journey on native `macos-15` with Xcode `16.4`. A missing Swift
compiler or unresolved SDK package fails the job. Failed runs preserve the consumer, generated
package, devnet files, and command logs through the harness's artifact upload.
