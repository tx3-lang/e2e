// Host-app consumer of the generated bindings: bind the parties, build the
// scaffolded `transfer`, and resolve it through a live TRP endpoint. Compiling
// this file type-checks the generated client's surface; running it exercises
// the full generated-SDK resolve path.
import { Party } from "tx3-sdk";
import { Client, PROTOCOL_NAME, type TransferParams } from "./protocol.js";

const [endpoint, sender, receiver] = process.argv.slice(2);
if (!endpoint || !sender || !receiver) {
    console.error("usage: resolve.js <trp-endpoint> <sender-addr> <receiver-addr>");
    process.exit(2);
}

const params: TransferParams = { quantity: 2_000_000 };

const client = new Client({ endpoint }, "local")
    .withSender(Party.address(sender))
    .withReceiver(Party.address(receiver));

const resolved = await client.transfer(params).resolve();
console.log(JSON.stringify({ protocol: PROTOCOL_NAME, hash: resolved.hash, cbor: resolved.txHex }));
