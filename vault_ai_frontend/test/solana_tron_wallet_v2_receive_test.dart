import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/wallet_v2_active_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_tron_send_panel.dart';

class _ReceiveApi extends VaultAIClient {
  _ReceiveApi(this.body, {this.onRead}) : super(baseUrl: 'http://test.invalid');

  final Map<String, dynamic> body;
  final Map<String, dynamic> Function()? onRead;
  int legacyCreates = 0;

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async =>
      onRead?.call() ?? body;

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) async =>
      {
        'balanceStatus': 'available',
        'asset': asset,
        'networkId': network,
        'publicAddress': address,
        'unit': asset == 'SOL' ? 'SOL' : 'USDT',
        'availableAmount': '10',
        'availableBaseUnits': '10000000000',
      };

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
    legacyCreates++;
    throw StateError('Legacy wallet write attempted');
  }
}

class _V2Store {
  _V2Store(this.slot);

  final WalletV2AccountSlot slot;
  Map<String, dynamic>? staged;
  bool verified = false;
  int stageWrites = 0;
  int publishWrites = 0;
  final String recordId = 'synthetic-wallet-record';

  WalletV2ActiveClient client() => WalletV2ActiveClient(
        codec: WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 13))),
        accessIsCurrent: () => true,
        creationEnabled: true,
        newRecordId: () => recordId,
        get: (path) async {
          if (path == '/vault/wallet-v2') {
            return {
              'wallets': verified
                  ? [
                      {
                        'wallet_record_id': recordId,
                        'chain': slot.chain,
                        'network': slot.network,
                        'asset': slot.asset,
                        'public_address': staged!['public_address'],
                        'wallet_label': staged!['wallet_label'],
                        'migration_state': 'v2_verified',
                      },
                    ]
                  : <Object>[],
            };
          }
          if (path == '/vault/wallet-v2/pending') {
            return {'wallets': <Object>[]};
          }
          expect(path, '/vault/wallet-v2/$recordId');
          return {
            ...staged!,
            'migration_state': verified ? 'v2_verified' : 'migration_pending',
            'legacy_item_id': null,
            'legacy_source_snapshot': null,
            'readback_receipt': 'synthetic-readback-receipt',
          };
        },
        post: (path, body) async {
          expect(body, isNot(contains('pin')));
          if (path == '/vault/wallet-v2') {
            stageWrites++;
            staged = body;
            expect(body['payload_ciphertext'], isA<String>());
            expect(body['chain'], slot.chain);
            return {
              'wallet_record_id': recordId,
              'migration_state': 'migration_pending',
            };
          }
          expect(path, '/vault/wallet-v2/$recordId/publish-new');
          expect(body['readback_receipt'], 'synthetic-readback-receipt');
          publishWrites++;
          verified = true;
          return {
            'wallet_record_id': recordId,
            'migration_state': 'v2_verified',
          };
        },
      );
}

CryptoWalletFeatures _sendFeatures(String chain) =>
    CryptoWalletFeatures.fromBackend({
      'walletEngineEnabled': true,
      'sepoliaReceiveEnabled': true,
      'sepoliaSendEnabled': true,
      'mainnetReceiveEnabled': false,
      'mainnetErc20ReceiveEnabled': false,
      'mainnetSendEnabled': false,
      'mainnetSendPaused': false,
      'defaultNetwork': 'ethereum_sepolia',
      'defaultNetworkConfigValid': true,
      'solanaEnabled': chain == 'solana',
      'solanaReceiveEnabled': chain == 'solana',
      'solanaBalanceEnabled': chain == 'solana',
      'solanaSendEnabled': chain == 'solana',
      'solanaSendPaused': false,
      'tronEnabled': chain == 'tron',
      'tronReceiveEnabled': chain == 'tron',
      'tronBalanceEnabled': chain == 'tron',
      'tronSendEnabled': chain == 'tron',
      'tronSendPaused': false,
      'tronUsdtContractConfigured': chain == 'tron',
      'supportedNetworks': ['ethereum_sepolia', '${chain}_mainnet'],
      'supportedAssetsByNetwork': {
        'ethereum_sepolia': ['ETH'],
        '${chain}_mainnet': [chain == 'solana' ? 'SOL' : 'USDT_TRC20'],
      },
    });

void main() {
  for (final chain in ['solana', 'tron']) {
    final slot = chain == 'solana'
        ? const WalletV2AccountSlot('solana', 'solana_mainnet', 'SOL')
        : const WalletV2AccountSlot('tron', 'tron_mainnet', 'USDT_TRC20');
    final createKey = chain == 'solana'
        ? kSolanaReceivePanelCreateBtnKey
        : kTronReceivePanelCreateBtnKey;
    final addressKey = chain == 'solana'
        ? kSolanaReceivePanelAddressTextKey
        : kTronReceivePanelAddressTextKey;

    testWidgets('$chain creates a verified V2 wallet without legacy write',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final store = _V2Store(slot);
      final api = _ReceiveApi({'wallet_engine': 'no_account'}, onRead: () {
        if (!store.verified) return {'wallet_engine': 'no_account'};
        return {
          'wallet_engine': 'receive_ready',
          'publicAddress': store.staged!['public_address'],
          'walletLabel': store.staged!['wallet_label'],
          'walletRecordId': store.recordId,
          'backupStatus': 'wallet_v2_encrypted',
        };
      });
      final panel = chain == 'solana'
          ? CryptoWalletEngineSolanaReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            )
          : CryptoWalletEngineTronReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            );
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: panel)));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(Key(createKey)));
      await tester.pumpAndSettle();

      expect(store.stageWrites, 1);
      expect(store.publishWrites, 1);
      expect(store.verified, isTrue);
      expect(find.byKey(Key(addressKey)), findsOneWidget);
      expect(
          find.byKey(Key(chain == 'solana'
              ? kSolanaReceivePanelQrKey
              : kTronReceivePanelQrKey)),
          findsOneWidget);
      expect(find.byKey(Key('${chain}_receive_panel_migration_warning')),
          findsNothing);
      expect(api.legacyCreates, 0);
    });

    testWidgets('$chain hides an unmigrated legacy receive address',
        (tester) async {
      final api = _ReceiveApi({
        'wallet_engine': 'receive_ready',
        'publicAddress': 'legacy-address-do-not-display',
        'walletLabel': 'Legacy wallet',
      });
      final store = _V2Store(slot);
      final panel = chain == 'solana'
          ? CryptoWalletEngineSolanaReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            )
          : CryptoWalletEngineTronReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            );
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: panel)));
      await tester.pumpAndSettle();
      expect(find.byKey(Key('${chain}_receive_panel_migration_warning')),
          findsOneWidget);
      expect(
          find.textContaining('legacy-address-do-not-display'), findsNothing);
      expect(find.byKey(Key(addressKey)), findsNothing);
      expect(
          find.byKey(Key(chain == 'solana'
              ? kSolanaReceivePanelQrKey
              : kTronReceivePanelQrKey)),
          findsNothing);
      expect(
          find.byKey(Key(chain == 'solana'
              ? kSolanaReceivePanelCopyBtnKey
              : kTronReceivePanelCopyBtnKey)),
          findsNothing);
      expect(find.textContaining('secret key is encrypted'), findsNothing);
    });

    testWidgets('$chain rejects a V2 address mismatch without metadata',
        (tester) async {
      final api = _ReceiveApi({
        'wallet_engine': 'receive_ready',
        'publicAddress': 'different-backend-address',
      });
      final store = _V2Store(slot);
      store.verified = true;
      store.staged = {
        'public_address': 'synthetic-private-address',
        'wallet_label': 'Synthetic wallet',
      };
      final panel = chain == 'solana'
          ? CryptoWalletEngineSolanaReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            )
          : CryptoWalletEngineTronReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            );
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: panel)));
      await tester.pumpAndSettle();
      expect(find.textContaining('Wallet account verification failed'),
          findsOneWidget);
      expect(find.byKey(Key(addressKey)), findsNothing);
    });

    testWidgets('$chain rejects a legacy response beside a verified V2 slot',
        (tester) async {
      final store = _V2Store(slot);
      store.verified = true;
      store.staged = {
        'public_address': 'synthetic-private-address',
        'wallet_label': 'Synthetic wallet',
      };
      final api = _ReceiveApi({
        'wallet_engine': 'receive_ready',
        'publicAddress': 'synthetic-private-address',
        'backupStatus': 'encrypted_backup_saved',
      });
      final panel = chain == 'solana'
          ? CryptoWalletEngineSolanaReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            )
          : CryptoWalletEngineTronReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            );
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: panel)));
      await tester.pumpAndSettle();
      expect(find.textContaining('Wallet account verification failed'),
          findsOneWidget);
      expect(find.byKey(Key(addressKey)), findsNothing);
    });

    testWidgets('$chain rejects a backend/V2 identity mismatch',
        (tester) async {
      final api = _ReceiveApi({
        'wallet_engine': 'receive_ready',
        'publicAddress': 'synthetic-backend-address',
        'walletRecordId': 'wrong-record',
        'backupStatus': 'wallet_v2_encrypted',
      });
      final store = _V2Store(slot);
      store.verified = true;
      store.staged = {
        'public_address': 'synthetic-backend-address',
        'wallet_label': 'Synthetic wallet',
      };
      final panel = chain == 'solana'
          ? CryptoWalletEngineSolanaReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            )
          : CryptoWalletEngineTronReceivePanel(
              authToken: 'synthetic-token',
              client: api,
              encryptForVault: (_) async => throw StateError('Legacy key used'),
              isVaultKeyAvailable: () => true,
              walletV2: store.client(),
            );
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: panel)));
      await tester.pumpAndSettle();
      expect(find.textContaining('Wallet account verification failed'),
          findsOneWidget);
      expect(find.byKey(Key(addressKey)), findsNothing);
      expect(api.legacyCreates, 0);
    });

    testWidgets('$chain asset detail opens V2 receive without legacy key',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = _ReceiveApi({'wallet_engine': 'no_account'});
      final store = _V2Store(slot);
      await tester.pumpWidget(MaterialApp(
        home: CryptoWalletEngineAssetDetailPage(
          asset: slot.asset,
          network: slot.network,
          authToken: 'synthetic-token',
          apiClient: api,
          walletV2: store.client(),
        ),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find
          .byKey(const Key('crypto_wallet_engine_asset_detail_receive_btn')));
      await tester.pumpAndSettle();
      expect(find.byKey(Key(createKey)), findsOneWidget);
      expect(api.legacyCreates, 0);
    });

    testWidgets('$chain asset detail keeps V2 send closed until routing review',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final store = _V2Store(slot);
      store.verified = true;
      store.staged = {
        'public_address': 'synthetic-private-address',
        'wallet_label': 'Synthetic wallet',
      };
      final api = _ReceiveApi({
        'wallet_engine': 'receive_ready',
        'publicAddress': 'synthetic-private-address',
        'walletRecordId': store.recordId,
        'backupStatus': 'wallet_v2_encrypted',
      });
      await tester.pumpWidget(MaterialApp(
        home: CryptoWalletEngineAssetDetailPage(
          asset: slot.asset,
          network: slot.network,
          authToken: 'synthetic-token',
          apiClient: api,
          walletV2: store.client(),
          verifyPin: (_) async => true,
          loadFromAddress: (_) async => 'synthetic-private-address',
          features: _sendFeatures(chain),
        ),
      ));
      await tester.pumpAndSettle();
      final send = tester.widget<ElevatedButton>(find.byKey(
          const Key('crypto_wallet_engine_asset_detail_send_btn')));
      expect(send.onPressed, isNull);
      expect(find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_address_text')), findsNothing);
      expect(find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_address_unverified')),
          findsOneWidget);
      expect(find.byType(CryptoWalletEngineSolanaSendPanel), findsNothing);
      expect(find.byType(CryptoWalletEngineTronSendPanel), findsNothing);
      expect(api.legacyCreates, 0);
    });
  }
}
