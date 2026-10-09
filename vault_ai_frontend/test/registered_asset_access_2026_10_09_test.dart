import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';
import 'package:vault_ai_frontend/services/asset_live_store.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';

import 'asset_catalog_2026_10_09_test.dart' show catalogFixture;

const _network = 'ethereum_mainnet';
const _token = 'synthetic-old-session';
const _address = '0x1111111111111111111111111111111111111111';
const _destination = '0x2222222222222222222222222222222222222222';

final _features = CryptoWalletFeatures.fromBackend({
  'walletEngineEnabled': true,
  'mainnetReceiveEnabled': true,
  'mainnetErc20ReceiveEnabled': true,
  'mainnetSendEnabled': true,
  'mainnetSendPaused': false,
  'defaultNetwork': _network,
  'defaultNetworkConfigValid': true,
});

typedef _Call = Future<Map<String, dynamic>> Function(VaultAIClient);
final Map<String, _Call> _walletCalls = {
  'receive': (c) => c.getCryptoWalletReceiveNetwork(
      network: _network, asset: kPaxgAssetId, authToken: _token),
  'create': (c) => c.createCryptoWalletAccountNetwork(
      network: _network,
      asset: kPaxgAssetId,
      authToken: _token,
      walletLabel: 'Synthetic',
      publicAddress: _address,
      encryptedWalletSecret: 'synthetic-ciphertext'),
  'balance': (c) => c.getCryptoWalletBalanceNetwork(
      network: _network,
      asset: kPaxgAssetId,
      authToken: _token,
      address: _address),
  'activity': (c) => c.listCryptoWalletTransactionsNetwork(
      network: _network, asset: kPaxgAssetId, authToken: _token),
  'draft': (c) => c.createCryptoWalletSendDraftNetwork(
      network: _network,
      asset: kPaxgAssetId,
      authToken: _token,
      fromAddress: _address,
      destinationAddress: _destination,
      amountEth: '1'),
  'broadcast': (c) => c.broadcastCryptoWalletSignedTransactionNetwork(
      network: _network,
      asset: kPaxgAssetId,
      authToken: _token,
      signedTransaction: 'synthetic-not-a-real-transaction'),
  'key': (c) => c.getCryptoWalletEncryptedSecretNetwork(
      network: _network, asset: 'ETH', authToken: _token),
  'transaction': (c) => c.getCryptoWalletTransactionStatusNetwork(
      network: _network,
      asset: kPaxgAssetId,
      authToken: _token,
      txHash: 'synthetic-transaction'),
  'history': (c) => c.getCryptoWalletOutgoingHistoryNetwork(
      network: _network, authToken: _token),
  'fee': (c) => c.postCryptoWalletSendFeeEstimateNetwork(
      network: _network,
      asset: kPaxgAssetId,
      authToken: _token,
      fromAddress: _address,
      destinationAddress: _destination),
  'expiry': (c) => c.getCryptoWalletDraftExpiryNetwork(
      network: _network, authToken: _token, draftId: 'synthetic-draft'),
};

Map<String, dynamic> _balance() => {
      'balanceStatus': 'available',
      'asset': kPaxgAssetId,
      'networkId': _network,
      'chainId': 1,
      'decimals': 18,
      'unit': 'PAXG',
      'availableAmount': '1',
      'baseUnits': '1000000000000000000',
      'publicAddress': _address,
      'tokenContract': kPaxgContractAddress,
    };

Widget _page(ValueNotifier<bool> access, VaultAIClient client,
        {String asset = kPaxgAssetId, bool registered = true}) =>
    MaterialApp(
      home: CryptoWalletEngineAssetDetailPage(
        asset: asset,
        registeredAsset: registered
            ? VaultAssetCatalog.fromJson(catalogFixture()).digitalGold
            : null,
        network: _network,
        features: _features,
        authToken: _token,
        apiClient: client,
        accessChanges: access,
        isVaultKeyAvailable: () => access.value,
        encryptForVault: (_) async => 'synthetic-ciphertext',
        decryptForVault: (_) async => 'synthetic-not-a-real-key',
        verifyPin: (_) async => true,
        loadFromAddress: (_) async => _address,
      ),
    );

void main() {
  setUp(() {
    SessionTermination.instance.reset();
    AssetLiveStore.instance.resetForTest();
  });
  tearDown(() {
    SessionTermination.instance.reset();
    SessionTermination.instance.setHandler((_) async {});
    AssetLiveStore.instance.resetForTest();
  });

  for (final entry in _walletCalls.entries) {
    test('${entry.key} does not dispatch after registered lease revoked',
        () async {
      var requests = 0;
      final client = VaultAIClient(
          baseUrl: 'https://synthetic.invalid',
          walletResponseIsCurrent: () => false);
      await http.runWithClient(() async {
        await expectLater(entry.value(client), throwsStateError);
      },
          () => MockClient((_) async {
                requests++;
                return http.Response('{}', 200);
              }));
      expect(requests, 0);
    });

    for (final status in [200, 401, 403]) {
      test('${entry.key} drops late $status without terminating new session',
          () async {
        var current = true;
        var terminations = 0;
        SessionTermination.instance.setHandler((_) async => terminations++);
        final started = Completer<void>();
        final response = Completer<http.Response>();
        final client = VaultAIClient(
            baseUrl: 'https://synthetic.invalid',
            walletResponseIsCurrent: () => current);
        await http.runWithClient(() async {
          final rejected = expectLater(entry.value(client), throwsStateError);
          await started.future;
          current = false;
          response.complete(http.Response(
              jsonEncode({
                'detail': {
                  'code':
                      status == 401 ? 'session_superseded' : 'device_revoked'
                },
                'encryptedWalletSecret': 'old-synthetic-ciphertext',
              }),
              status));
          await rejected;
          expect(terminations, 0);
          expect(SessionTermination.instance.isTerminated, isFalse);
        },
            () => MockClient((request) async {
                  expect(request.url.host, 'synthetic.invalid');
                  started.complete();
                  return response.future;
                }));
      });
    }
  }

  test('ordinary unscoped client retains accepted network response', () async {
    const client = VaultAIClient(baseUrl: 'https://synthetic.invalid');
    await http.runWithClient(() async {
      expect(await _walletCalls['receive']!(client),
          {'wallet_engine': 'no_account'});
    },
        () => MockClient(
            (_) async => http.Response('{"wallet_engine":"no_account"}', 200)));
  });

  test('shared loader checks lease before sending its follow-up balance',
      () async {
    var current = true;
    var requests = 0;
    final started = Completer<void>();
    final response = Completer<http.Response>();
    const client = VaultAIClient(baseUrl: 'https://synthetic.invalid');
    await http.runWithClient(() async {
      final result = loadAssetWalletState(
        apiClient: client,
        authToken: _token,
        network: _network,
        asset: kPaxgAssetId,
        responseIsCurrent: () => current,
      );
      await started.future;
      current = false;
      response.complete(http.Response(
          jsonEncode({
            'wallet_engine': 'receive_ready',
            'publicAddress': _address,
          }),
          200));
      expect((await result).publicAddress, isNull);
      expect(requests, 1);
    },
        () => MockClient((_) async {
              requests++;
              started.complete();
              return response.future;
            }));
  });

  testWidgets(
      'lock during receive stops follow-up balance and stale global apply',
      (tester) async {
    final access = ValueNotifier(true);
    addTearDown(access.dispose);
    final response = Completer<http.Response>();
    var balances = 0;
    final client = VaultAIClient(
        baseUrl: 'https://synthetic.invalid',
        walletResponseIsCurrent: () => access.value);
    await http.runWithClient(() async {
      await tester.pumpWidget(_page(access, client));
      await tester.pump();
      access.value = false;
      await tester.pump();
      expect(find.byKey(const Key('registered_asset_access_locked')),
          findsOneWidget);
      response.complete(http.Response(
          jsonEncode({
            'wallet_engine': 'receive_ready',
            'publicAddress': _address,
          }),
          200));
      await tester.pumpAndSettle();
      expect(balances, 0);
      expect(AssetLiveStore.instance.getState(kPaxgAssetId)?.publicAddress,
          isNull);
      access.value = true;
      await tester.pump();
      expect(find.byKey(const Key('registered_asset_access_locked')),
          findsOneWidget);
      expect(tester.takeException(), isNull);
    },
        () => MockClient((request) async {
              if (request.url.path.endsWith('/receive')) return response.future;
              balances++;
              return http.Response(jsonEncode(_balance()), 200);
            }));
  });

  testWidgets('lock during balance never applies old address/balance globally',
      (tester) async {
    final access = ValueNotifier(true);
    addTearDown(access.dispose);
    final response = Completer<http.Response>();
    var balances = 0;
    final client = VaultAIClient(
        baseUrl: 'https://synthetic.invalid',
        walletResponseIsCurrent: () => access.value);
    await http.runWithClient(() async {
      await tester.pumpWidget(_page(access, client));
      await tester.pump();
      await tester.pump();
      expect(balances, 1);
      access.value = false;
      await tester.pump();
      response.complete(http.Response(jsonEncode(_balance()), 200));
      await tester.pumpAndSettle();
      expect(AssetLiveStore.instance.getState(kPaxgAssetId)?.publicAddress,
          isNull);
      expect(find.text(_address), findsNothing);
      expect(find.byKey(const Key('registered_asset_access_locked')),
          findsOneWidget);
      expect(tester.takeException(), isNull);
    },
        () => MockClient((request) async {
              if (request.url.path.endsWith('/receive')) {
                return http.Response(
                    jsonEncode({
                      'wallet_engine': 'receive_ready',
                      'publicAddress': _address
                    }),
                    200);
              }
              balances++;
              return response.future;
            }));
  });

  testWidgets('open registered receive sheet blanks on vault lock',
      (tester) async {
    final access = ValueNotifier(true);
    addTearDown(access.dispose);
    final client = VaultAIClient(
        baseUrl: 'https://synthetic.invalid',
        walletResponseIsCurrent: () => access.value);
    await http.runWithClient(() async {
      await tester.pumpWidget(_page(access, client));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find
          .byKey(const Key('crypto_wallet_engine_asset_detail_receive_btn')));
      await tester.tap(find
          .byKey(const Key('crypto_wallet_engine_asset_detail_receive_btn')));
      await tester.pumpAndSettle();
      access.value = false;
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('registered_asset_sheet_locked')),
          findsOneWidget);
      expect(find.text(_address), findsNothing);
      expect(tester.takeException(), isNull);
    },
        () => MockClient((request) async => http.Response(
            jsonEncode(request.url.path.endsWith('/receive')
                ? {'wallet_engine': 'receive_ready', 'publicAddress': _address}
                : request.url.path.endsWith('/transactions')
                    ? {'transactionsStatus': 'available', 'transactions': []}
                    : request.url.path.contains('/ETH/')
                        ? {'balanceStatus': 'available', 'weiAmount': '1'}
                        : _balance()),
            200)));
  });

  testWidgets('ordinary ETH detail does not opt into registered lock behavior',
      (tester) async {
    final access = ValueNotifier(false);
    addTearDown(access.dispose);
    const client = VaultAIClient(baseUrl: 'https://synthetic.invalid');
    await http.runWithClient(() async {
      await tester
          .pumpWidget(_page(access, client, asset: 'ETH', registered: false));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('registered_asset_access_locked')),
          findsNothing);
      expect(find.byKey(const Key('crypto_wallet_engine_asset_detail_page')),
          findsOneWidget);
      expect(tester.takeException(), isNull);
    },
        () => MockClient(
            (_) async => http.Response('{"wallet_engine":"no_account"}', 200)));
  });
}
