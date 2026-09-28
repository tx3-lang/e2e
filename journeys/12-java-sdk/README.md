# 12-java-sdk

The Java generated-client path with real released components: seed trix's
`java-client` plugin, render tx3c's built-in template, compile the generated
Maven project against `land.tx3:tx3-sdk:0.15.0`, and consume that installed
artifact from a separate Java 21 host project. The host then resolves, signs,
submits, and confirms a transfer through the generated `DemoClient` against a
disposable local devnet.

- **Scope:** runtime. The generated project and consumer use an isolated Maven
  repository; normal released-channel validation downloads dependencies from
  Maven Central without credentials. No preprod endpoint or secret is used.
- **Toolchain gate:** `#@ min-tx3c: 0.25.0`, the first tx3c release with the
  built-in `java-client` template. The selected trix channel must also include
  the built-in Java plugin registration that invokes `--template java-client`.
- **Host baseline:** CI runs only on `ubuntu-24.04` with Temurin 21 and Maven
  3.9. A local run without Java/Maven skips; CI treats either missing tool as a
  failure so absent prerequisites cannot count as coverage.
- **Identity:** the checked-in phrase and address are the Java SDK's public,
  checksum-verified CIP-1852 test vector. The address is funded only by this
  disposable devnet; the phrase is never a live credential. The receiver is
  trix's deterministic `bob` identity.

For reviewed pre-publication testing, install `0.15.0-SNAPSHOT` into an isolated
Maven repository, set `TX3_JAVA_M2_REPO` to that directory, and set
`TX3_JAVA_SDK_VERSION=0.15.0-SNAPSHOT`. The released-channel acceptance path
leaves both overrides unset and resolves `0.15.0` from Maven Central.
