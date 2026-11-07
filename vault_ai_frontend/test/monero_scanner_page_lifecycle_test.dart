import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_scanner.dart';
import 'package:vault_ai_frontend/services/monero_wallet.dart';
import 'package:vault_ai_frontend/services/wallet_v2_active_client.dart';
import 'package:vault_ai_frontend/services/wallet_v2_migration.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_scanner_card.dart';

class _Lease extends ChangeNotifier {
  bool current = true;

  void lock() {
    current = false;
    notifyListeners();
  }

  void unlock() {
    current = true;
    notifyListeners();
  }
}

class _ScannerApi extends VaultAIClient {
  final String address;

  _ScannerApi(this.address) : super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async =>
      {
        'wallet_engine': 'receive_ready',
        'publicAddress': address,
        'walletLabel': 'Synthetic',
      };

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) async =>
      {
        'balanceStatus': 'unavailable',
        'reason': 'scanner_not_configured',
      };

  @override
  Future<Map<String, dynamic>> getXmrScannerStatus({
    required String authToken,
    String? clientPlatform,
  }) async =>
      throw StateError('No backend scanner in synthetic test');
}

void main() {
  testWidgets('XMR page stops on lock and close across rapid unlock',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final generated = await RealMoneroWalletAdapter().generatePrivate(
      restoreHeight: 3000000,
      seedForTests: Uint8List.fromList(List<int>.filled(32, 13)),
    );
    const recordId = 'synthetic-xmr-scanner-record';
    final identity = WalletV2Identity(
      recordId: recordId,
      chain: 'monero',
      network: 'monero_mainnet',
      asset: 'XMR',
      publicAddress: generated.publicAddress,
      label: 'Synthetic',
    );
    final codec = WalletV2EnvelopeCodec(SecretKey(List<int>.filled(32, 9)));
    final ciphertext = await codec.wrap(identity, generated.secret);
    final lease = _Lease();
    addTearDown(lease.dispose);
    final walletV2 = WalletV2ActiveClient(
      codec: codec,
      accessIsCurrent: () => lease.current,
      get: (path) async => path == '/vault/wallet-v2'
          ? {
              'wallets': [
                {
                  'wallet_record_id': recordId,
                  'chain': 'monero',
                  'network': 'monero_mainnet',
                  'asset': 'XMR',
                  'public_address': generated.publicAddress,
                  'wallet_label': 'Synthetic',
                  'migration_state': 'v2_verified',
                },
              ]
            }
          : {
              'wallet_record_id': recordId,
              'chain': 'monero',
              'network': 'monero_mainnet',
              'asset': 'XMR',
              'public_address': generated.publicAddress,
              'wallet_label': 'Synthetic',
              'migration_state': 'v2_verified',
              'envelope_version': 'v2',
              'payload_ciphertext': ciphertext,
            },
      post: (_, __) async => throw StateError('No writes in synthetic test'),
    );
    var starts = 0;
    var stops = 0;
    final adapter = InjectedMoneroScannerAdapter(
      available: true,
      onStart: (_) async {
        starts++;
      },
      onStop: () async {
        stops++;
      },
    );
    addTearDown(adapter.dispose);
    final features = CryptoWalletFeatures.fromBackend({
      'xmrEnabled': true,
      'xmrClientScannerSupported': true,
      'xmrScannerMode': 'client_local',
    });
    await tester.pumpWidget(MaterialApp(
        home: CryptoWalletEngineAssetDetailPage(
      asset: 'XMR',
      network: 'monero_mainnet',
      authToken: 'synthetic-token',
      apiClient: _ScannerApi(generated.publicAddress),
      accessChanges: lease,
      walletV2: walletV2,
      features: features,
      moneroScannerAdapter: adapter,
    )));
    await tester.pumpAndSettle();
    final startButton = find.byKey(const Key(kMoneroScannerStartBtnKey));
    await tester.ensureVisible(startButton);
    await tester.tap(startButton);
    await tester.pumpAndSettle();
    expect(starts, 1);
    expect(stops, 0);

    lease.lock();
    lease.unlock();
    await tester.pumpAndSettle();
    expect(stops, 1);
    await tester.tap(startButton);
    await tester.pumpAndSettle();
    expect(starts, 2);
    await tester.pumpWidget(const MaterialApp(home: SizedBox()));
    await tester.pump();
    expect(stops, 2);
  });
}
