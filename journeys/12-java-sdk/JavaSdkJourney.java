package e2e;

import java.math.BigInteger;
import java.net.URI;
import land.tx3.generated.demo.DemoClient;
import land.tx3.sdk.Address;
import land.tx3.sdk.CardanoSigner;
import land.tx3.sdk.ClientOptions;
import land.tx3.sdk.Party;
import land.tx3.sdk.PollConfig;

/** Host application for the generated Java client journey. */
public final class JavaSdkJourney {
  // Public test vector from the Java SDK; funded only by this disposable devnet.
  private static final String ALICE_MNEMONIC =
      "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon "
          + "abandon about";

  private JavaSdkJourney() {}

  /** Runs one generated-client transfer through confirmation. */
  public static void main(String[] args) {
    if (args.length != 3) {
      throw new IllegalArgumentException(
          "usage: JavaSdkJourney <trp-endpoint> <sender-address> <receiver-address>");
    }

    var sender = new Address(args[1]);
    var signer = new CardanoSigner(ALICE_MNEMONIC, sender);
    var client =
        new DemoClient(ClientOptions.forEndpoint(URI.create(args[0])), DemoClient.Profile.LOCAL)
            .withSender(Party.signer(signer))
            .withReceiver(Party.address(new Address(args[2])));

    var resolved =
        client
            .transfer(new DemoClient.TransferParams(BigInteger.valueOf(2_000_000)))
            .resolve()
            .join();
    var submitted = resolved.sign().submit().join();
    var confirmed = submitted.waitForConfirmed(PollConfig.defaults()).join();

    System.out.printf(
        "{\"hash\":\"%s\",\"stage\":\"%s\",\"confirmations\":%d}%n",
        submitted.hash(), confirmed.stage().wireValue(), confirmed.confirmations());
  }
}
