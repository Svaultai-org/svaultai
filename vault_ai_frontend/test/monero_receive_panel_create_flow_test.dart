


import 'dart:typed_data';
import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_crypto_primitives.dart';
import 'package:vault_ai_frontend/services/monero_wallet.dart';
import 'package:vault_ai_frontend/services/wallet_v2_active_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


class _MoneroSpyClient extends VaultAIClient {
  Map<String, dynamic> nextReceiveResponse = {'wallet_engine': 'no_account'};
  final List<Map<String, dynamic>> createCalls = [];

  _MoneroSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
    bool Function()? responseIsCurrent,
  }) async => {
    'status': 'ok',
    'schema': 'crypto_wallet_features_v1',
    'walletEngineEnabled': true,
    'sepoliaReceiveEnabled': true,
    'sepoliaSendEnabled': false,
    'defaultNetwork': 'ethereum_sepolia',
    'defaultNetworkConfigValid': true,
    'xmrEnabled': true,
    'xmrReceiveEnabled': true,
    'xmrSendEnabled': false,
    'supportedNetworks': const ['ethereum_sepolia', 'monero_mainnet'],
    'supportedAssetsByNetwork': const {'monero_mainnet': ['XMR']},
  };

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    return nextReceiveResponse;
  }

  @override
  Future<Map<String, dynamic>> createCryptoWalletAccountNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String walletLabel,
    required String publicAddress,
    required String encryptedWalletSecret,
    int? restoreHeight,
    String? scannerMode,
  }) async {
    createCalls.add({
      'network':               network,
      'asset':                 asset,
      'walletLabel':           walletLabel,
      'publicAddress':         publicAddress,
      'encryptedWalletSecret': encryptedWalletSecret,
      'restoreHeight':         restoreHeight,
      'scannerMode':           scannerMode,
    });
    nextReceiveResponse = {
      'wallet_engine':  'receive_ready',
      'publicAddress':  publicAddress,
      'walletLabel':    walletLabel,
      'restoreHeight':  restoreHeight,
    };
    return {'wallet_engine': 'account_created'};
  }
}


CryptoWalletFeatures _features({bool xmrOn = true}) {
  return CryptoWalletFeatures.fromBackend({
    'walletEngineEnabled':       true,
    'sepoliaReceiveEnabled':     true,
    'sepoliaSendEnabled':        true,
    'mainnetReceiveEnabled':     false,
    'mainnetErc20ReceiveEnabled': false,
    'mainnetSendEnabled':        false,
    'mainnetSendPaused':         false,
    'defaultNetwork':            'ethereum_sepolia',
    'defaultNetworkConfigValid': true,
    'solanaEnabled':             false,
    'solanaReceiveEnabled':      false,
    'solanaBalanceEnabled':      false,
    'solanaSendEnabled':         false,
    'solanaSendPaused':          false,
    'solanaActivityConnected':   false,
    'solanaStatusReady':         false,
    'solanaFeeReady':            false,
    'tronEnabled':               false,
    'tronReceiveEnabled':        false,
    'tronBalanceEnabled':        false,
    'tronSendEnabled':           false,
    'tronSendPaused':            false,
    'tronActivityConnected':     false,
    'tronUsdtContractConfigured': false,
    'xmrEnabled':                xmrOn,
    'xmrReceiveEnabled':         xmrOn,
    'xmrBalanceEnabled':         false,
    'xmrSendEnabled':            false,
    'xmrActivityConnected':      false,
    'xmrScannerMode':            'none',
    'supportedNetworks':         const ['ethereum_sepolia'],
    'supportedAssetsByNetwork':  const {},
  });
}


Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));


Future<void> _pumpPanel(
  WidgetTester tester, {
  required _MoneroSpyClient client,
  required MoneroWalletAdapter adapter,
  WalletV2ActiveClient? walletV2,
  Future<String> Function(String)? encryptForVault,
  bool Function()? isVaultKeyAvailable,
}) async {
  await tester.pumpWidget(_wrap(
    CryptoWalletEngineMoneroReceivePanel(
      authToken: 'tok',
      client: client,
      features: _features(),
      walletAdapter: adapter,
      walletV2: walletV2,
      encryptForVault:
          encryptForVault ?? ((p) async => 'vault-cipher:${p.length}'),
      isVaultKeyAvailable: isVaultKeyAvailable ?? () => true,
    ),
  ));
  await tester.pumpAndSettle();
}


void main() {

  group('MoneroReceivePanel — no wallet exists, adapter available', () {
    testWidgets(
      'Create Monero wallet button is rendered when adapter is available',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'Generation-pending banner is rendered when adapter unavailable',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client,
          adapter: const NullMoneroWalletAdapter(),
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
          findsNothing,
        );
        expect(
          find.text(kMoneroReceiveGenerationPendingMessage),
          findsOneWidget,
        );
      },
    );
  });


  group('MoneroReceivePanel — Create Monero wallet flow', () {

    testWidgets(
      'tapping Create → generates real address → POSTs ciphertext only '
      '→ refresh shows QR + address',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        await tester.tap(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
        );
        await tester.pumpAndSettle();
        expect(client.createCalls.length, 1);
        final call = client.createCalls.first;
        expect(call['network'], 'monero_mainnet');
        expect(call['asset'], 'XMR');
        expect(call['scannerMode'], 'none');
        expect(call['restoreHeight'], greaterThan(0));
        final generatedAddress = call['publicAddress'] as String;
        expect(generatedAddress.length, 95);
        expect(generatedAddress.substring(0, 1), '4');
        expect(
          moneroPrimaryAddressChecksumValid(generatedAddress),
          true,
        );
        final envelope = call['encryptedWalletSecret'] as String;
        expect(envelope.startsWith('vault-cipher:'), true);
        expect(envelope.contains('spendKey'), false);
        expect(envelope.contains('viewKey'), false);
        expect(envelope.contains('privateSpend'), false);
        expect(envelope.contains('mnemonic'), false);

        expect(
          find.byKey(const Key(kMoneroReceivePanelQrKey)),
          findsOneWidget,
        );
        expect(find.text(generatedAddress), findsOneWidget);
      },
    );

    testWidgets(
      'HTTP payload keys never include mnemonic / spendKey / viewKey / '
      'privateSpendKey / privateViewKey / walletPassword',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        await tester.tap(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
        );
        await tester.pumpAndSettle();
        final call = client.createCalls.first;
        for (final banned in const [
          'mnemonic', 'spendKey', 'viewKey', 'privateSpendKey',
          'privateViewKey', 'walletPassword', 'seed25', 'polyseed',
          'moneroSpendKey', 'moneroViewKey', 'moneroSeed',
          'recoveryPhrase',
        ]) {
          expect(call.containsKey(banned), false,
              reason: 'payload must not carry $banned');
        }
      },
    );

    testWidgets(
      'when vault key is unavailable, Create fails with honest message '
      'and no HTTP call fires',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
          isVaultKeyAvailable: () => false,
        );
        await tester.tap(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
        );
        await tester.pumpAndSettle();
        expect(client.createCalls, isEmpty);
        expect(
          find.byKey(const Key(kMoneroReceivePanelCreateFailedKey)),
          findsOneWidget,
        );
        expect(
          find.text(kMoneroReceiveCreateVaultKeyMissingMessage),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'when generation throws, Create shows honest failure and no fake '
      'address is rendered',
      (tester) async {
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        final failing = InjectedMoneroWalletAdapter(
          generator: ({
            required int restoreHeight,
            required Future<String> Function(String) encryptForVault,
            Uint8List? seedForTests,
          }) async {
            throw const MoneroWalletGenerationFailed('boom');
          },
        );
        await _pumpPanel(tester, client: client, adapter: failing);
        await tester.tap(
          find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)),
        );
        await tester.pumpAndSettle();
        expect(client.createCalls, isEmpty);
        expect(
          find.byKey(const Key(kMoneroReceivePanelCreateFailedKey)),
          findsOneWidget,
        );
        expect(
          find.text(kMoneroReceiveCreateFallbackErrorMessage),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroReceivePanelQrKey)),
          findsNothing,
        );
      },
    );
  });


  group('MoneroReceivePanel — mobile overflow', () {
    testWidgets(
      'no-account state fits without overflow at 420 x 720',
      (tester) async {
        tester.view.physicalSize = const Size(420, 720);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.reset);
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {'wallet_engine': 'no_account'};
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'receive-ready state fits without overflow at 420 x 800',
      (tester) async {
        tester.view.physicalSize = const Size(420, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.reset);
        final client = _MoneroSpyClient();
        client.nextReceiveResponse = {
          'wallet_engine': 'receive_ready',
          'publicAddress':
              '44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7Sq'
              'SsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A',
          'walletLabel':  'Monero',
          'restoreHeight': 3220000,
        };
        await _pumpPanel(
          tester, client: client, adapter: RealMoneroWalletAdapter(),
        );
        expect(tester.takeException(), isNull);
      },
    );
  });


  group('MoneroReceivePanel — private V2 backup', () {
    testWidgets('creates an MVK-encrypted wallet without legacy create',
        (tester) async {
      final legacy = _MoneroSpyClient();
      final posts = <String>[];
      Map<String, dynamic>? staged;
      var state = '';
      const recordId = 'synthetic-monero-v2-record';
      final walletV2 = WalletV2ActiveClient(
        codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 7))),
        accessIsCurrent: () => true,
        creationEnabled: true,
        newRecordId: () => recordId,
        post: (path, body) async {
          posts.add(path);
          expect(body.containsKey('pin'), false);
          expect(jsonEncode(body), isNot(contains('privateSpendKeyHex')));
          if (path == '/vault/wallet-v2') {
            staged = Map<String, dynamic>.from(body);
            state = 'migration_pending';
            return {
              'wallet_record_id': recordId,
              'migration_state': state,
            };
          }
          expect(path, '/vault/wallet-v2/$recordId/publish-new');
          expect(body['readback_receipt'], 'synthetic-receipt');
          state = 'v2_verified';
          return {
            'wallet_record_id': recordId,
            'migration_state': state,
          };
        },
        get: (path) async {
          if (path == '/vault/wallet-v2/pending') {
            return {'wallets': <Object>[]};
          }
          if (path == '/vault/wallet-v2') {
            return {
              'wallets': state == 'v2_verified' ? [
                {
                  'wallet_record_id': recordId,
                  'chain': 'monero',
                  'network': 'monero_mainnet',
                  'asset': 'XMR',
                  'public_address': staged!['public_address'],
                  'wallet_label': 'Monero',
                  'migration_state': state,
                },
              ] : <Object>[],
            };
          }
          expect(path, '/vault/wallet-v2/$recordId');
          return {
            ...staged!,
            'migration_state': state,
            'legacy_item_id': null,
            'readback_receipt': 'synthetic-receipt',
          };
        },
      );
      await _pumpPanel(
        tester,
        client: legacy,
        adapter: RealMoneroWalletAdapter(),
        walletV2: walletV2,
        encryptForVault: (_) async =>
            throw StateError('legacy encryption must not run'),
        isVaultKeyAvailable: () => true,
      );
      expect(find.byKey(const Key(kMoneroReceivePanelGenerationPendingKey)),
          findsOneWidget);
      expect(find.text(kMoneroReceivePrivateAttestation), findsNothing);
      await tester.tap(find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(legacy.createCalls, isEmpty);
      expect(posts, [
        '/vault/wallet-v2',
        '/vault/wallet-v2/$recordId/publish-new',
      ]);
      expect(find.byKey(const Key(kMoneroReceivePanelQrKey)), findsOneWidget);
      expect(find.text(kMoneroReceivePrivateAttestation), findsOneWidget);
      expect(find.byKey(const Key(kMoneroReceivePanelRestoreHeightKey)),
          findsOneWidget);
      final verified = await walletV2.findVerified(
        const WalletV2AccountSlot('monero', 'monero_mainnet', 'XMR'),
      );
      expect(verified, isNotNull);
      final secret = await walletV2.readSigningSecret(verified!);
      expect(secret, contains('"restoreHeight":3230000'));
    });

    testWidgets('existing legacy wallet is shown as needing migration',
        (tester) async {
      final existing = await RealMoneroWalletAdapter().generatePrivate(
        restoreHeight: 3230000,
        seedForTests: Uint8List.fromList(List<int>.filled(32, 17)),
      );
      final legacy = _MoneroSpyClient()
        ..nextReceiveResponse = {
          'wallet_engine': 'receive_ready',
          'publicAddress': existing.publicAddress,
          'walletLabel': 'Existing wallet',
        };
      var posts = 0;
      final walletV2 = WalletV2ActiveClient(
        codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 8))),
        accessIsCurrent: () => true,
        creationEnabled: true,
        post: (_, __) async { posts++; return {}; },
        get: (_) async => {'wallets': <Object>[]},
      );
      await _pumpPanel(
        tester,
        client: legacy,
        adapter: RealMoneroWalletAdapter(),
        walletV2: walletV2,
      );
      expect(find.text(kMoneroReceiveBackupMigrationMessage), findsOneWidget);
      expect(find.byKey(const Key(kMoneroReceivePanelMigrationRequiredKey)),
          findsOneWidget);
      expect(find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)), findsNothing);
      expect(find.byKey(const Key(kMoneroReceivePanelQrKey)), findsNothing);
      expect(find.byKey(const Key(kMoneroReceivePanelAddressTextKey)),
          findsNothing);
      expect(find.byKey(const Key(kMoneroReceivePanelCopyBtnKey)), findsNothing);
      expect(find.byKey(const Key(kMoneroReceivePanelRestoreHeightKey)),
          findsNothing);
      expect(find.text(existing.publicAddress), findsNothing);
      expect(find.text(kMoneroReceivePrivateAttestation), findsNothing);
      expect(find.text(kMoneroReceiveNonCustodialAttestation), findsNothing);
      expect(posts, 0);
      expect(legacy.createCalls, isEmpty);
    });

    testWidgets('unreadable V2 backup never renders a receive QR',
        (tester) async {
      final generated = await RealMoneroWalletAdapter().generatePrivate(
        restoreHeight: 3230000,
        seedForTests: Uint8List.fromList(List<int>.filled(32, 11)),
      );
      const recordId = 'synthetic-unreadable-xmr-record';
      final walletV2 = WalletV2ActiveClient(
        codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 9))),
        accessIsCurrent: () => true,
        get: (path) async => path == '/vault/wallet-v2'
            ? {'wallets': [
                {
                  'wallet_record_id': recordId,
                  'chain': 'monero',
                  'network': 'monero_mainnet',
                  'asset': 'XMR',
                  'public_address': generated.publicAddress,
                  'wallet_label': 'Synthetic',
                  'migration_state': 'v2_verified',
                },
              ]}
            : {
                'wallet_record_id': recordId,
                'chain': 'monero',
                'network': 'monero_mainnet',
                'asset': 'XMR',
                'public_address': generated.publicAddress,
                'wallet_label': 'Synthetic',
                'migration_state': 'v2_verified',
                'envelope_version': 'v2',
                'payload_ciphertext': 'unreadable',
              },
        post: (_, __) async => throw StateError('no writes expected'),
      );
      await _pumpPanel(
        tester,
        client: _MoneroSpyClient(),
        adapter: RealMoneroWalletAdapter(),
        walletV2: walletV2,
      );
      expect(find.byKey(const Key(kMoneroReceivePanelQrKey)), findsNothing);
      expect(find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)), findsNothing);
    });

    testWidgets('session loss during generation causes no V2 write',
        (tester) async {
      final generated = await RealMoneroWalletAdapter().generatePrivate(
        restoreHeight: 3230000,
        seedForTests: Uint8List.fromList(List<int>.filled(32, 13)),
      );
      var current = true;
      var posts = 0;
      final walletV2 = WalletV2ActiveClient(
        codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 9))),
        accessIsCurrent: () => current,
        creationEnabled: true,
        get: (_) async => {'wallets': <Object>[]},
        post: (_, __) async { posts++; return {}; },
      );
      final adapter = InjectedMoneroWalletAdapter(
        generator: ({required restoreHeight, required encryptForVault,
            seedForTests}) async =>
            throw StateError('legacy generator must not run'),
        privateGenerator: ({required restoreHeight, seedForTests}) async {
          current = false;
          return generated;
        },
      );
      await _pumpPanel(
        tester,
        client: _MoneroSpyClient(),
        adapter: adapter,
        walletV2: walletV2,
      );
      await tester.tap(find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)));
      await tester.pumpAndSettle();
      expect(posts, 0);
      expect(find.byKey(const Key(kMoneroReceivePanelQrKey)), findsNothing);
    });

    testWidgets('asset detail opens private XMR receive without legacy key',
        (tester) async {
      final walletV2 = WalletV2ActiveClient(
        codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 9))),
        accessIsCurrent: () => true,
        get: (_) async => {'wallets': <Object>[]},
        post: (_, __) async => throw StateError('no writes expected'),
      );
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineAssetDetailPage(
            asset: 'XMR',
            network: 'monero_mainnet',
            authToken: 'synthetic-token',
            apiClient: _MoneroSpyClient(),
            walletV2: walletV2,
            features: _features(),
            moneroWalletAdapter: RealMoneroWalletAdapter(),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      final receive = find.byKey(const Key(
        'crypto_wallet_engine_asset_detail_receive_btn',
      ));
      await tester.ensureVisible(receive);
      await tester.tap(receive);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kMoneroReceivePanelKey)), findsOneWidget);
      expect(find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('wallet dashboard opens private XMR receive without legacy key',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final walletV2 = WalletV2ActiveClient(
        codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 9))),
        accessIsCurrent: () => true,
        get: (_) async => {'wallets': <Object>[]},
        post: (_, __) async => throw StateError('no writes expected'),
      );
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoWalletEnginePage(
            authToken: 'synthetic-token',
            apiClient: _MoneroSpyClient(),
            walletV2: walletV2,
            moneroWalletAdapter: RealMoneroWalletAdapter(),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      final receive = find.byKey(const Key(
        'crypto_wallet_engine_card_receive_btn_XMR',
      ));
      await tester.ensureVisible(receive);
      await tester.tap(receive);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kMoneroReceivePanelKey)), findsOneWidget);
      expect(find.byKey(const Key(kMoneroReceivePanelCreateBtnKey)), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('MoneroReceivePanel — copy hygiene', () {
    test('no marketing exchange verbs in Monero copy constants', () {
      const forbidden = [
        'buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
      ];
      for (final copy in const [
        kMoneroReceivePanelTitle,
        kMoneroReceiveNetworkBadge,
        kMoneroReceiveNonCustodialAttestation,
        kMoneroReceiveAssetWarning,
        kMoneroReceivePrivacyNote,
        kMoneroReceiveDisabledMessage,
        kMoneroReceiveGenerationPendingMessage,
        kMoneroReceiveCreateButtonLabel,
        kMoneroReceiveCreateBusyLabel,
        kMoneroReceiveCreateVaultKeyMissingMessage,
        kMoneroReceiveCreateFallbackErrorMessage,
      ]) {
        for (final v in forbidden) {
          expect(
            copy.toLowerCase(), isNot(contains(' $v ')),
            reason: 'copy must not contain marketing verb "$v": $copy',
          );
        }
      }
    });

    test('never asks user to type a seed / mnemonic / spend / view key', () {
      const inputs = [
        'seed', 'mnemonic', 'spend key', 'view key', 'polyseed',
      ];
      for (final copy in const [
        kMoneroReceiveCreateButtonLabel,
        kMoneroReceiveCreateBusyLabel,
        kMoneroReceiveCreateVaultKeyMissingMessage,
        kMoneroReceiveCreateFallbackErrorMessage,
      ]) {
        for (final tok in inputs) {
          expect(
            copy.toLowerCase(),
            isNot(contains('enter your $tok')),
          );
          expect(
            copy.toLowerCase(),
            isNot(contains('paste your $tok')),
          );
        }
      }
    });
  });
}
