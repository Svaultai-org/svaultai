import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_scan_session.dart';
import 'package:vault_ai_frontend/services/monero_scanner.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_scanner_card.dart';

MoneroScannerInput _input() => MoneroScannerInput(
      privateViewKey: Uint8List.fromList(List<int>.filled(32, 7)),
      publicSpendKey: Uint8List(32),
      publicAddress: 'synthetic-address',
      restoreHeight: 3000000,
    );

CryptoWalletFeatures _features({
  bool enabled = true,
  bool supported = true,
  String mode = 'client_local',
}) =>
    CryptoWalletFeatures.fromBackend({
      'xmrEnabled': enabled,
      'xmrClientScannerSupported': supported,
      'xmrScannerMode': mode,
    });

void main() {
  test('local scan requires every server feature flag', () {
    expect(const CryptoWalletFeatures.unknown().xmrLocalScannerEnabled, false);
    expect(_features(enabled: false).xmrLocalScannerEnabled, false);
    expect(_features(supported: false).xmrLocalScannerEnabled, false);
    expect(_features(mode: 'none').xmrLocalScannerEnabled, false);
    expect(_features().xmrLocalScannerEnabled, true);
  });

  testWidgets('available adapter cannot show Start with feature off', (
    tester,
  ) async {
    final adapter = InjectedMoneroScannerAdapter(available: true);
    addTearDown(adapter.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineMoneroScannerCard(
            scannerAdapter: adapter,
            features: _features(mode: 'none'),
            requirePrivateWalletCapability: true,
          ),
        ),
      ),
    );
    expect(find.byKey(const Key(kMoneroScannerStartBtnKey)), findsNothing);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineMoneroScannerCard(
            scannerAdapter: adapter,
            features: _features(),
            requirePrivateWalletCapability: true,
          ),
        ),
      ),
    );
    expect(find.byKey(const Key(kMoneroScannerStartBtnKey)), findsOneWidget);
  });

  test(
    'close stops an active scan and start wipes the caller view key',
    () async {
      var stops = 0;
      final adapter = InjectedMoneroScannerAdapter(
        available: true,
        onStart: (_) async {},
        onStop: () async {
          stops++;
        },
      );
      addTearDown(adapter.dispose);
      final session = MoneroScanSession(adapter);
      final input = _input();
      await session.start(input, accessIsCurrent: () => true);
      expect(input.privateViewKey.every((byte) => byte == 0), true);
      await session.close();
      expect(stops, 1);
      expect(session.isClosed, true);
    },
  );

  test(
    'lock during pending start stops before and after start completes',
    () async {
      final startCompletion = Completer<void>();
      var stops = 0;
      final adapter = InjectedMoneroScannerAdapter(
        available: true,
        onStart: (_) => startCompletion.future,
        onStop: () async {
          stops++;
        },
      );
      addTearDown(adapter.dispose);
      final session = MoneroScanSession(adapter);
      final input = _input();
      var access = true;
      final starting = session.start(input, accessIsCurrent: () => access);
      access = false;
      await session.close();
      expect(stops, 1);
      startCompletion.complete();
      await expectLater(starting, throwsStateError);
      expect(stops, 2);
      expect(input.privateViewKey.every((byte) => byte == 0), true);
    },
  );

  test('partial start failure stops scanner and wipes the view key', () async {
    var stops = 0;
    final adapter = InjectedMoneroScannerAdapter(
      available: true,
      onStart: (_) async {
        throw StateError('partial native start');
      },
      onStop: () async {
        stops++;
      },
    );
    addTearDown(adapter.dispose);
    final input = _input();
    await expectLater(
      MoneroScanSession(adapter).start(input, accessIsCurrent: () => true),
      throwsStateError,
    );
    expect(stops, 1);
    expect(input.privateViewKey.every((byte) => byte == 0), true);
  });
}
