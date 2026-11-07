import 'dart:async';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/asset_live_store.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/wallet_v2_active_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_send_panel.dart';

class _ChainApi extends VaultAIClient {
  _ChainApi(this.asset, this.address) : super(baseUrl: 'http://test.invalid');

  final String asset;
  final String address;
  final List<String> receiveCalls = [];
  final List<String> balanceCalls = [];
  Map<String, dynamic>? trxOverride;
  Map<String, dynamic>? chainOverride;
  bool failChainBalance = false;
  int broadcastCalls = 0;

  @override
  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
    bool Function()? responseIsCurrent,
  }) async =>
      {
        'walletEngineEnabled': true,
        'sepoliaReceiveEnabled': true,
        'sepoliaSendEnabled': true,
        'mainnetReceiveEnabled': false,
        'mainnetErc20ReceiveEnabled': false,
        'mainnetSendEnabled': false,
        'mainnetSendPaused': false,
        'defaultNetwork': 'ethereum_sepolia',
        'defaultNetworkConfigValid': true,
        'solanaEnabled': asset == 'SOL',
        'solanaReceiveEnabled': asset == 'SOL',
        'solanaBalanceEnabled': asset == 'SOL',
        'solanaSendEnabled': asset == 'SOL',
        'solanaSendPaused': false,
        'tronEnabled': asset == 'USDT_TRC20',
        'tronReceiveEnabled': asset == 'USDT_TRC20',
        'tronBalanceEnabled': asset == 'USDT_TRC20',
        'tronSendEnabled': asset == 'USDT_TRC20',
        'tronSendPaused': false,
        'tronUsdtContractConfigured': asset == 'USDT_TRC20',
        'supportedNetworks': [
          'ethereum_sepolia',
          asset == 'SOL' ? 'solana_mainnet' : 'tron_mainnet',
        ],
        'supportedAssetsByNetwork': {
          'ethereum_sepolia': ['ETH'],
          asset == 'SOL' ? 'solana_mainnet' : 'tron_mainnet': [asset],
        },
      };

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveCalls.add('$network/$asset');
    if (asset != this.asset) return {'wallet_engine': 'no_account'};
    return {
      'wallet_engine': 'receive_ready',
      'publicAddress': address,
      'walletLabel': 'Synthetic wallet',
    };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) async {
    balanceCalls.add('$network/$asset');
    if (asset == this.asset && failChainBalance) {
      throw StateError('Synthetic RPC failure');
    }
    final body = <String, dynamic>{
      'balanceStatus': 'available',
      'asset': asset,
      'network': network,
      'publicAddress': address,
      'availableAmount': '10',
      'availableBaseUnits': '10000000000',
      'unit': asset == 'SOL' ? 'SOL' : 'USDT',
      if (asset == 'SOL') 'lamports': '10000000000',
      if (asset == 'USDT_TRC20') 'baseUnits': '10000000000',
      if (asset == 'TRX') 'trxBalanceSun': '10000000000',
    };
    if (asset == this.asset && chainOverride != null) {
      body.addAll(chainOverride!);
    }
    if (asset == 'TRX' && trxOverride != null) {
      body.addAll(trxOverride!);
    }
    return body;
  }

  @override
  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
    String? draftId,
  }) async {
    broadcastCalls++;
    throw StateError('No transaction may be broadcast in this test');
  }
}

class _RouteWalletV2Client extends WalletV2ActiveClient {
  _RouteWalletV2Client({
    required WalletV2EnvelopeCodec codec,
    required WalletV2Get get,
    required bool Function() accessIsCurrent,
    required this.verified,
  }) : super(
          codec: codec,
          get: get,
          accessIsCurrent: accessIsCurrent,
          post: (_, __) async => throw StateError('No wallet writes'),
        );

  final bool verified;

  @override
  Future<String> readSigningSecret(WalletV2Identity identity) async {
    if (!verified || !accessIsCurrent()) {
      throw StateError('Synthetic backup unavailable');
    }
    return 'synthetic-secret';
  }
}

WalletV2ActiveClient _walletV2(
  String asset,
  String address, {
  bool verified = true,
  bool Function()? accessIsCurrent,
}) {
  final solana = asset == 'SOL';
  return _RouteWalletV2Client(
    codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 7))),
    accessIsCurrent: accessIsCurrent ?? () => true,
    verified: verified,
    get: (path) async {
      expect(path, '/vault/wallet-v2');
      return {
        'wallets': verified
            ? [
                {
                  'wallet_record_id': 'synthetic-wallet-record',
                  'chain': solana ? 'solana' : 'tron',
                  'network': solana ? 'solana_mainnet' : 'tron_mainnet',
                  'asset': asset,
                  'public_address': address,
                  'wallet_label': 'Synthetic wallet',
                  'migration_state': 'v2_verified',
                },
              ]
            : <Object>[],
      };
    },
  );
}

Future<void> _pumpDashboard(
  WidgetTester tester, {
  required _ChainApi api,
  WalletV2ActiveClient? walletV2,
  bool walletV2SendEnabled = true,
  Future<int> Function()? upgradeLegacyWallets,
}) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  AssetLiveStore.instance.clear();
  addTearDown(AssetLiveStore.instance.clear);
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: CryptoWalletEnginePage(
          authToken: 'synthetic-token',
          apiClient: api,
          walletV2: walletV2,
          walletV2SendEnabled: walletV2SendEnabled,
          upgradeLegacyWallets: upgradeLegacyWallets,
          decryptForVault: (_) async => throw StateError('Legacy secret used'),
          isVaultKeyAvailable: () => true,
          encryptForVault: (_) async => throw StateError('Legacy key used'),
          verifyPin: (_) async => true,
          // Production's callback is ETH-only; SOL/TRON must never call it.
          loadFromAddress: (_) async =>
              throw StateError('Ethereum address lookup used'),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('private wallet preparation starts once and reports copies',
      (tester) async {
    final api = _ChainApi('SOL', 'synthetic-SOL-address');
    final pending = Completer<int>();
    var calls = 0;
    await _pumpDashboard(
      tester,
      api: api,
      walletV2: _walletV2('SOL', api.address),
      upgradeLegacyWallets: () {
        calls++;
        return pending.future;
      },
    );
    final button =
        find.byKey(const Key('crypto_wallet_engine_upgrade_wallets_btn'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pump();
    expect(calls, 1);
    expect(tester.widget<OutlinedButton>(button).onPressed, isNull);
    pending.complete(1);
    await tester.pumpAndSettle();
    expect(calls, 1);
    expect(find.text('Verified encrypted copies of 1 older wallet. Your originals remain available.'), findsOneWidget);
  });

  for (final asset in ['SOL', 'USDT_TRC20']) {
    final solana = asset == 'SOL';
    final network = solana ? 'solana_mainnet' : 'tron_mainnet';
    final panelType = solana
        ? CryptoWalletEngineSolanaSendPanel
        : CryptoWalletEngineTronSendPanel;

    testWidgets('$asset dashboard Send opens its own private chain panel', (
      tester,
    ) async {
      final api = _ChainApi(asset, 'synthetic-$asset-address');
      final wallet = _walletV2(asset, api.address);
      await _pumpDashboard(tester, api: api, walletV2: wallet);
      final send = find.byKey(Key('crypto_wallet_engine_card_send_btn_$asset'));
      expect(send, findsOneWidget);
      await tester.ensureVisible(send);
      await tester.tap(send);
      await tester.pumpAndSettle();
      expect(find.byType(panelType), findsOneWidget);
      expect(find.byType(CryptoWalletEngineSendPanel), findsNothing);
      expect(api.receiveCalls, contains('$network/$asset'));
      expect(api.receiveCalls, isNot(contains('$network/ETH')));
      if (solana) {
        final panel = tester.widget<CryptoWalletEngineSolanaSendPanel>(
          find.byType(CryptoWalletEngineSolanaSendPanel),
        );
        expect(await panel.fetchAvailableLamports!(), BigInt.from(10000000000));
        expect(api.balanceCalls.last, 'solana_mainnet/SOL');
      } else {
        final panel = tester.widget<CryptoWalletEngineTronSendPanel>(
          find.byType(CryptoWalletEngineTronSendPanel),
        );
        expect(await panel.fetchAvailableTokenBaseUnits!(),
            BigInt.from(10000000000));
        expect(await panel.fetchTrxBalanceSun!(), BigInt.from(10000000000));
        expect(api.balanceCalls.last, 'tron_mainnet/TRX');
      }
      expect(api.broadcastCalls, 0);
    });

    if (!solana) {
      testWidgets('TRON dashboard fee hook rejects mismatched RPC envelopes', (
        tester,
      ) async {
        final api = _ChainApi(asset, 'synthetic-TRON-address');
        await _pumpDashboard(
          tester,
          api: api,
          walletV2: _walletV2(asset, api.address),
        );
        final send =
            find.byKey(Key('crypto_wallet_engine_card_send_btn_$asset'));
        await tester.ensureVisible(send);
        await tester.tap(send);
        await tester.pumpAndSettle();
        final panel = tester.widget<CryptoWalletEngineTronSendPanel>(
          find.byType(CryptoWalletEngineTronSendPanel),
        );
        for (final override in [
          {'asset': 'USDT_TRC20'},
          {'network': 'ethereum_mainnet'},
          {'publicAddress': 'other-wallet'},
          {'trxBalanceSun': null},
        ]) {
          api.trxOverride = override;
          expect(await panel.fetchTrxBalanceSun!(), isNull);
        }
        expect(api.broadcastCalls, 0);
      });

      testWidgets('TRON asset detail fee hook reads exact fresh TRX sun', (
        tester,
      ) async {
        final api = _ChainApi(asset, 'synthetic-TRON-address');
        final features = CryptoWalletFeatures.fromBackend(
          await api.getCryptoWalletFeatures(authToken: 'synthetic-token'),
        );
        await tester.pumpWidget(MaterialApp(
          home: CryptoWalletEngineAssetDetailPage(
            asset: asset,
            network: network,
            authToken: 'synthetic-token',
            apiClient: api,
            walletV2: _walletV2(asset, api.address),
            walletV2SendEnabled: true,
            verifyPin: (_) async => true,
            loadFromAddress: (_) async => api.address,
            features: features,
          ),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find
            .byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')));
        await tester.pumpAndSettle();
        final panel = tester.widget<CryptoWalletEngineTronSendPanel>(
          find.byType(CryptoWalletEngineTronSendPanel),
        );
        expect(await panel.fetchTrxBalanceSun!(), BigInt.from(10000000000));
        expect(api.balanceCalls.last, 'tron_mainnet/TRX');
        api.trxOverride = {'publicAddress': 'other-wallet'};
        expect(await panel.fetchTrxBalanceSun!(), isNull);
        expect(api.broadcastCalls, 0);
      });
    }

    testWidgets('$asset dashboard Send hides when private send is off', (
      tester,
    ) async {
      final api = _ChainApi(asset, 'synthetic-$asset-address');
      await _pumpDashboard(
        tester,
        api: api,
        walletV2: _walletV2(asset, api.address),
        walletV2SendEnabled: false,
      );
      final send = find.byKey(Key('crypto_wallet_engine_card_send_btn_$asset'));
      if (send.evaluate().isNotEmpty) {
        expect(tester.widget<ElevatedButton>(send).onPressed, isNull);
      }
      expect(api.broadcastCalls, 0);
    });

    testWidgets('$asset dashboard Send rejects unverified V2 backup', (
      tester,
    ) async {
      final api = _ChainApi(asset, 'synthetic-$asset-address');
      await _pumpDashboard(
        tester,
        api: api,
        walletV2: _walletV2(asset, api.address, verified: false),
      );
      final send = find.byKey(Key('crypto_wallet_engine_card_send_btn_$asset'));
      await tester.ensureVisible(send);
      await tester.tap(send);
      await tester.pumpAndSettle();
      expect(find.byType(panelType), findsNothing);
      expect(find.byType(CryptoWalletEngineSendPanel), findsNothing);
      expect(api.broadcastCalls, 0);
    });

    testWidgets('$asset keeps a chain-specific legacy Send route', (
      tester,
    ) async {
      final api = _ChainApi(asset, 'synthetic-$asset-address');
      await _pumpDashboard(
        tester,
        api: api,
        walletV2SendEnabled: false,
      );
      final send = find.byKey(Key('crypto_wallet_engine_card_send_btn_$asset'));
      expect(send, findsOneWidget);
      await tester.ensureVisible(send);
      await tester.tap(send);
      await tester.pumpAndSettle();
      expect(find.byType(panelType), findsOneWidget);
      expect(find.byType(CryptoWalletEngineSendPanel), findsNothing);
      expect(api.receiveCalls, isNot(contains('$network/ETH')));
      expect(api.broadcastCalls, 0);
    });

    testWidgets('$asset asset detail hides unmigrated address and Copy', (
      tester,
    ) async {
      final api = _ChainApi(asset, 'legacy-$asset-address');
      await tester.pumpWidget(
        MaterialApp(
          home: CryptoWalletEngineAssetDetailPage(
            asset: asset,
            network: network,
            authToken: 'synthetic-token',
            apiClient: api,
            walletV2: _walletV2(asset, api.address, verified: false),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(
          const Key('crypto_wallet_engine_asset_detail_address_unverified'),
        ),
        findsOneWidget,
      );
      expect(find.textContaining(api.address), findsNothing);
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_address_text')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_copy_btn')),
        findsNothing,
      );
      expect(api.broadcastCalls, 0);
    });

    testWidgets('$asset asset detail shows a verified V2 address', (
      tester,
    ) async {
      final api = _ChainApi(asset, 'verified-$asset-address');
      await tester.pumpWidget(
        MaterialApp(
          home: CryptoWalletEngineAssetDetailPage(
            asset: asset,
            network: network,
            authToken: 'synthetic-token',
            apiClient: api,
            walletV2: _walletV2(asset, api.address),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text(api.address), findsOneWidget);
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_address_text')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_copy_btn')),
        findsOneWidget,
      );
      expect(api.broadcastCalls, 0);
    });

    testWidgets('$asset asset detail send rechecks exact live balance', (
      tester,
    ) async {
      final api = _ChainApi(asset, 'synthetic-$asset-address');
      var accessCurrent = true;
      final features = CryptoWalletFeatures.fromBackend(
        await api.getCryptoWalletFeatures(authToken: 'synthetic-token'),
      );
      await tester.pumpWidget(MaterialApp(
        home: CryptoWalletEngineAssetDetailPage(
          asset: asset,
          network: network,
          authToken: 'synthetic-token',
          apiClient: api,
          walletV2: _walletV2(
            asset,
            api.address,
            accessIsCurrent: () => accessCurrent,
          ),
          walletV2SendEnabled: true,
          verifyPin: (_) async => true,
          loadFromAddress: (_) async => api.address,
          features: features,
        ),
      ));
      await tester.pumpAndSettle();
      await tester.tap(
          find.byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')));
      await tester.pumpAndSettle();
      final Future<BigInt?> Function() freshBalance = solana
          ? tester
              .widget<CryptoWalletEngineSolanaSendPanel>(
                find.byType(CryptoWalletEngineSolanaSendPanel),
              )
              .fetchAvailableLamports!
          : tester
              .widget<CryptoWalletEngineTronSendPanel>(
                find.byType(CryptoWalletEngineTronSendPanel),
              )
              .fetchAvailableTokenBaseUnits!;
      expect(await freshBalance(), BigInt.from(10000000000));
      final rawField = solana ? 'lamports' : 'baseUnits';
      api.chainOverride = {rawField: '1'};
      expect(await freshBalance(), BigInt.one,
          reason: 'a newer lower balance must replace the displayed value');
      api.failChainBalance = true;
      expect(await freshBalance(), isNull,
          reason: 'a failed fresh read must not reuse a cached balance');
      api.failChainBalance = false;
      accessCurrent = false;
      expect(await freshBalance(), isNull,
          reason: 'vault access loss must block the final balance gate');
      accessCurrent = true;
      for (final override in [
        {'asset': 'ETH'},
        {'network': 'ethereum_mainnet'},
        {'publicAddress': 'other-wallet'},
        {'balanceStatus': 'unavailable'},
        {rawField: null},
      ]) {
        api.chainOverride = override;
        expect(await freshBalance(), isNull);
      }
      expect(api.broadcastCalls, 0);
    });
  }
}
