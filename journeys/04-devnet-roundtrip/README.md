# 04-devnet-roundtrip

The integration centerpiece: scaffold the default project and run a real `trix test`. It spins a
local Dolos devnet, restores deterministic cshell wallets, submits the scaffolded transfers, and
asserts the resulting balances — exercising trix + tx3c + dolos + cshell + the resolver together.

- **Scope:** runtime (needs a working devnet). No secrets, no live network beyond the one-time install.
- **Channels:** runs everywhere (no `tx3c` floor); scheduled on both the **stable** and **beta** jobs.

## History: parked on beta until trix 0.26.2

The balance-assertion phase used to hit a known trix bug (the expect path queried the wrong cshell
store, passed the `@bob` placeholder, and parsed a mismatched utxo shape — tx3-lang/trix#123), so
this journey was scheduled on the beta job only and kept **strict** (not `xfail`) so the broken
round-trip stayed a visible red. The fix ships in trix 0.26.2 on both channels; the journey is on
the stable job since then.
