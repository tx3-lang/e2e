import DemoClient
import Foundation
import Tx3SDK

let arguments = CommandLine.arguments
guard arguments.count == 5, let endpoint = URL(string: arguments[1]) else {
  FileHandle.standardError.write(
    Data("usage: SwiftSDKJourney <trp-endpoint> <sender> <receiver> <sender-mnemonic>\n".utf8)
  )
  exit(2)
}

let sender = try Address(arguments[2])
let receiver = try Address(arguments[3])
let signer = try CardanoSigner(mnemonic: arguments[4], address: sender)

let client = DemoClient(
  options: ClientOptions(endpoint: endpoint),
  profile: .local
)
.withSender(.signer(signer))
.withReceiver(.address(receiver))

let resolved = try await client.transfer(TransferParams(quantity: 2_000_000)).resolve()
let submitted = try await resolved.sign().submit()
let status = try await submitted.waitForConfirmed(
  PollConfig(attempts: 30, delay: .seconds(1))
)

print("{\"hash\":\"\(submitted.hash)\",\"status\":\"\(status.stage.rawValue)\"}")
