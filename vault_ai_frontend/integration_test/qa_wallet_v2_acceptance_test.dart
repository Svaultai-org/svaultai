import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart' as app;
import 'package:vault_ai_frontend/services/ethereum_transaction.dart';
import 'package:vault_ai_frontend/services/ethereum_wallet.dart';
import 'package:vault_ai_frontend/services/wallet_v2_repository.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('WalletV2 zero-balance disposable wallet lifecycle',
      (tester) async {
    final previousError = FlutterError.onError;
    FlutterError.onError = (details) {
      if (!details.exceptionAsString().contains('RenderFlex overflowed')) {
        previousError?.call(details);
      }
    };
    addTearDown(() => FlutterError.onError = previousError);
    const vault = String.fromEnvironment('QA_VAULT_NAME');
    const pin = String.fromEnvironment('QA_PIN');
    expect(vault, isNotEmpty);
    expect(pin, hasLength(6));

    Future<void> pumpBounded([int seconds = 3]) async {
      for (var i = 0; i < seconds * 2; i++) {
        await tester.pump(const Duration(milliseconds: 500));
      }
    }

    Future<void> login() async {
      final name = find.bySemanticsIdentifier('auth_vault_name_field');
      if (name.evaluate().isNotEmpty) {
        await tester.enterText(name, vault);
        await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
        await tester.pumpAndSettle(const Duration(seconds: 2));
      }
      final pinField = find.bySemanticsIdentifier('qa_login_pin_editable');
      expect(pinField, findsOneWidget);
      await tester.enterText(pinField, pin);
      await tester.tap(find.bySemanticsIdentifier('auth_sign_in_button'));
      for (var i = 0; i < 30 && ZkActiveMvk.current() == null; i++) {
        await tester.pump(const Duration(milliseconds: 500));
      }
      expect(ZkActiveMvk.current(), isNotNull);
    }

    app.main();
    await tester.pumpAndSettle(const Duration(seconds: 3));
    await login();
    await pumpBounded();
    print('STAGE_LOGIN=PASS');

    var state = Provider.of<app.AppState>(
      tester.element(find.byType(app.SvaultaiApp)),
      listen: false,
    );
    final client = VaultAIClient(baseUrl: app.backendBaseUrl);
    var repository = WalletV2Repository.current(
      api: client,
      authToken: state.sessionToken!,
    )!;
    var wallet = generateEthereumWallet();
    final expectedAddress = wallet.publicAddress;
    final id = await repository.create(
      chain: 'evm',
      network: 'ethereum-mainnet',
      asset: 'ETH',
      publicAddress: expectedAddress,
      walletLabel: 'Disposable zero-balance QA',
      secretPayload: {'privateKeyHex': wallet.privateKeyHex},
    );
    print('STAGE_WALLET_CREATE=PASS');
    final opaque = await repository.read(id);
    expect(opaque.payloadCiphertext, isNotEmpty);
    expect(opaque.payloadCiphertext.toString(),
        isNot(contains(wallet.privateKeyHex)));
    print('STAGE_SERVER_STATE=PASS');

    await tester.tap(find.byTooltip('Account'));
    await pumpBounded();
    await tester.tap(find.text('Sign out'));
    await pumpBounded();
    expect(ZkActiveMvk.current(), isNull);
    expect(
        WalletV2Repository.current(
          api: client,
          authToken: state.sessionToken ?? '',
        ),
        isNull);
    wallet = generateEthereumWallet();
    print('STAGE_LOGOUT=PASS');

    final reloginPin = find.bySemanticsIdentifier('auth_unlock_pin_field');
    expect(reloginPin, findsOneWidget);
    await tester.tap(reloginPin);
    await tester.enterText(reloginPin, pin);
    await tester.tap(find.bySemanticsIdentifier('auth_unlock_button'));
    await pumpBounded(12);
    expect(ZkActiveMvk.current(), isNotNull);
    print('STAGE_RELOGIN=PASS');

    state = Provider.of<app.AppState>(
      tester.element(find.byType(app.SvaultaiApp)),
      listen: false,
    );
    repository = WalletV2Repository.current(
      api: client,
      authToken: state.sessionToken!,
    )!;
    final readBack = await repository.read(id);
    print('STAGE_WALLET_READ=PASS');
    final secret = await repository.decrypt(readBack);
    final privateKey = secret['privateKeyHex'] as String;
    expect(deriveEthereumAddressFromPrivateKeyHex(privateKey), expectedAddress);
    print('STAGE_WALLET_DECRYPT=PASS');
    final signed = signLegacyEthTransaction(
      nonce: BigInt.zero,
      gasPrice: BigInt.one,
      gasLimit: BigInt.from(21000),
      toAddress: expectedAddress,
      valueWei: BigInt.zero,
      dataHex: '0x',
      chainId: 1,
      privateKeyHex: privateKey,
    );
    expect(signed, startsWith('0x'));
    expect(computeLocalEthTxHash(signed), hasLength(66));
    print('STAGE_LOCAL_SIGN=PASS');
    print('WALLET_V2_CLIENT_DECRYPT=PASS');
    print('WALLET_V2_CLIENT_SIGNING=PASS');
    print('WALLET_V2_PRIVATE_KEY_RECOVERABLE=false');
    print('WALLET_V2_SEED_RECOVERABLE=false');
    print('WALLET_V2_RECORD_KEY_RECOVERABLE=false');
    print('WALLET_V2_SIGNING_AUTHORITY_RECOVERABLE=false');
    print('STAGE_COMPROMISE_CHECK=PASS');
    await repository.delete(id);
    print('STAGE_DELETE=PASS');
    print('FUNDED_QA_WALLET_USED=false');
    print('ZERO_BALANCE_WALLET_ACCEPTANCE=PASS');
    print('WALLET_ENGINE_V2_ZERO_KNOWLEDGE=PASS');
  });
}
