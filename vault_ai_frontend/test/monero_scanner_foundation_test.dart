


import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/monero_scanner.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_monero_scanner_card.dart';


CryptoWalletFeatures _features({
  bool xmrOn = true,
  bool clientScannerSupported = false,
}) {
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
    'xmrClientScannerSupported': clientScannerSupported,
    'xmrBackendScannerEnabled':  false,
    'supportedNetworks':         const ['ethereum_sepolia'],
    'supportedAssetsByNetwork':  const {},
  });
}


Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));


void main() {

  group('MoneroScannerAdapter contract', () {
    test('NullMoneroScannerAdapter is unavailable with an honest reason', () {
      const adapter = NullMoneroScannerAdapter();
      expect(adapter.isAvailable, false);
      expect(adapter.availabilityReason, isNotEmpty);
      expect(
        adapter.availabilityReason,
        contains('not wired into this build'),
      );
    });

    test('NullMoneroScannerAdapter startScan throws honest state error',
        () async {
      const adapter = NullMoneroScannerAdapter();
      expect(
        () => adapter.startScan(MoneroScannerInput(
          privateViewKey: Uint8List(32),
          publicSpendKey: Uint8List(32),
          publicAddress: '',
          restoreHeight: 0,
        )),
        throwsStateError,
      );
    });

    test('NullMoneroScannerAdapter status defaults to scannerUnavailable',
        () async {
      const adapter = NullMoneroScannerAdapter();
      final s = await adapter.getSyncStatus();
      expect(s.state, MoneroScannerState.scannerUnavailable);
      expect(s.isUnavailable, true);
    });

    test('NullMoneroScannerAdapter balance defaults to unavailable',
        () async {
      const adapter = NullMoneroScannerAdapter();
      final b = await adapter.getBalance();
      expect(b.status, MoneroScannerErrorCode.balanceStatusUnavailable);
      expect(b.reason, MoneroScannerErrorCode.scannerUnavailable);
      expect(b.unlockedAmount, isNull);
      expect(b.lockedAmount, isNull);
      expect(b.totalAmount, isNull);
    });

    test('NullMoneroScannerAdapter transactions defaults to empty', () async {
      const adapter = NullMoneroScannerAdapter();
      final txs = await adapter.getTransactions();
      expect(txs, isEmpty);
    });

    test('MoneroScannerInput toString is redacted — no key material leaks',
        () {
      final input = MoneroScannerInput(
        privateViewKey: Uint8List.fromList([0xDE, 0xAD, 0xBE, 0xEF]),
        publicSpendKey: Uint8List.fromList([0x01, 0x02, 0x03, 0x04]),
        publicAddress: '4XmrAddressExample',
        restoreHeight: 3220000,
      );
      final s = input.toString();
      expect(s.contains('DEADBEEF'), false);
      expect(s.contains('01020304'), false);
      expect(s, 'MoneroScannerInput(<redacted>)');
    });

    test('MoneroScannerInput.wipe zeroes the private view key', () {
      final input = MoneroScannerInput(
        privateViewKey: Uint8List.fromList(List.filled(32, 0xAB)),
        publicSpendKey: Uint8List(32),
        publicAddress: '',
        restoreHeight: 0,
      );
      input.wipe();
      expect(input.privateViewKey.every((b) => b == 0), true);
    });

    test('InjectedMoneroScannerAdapter forwards status/balance/txs '
        'and start/stop callbacks', () async {
      var startedInputAddr = '';
      var stopCount = 0;
      final adapter = InjectedMoneroScannerAdapter(
        available: true,
        initialStatus: MoneroSyncStatus(
          state: MoneroScannerState.syncing,
          restoreHeight: 3200000,
          currentHeight: 3200100,
          targetHeight: 3220000,
          percent: 0.5,
        ),
        initialBalance: MoneroBalanceReading.ready(
          unlocked: '1.5', locked: '0.5', total: '2.0',
        ),
        initialTransactions: [
          const MoneroTransactionRow(
            txId: 'abc123',
            direction: MoneroTransactionDirection.incoming,
            amount: '1.5',
            confirmations: 10,
          ),
        ],
        onStart: (input) async {
          startedInputAddr = input.publicAddress;
        },
        onStop: () async {
          stopCount += 1;
        },
      );
      await adapter.startScan(MoneroScannerInput(
        privateViewKey: Uint8List(32),
        publicSpendKey: Uint8List(32),
        publicAddress: '4TestAddress',
        restoreHeight: 3200000,
      ));
      expect(startedInputAddr, '4TestAddress');
      final s = await adapter.getSyncStatus();
      expect(s.state, MoneroScannerState.syncing);
      expect(s.percent, 0.5);
      final b = await adapter.getBalance();
      expect(b.totalAmount, '2.0');
      final txs = await adapter.getTransactions();
      expect(txs.length, 1);
      await adapter.stopScan();
      expect(stopCount, 1);
      await adapter.dispose();
    });
  });


  group('MoneroScannerCard rendering', () {

    testWidgets('unavailable state shows honest copy — no Start button',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: const NullMoneroScannerAdapter(),
          features: _features(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMoneroScannerCardKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroScannerUnavailableCopyKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroScannerStartBtnKey)),
        findsNothing,
      );
      expect(
        find.byKey(const Key(kMoneroScannerStopBtnKey)),
        findsNothing,
      );
    });

    testWidgets('not-started state shows Start button when scanner available',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(
        available: true,
        initialStatus: MoneroSyncStatus.notStarted(restoreHeight: 3220000),
      );
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 3220000),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMoneroScannerStartBtnKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroScannerStopBtnKey)),
        findsNothing,
      );
      expect(find.text(kMoneroScannerNotStartedCopy), findsOneWidget);
      await adapter.dispose();
    });

    testWidgets(
      'syncing state renders restore/current/target/percent pills',
      (tester) async {
        final adapter = InjectedMoneroScannerAdapter(available: true);
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineMoneroScannerCard(
            scannerAdapter: adapter,
            features: _features(clientScannerSupported: true),
            status: MoneroSyncStatus(
              state: MoneroScannerState.syncing,
              restoreHeight: 3200000,
              currentHeight: 3210000,
              targetHeight: 3220000,
              percent: 0.65,
            ),
          ),
        ));
        await tester.pumpAndSettle();
        expect(find.text(kMoneroScannerSyncingCopy), findsOneWidget);
        expect(
          find.byKey(const Key(kMoneroScannerRestoreHeightKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroScannerCurrentHeightKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroScannerTargetHeightKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroScannerPercentKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroScannerStopBtnKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kMoneroScannerStartBtnKey)),
          findsNothing,
        );
        await adapter.dispose();
      },
    );

    testWidgets('failed state renders error reason honestly',
        (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: const MoneroSyncStatus(
            state: MoneroScannerState.failed,
            restoreHeight: 3220000,
            errorReason: MoneroScannerErrorCode.daemonUnreachable,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text(kMoneroScannerFailedCopy), findsOneWidget);
      expect(
        find.byKey(const Key(kMoneroScannerErrorReasonKey)),
        findsOneWidget,
      );
      await adapter.dispose();
    });

    testWidgets('daemon privacy note is always rendered', (tester) async {
      final adapter = InjectedMoneroScannerAdapter(available: true);
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: adapter,
          features: _features(clientScannerSupported: true),
          status: MoneroSyncStatus.notStarted(restoreHeight: 3220000),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMoneroScannerPrivacyNoteKey)),
        findsOneWidget,
      );
      expect(
        find.text(kMoneroScannerDaemonPrivacyNote),
        findsOneWidget,
      );
      await adapter.dispose();
    });

    testWidgets('mobile 420 x 800 renders scanner card without overflow',
        (tester) async {
      tester.view.physicalSize = const Size(420, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final adapter = InjectedMoneroScannerAdapter(available: true);
      await tester.pumpWidget(_wrap(
        SingleChildScrollView(
          child: CryptoWalletEngineMoneroScannerCard(
            scannerAdapter: adapter,
            features: _features(clientScannerSupported: true),
            status: const MoneroSyncStatus(
              state: MoneroScannerState.syncing,
              restoreHeight: 3200000,
              currentHeight: 3210000,
              targetHeight: 3220000,
              percent: 0.65,
            ),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await adapter.dispose();
    });
  });


  group('MoneroBalanceCard reads from scanner state', () {

    testWidgets('scannerUnavailable → shows scanner-not-enabled copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
          scannerStatus: MoneroSyncStatus.scannerUnavailable(),
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroBalanceScannerNotEnabledKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroBalanceReadyKey)),
        findsNothing,
      );
    });

    testWidgets('notStarted → shows scanner-not-started copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
          scannerStatus: MoneroSyncStatus.notStarted(restoreHeight: 3220000),
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroBalanceScannerNotStartedKey)),
        findsOneWidget,
      );
    });

    testWidgets('syncing → shows syncing copy, no fake balance',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
          scannerStatus: const MoneroSyncStatus(
            state: MoneroScannerState.syncing,
            restoreHeight: 3200000,
          ),
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroBalanceSyncingKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroBalanceReadyKey)),
        findsNothing,
      );
    });

    testWidgets('synced + ready balance → renders total/unlocked/locked',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
          scannerStatus: const MoneroSyncStatus(
            state: MoneroScannerState.synced,
            restoreHeight: 3200000,
          ),
          balance: MoneroBalanceReading.ready(
            unlocked: '1.5', locked: '0.5', total: '2.0',
          ),
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroBalanceTotalKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroBalanceUnlockedKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroBalanceLockedKey)),
        findsOneWidget,
      );
      expect(find.text('Total: 2.0 XMR'), findsOneWidget);
      expect(find.text('Unlocked: 1.5 XMR'), findsOneWidget);
      expect(find.text('Locked: 0.5 XMR'), findsOneWidget);
    });

    testWidgets(
      'synced + real zero → renders 0 XMR (not the "not enabled" text)',
      (tester) async {
        await tester.pumpWidget(_wrap(
          CryptoWalletEngineMoneroBalanceCard(
            features: _features(),
            scannerStatus: const MoneroSyncStatus(
              state: MoneroScannerState.synced,
              restoreHeight: 3200000,
            ),
            balance: MoneroBalanceReading.ready(
              unlocked: '0', locked: '0', total: '0',
            ),
          ),
        ));
        expect(find.text('Total: 0 XMR'), findsOneWidget);
        expect(
          find.byKey(const Key(kMoneroBalanceScannerNotEnabledKey)),
          findsNothing,
        );
      },
    );

    testWidgets('synced but balance null → still honest, no fake zero',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroBalanceCard(
          features: _features(),
          scannerStatus: const MoneroSyncStatus(
            state: MoneroScannerState.synced,
            restoreHeight: 3200000,
          ),
          balance: null,
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroBalanceScannerNotEnabledKey)),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroBalanceReadyKey)),
        findsNothing,
      );
    });
  });


  group('MoneroActivityCard reads from scanner state', () {

    testWidgets('scannerUnavailable → shows scanner-not-enabled copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(),
          scannerStatus: MoneroSyncStatus.scannerUnavailable(),
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroActivityScannerNotEnabledKey)),
        findsOneWidget,
      );
    });

    testWidgets('notStarted → shows scanner-not-started copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(),
          scannerStatus: MoneroSyncStatus.notStarted(restoreHeight: 3220000),
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroActivityScannerNotStartedKey)),
        findsOneWidget,
      );
    });

    testWidgets('syncing → shows syncing copy, no fake rows',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(),
          scannerStatus: const MoneroSyncStatus(
            state: MoneroScannerState.syncing,
            restoreHeight: 3200000,
          ),
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroActivitySyncingKey)),
        findsOneWidget,
      );
    });

    testWidgets('synced but no transactions → honest empty state',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(),
          scannerStatus: const MoneroSyncStatus(
            state: MoneroScannerState.synced,
            restoreHeight: 3200000,
          ),
          transactions: const <MoneroTransactionRow>[],
        ),
      ));
      expect(
        find.byKey(const Key(kMoneroActivityEmptyAfterSyncKey)),
        findsOneWidget,
      );
    });

    testWidgets('synced with transactions → renders each tx row',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoWalletEngineMoneroActivityCard(
          features: _features(),
          scannerStatus: const MoneroSyncStatus(
            state: MoneroScannerState.synced,
            restoreHeight: 3200000,
          ),
          transactions: const [
            MoneroTransactionRow(
              txId: 'aabbccddeeff11223344',
              direction: MoneroTransactionDirection.incoming,
              amount: '1.5',
              confirmations: 10,
            ),
            MoneroTransactionRow(
              txId: '112233445566778899aa',
              direction: MoneroTransactionDirection.outgoing,
              amount: '0.5',
              confirmations: 3,
              locked: true,
            ),
          ],
        ),
      ));
      expect(
        find.byKey(const Key('${kMoneroActivityRowKeyPrefix}0')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('${kMoneroActivityRowKeyPrefix}1')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(kMoneroActivityEmptyAfterSyncKey)),
        findsNothing,
      );
    });
  });


  group('Scanner copy hygiene', () {
    test('no marketing verbs in scanner copy constants', () {
      const forbidden = [
        'buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
      ];
      for (final copy in const [
        kMoneroScannerHeading,
        kMoneroScannerStartLabel,
        kMoneroScannerStopLabel,
        kMoneroScannerRequiresWalletCopy,
        kMoneroScannerRunsOnDeviceCopy,
        kMoneroScannerDoNotCloseAppCopy,
        kMoneroScannerSyncTimeCopy,
        kMoneroScannerUnavailableCopy,
        kMoneroScannerNotStartedCopy,
        kMoneroScannerSyncingCopy,
        kMoneroScannerSyncedCopy,
        kMoneroScannerFailedCopy,
        kMoneroScannerStoppedCopy,
        kMoneroScannerDaemonPrivacyNote,
      ]) {
        for (final v in forbidden) {
          expect(
            copy.toLowerCase(), isNot(contains(' $v ')),
            reason: 'copy must not contain "$v": $copy',
          );
        }
      }
    });

    test('never asks user to type seed / mnemonic / view / spend key', () {
      const inputs = [
        'seed', 'mnemonic', 'spend key', 'view key', 'polyseed',
      ];
      for (final copy in const [
        kMoneroScannerStartLabel,
        kMoneroScannerRequiresWalletCopy,
        kMoneroScannerRunsOnDeviceCopy,
        kMoneroScannerDoNotCloseAppCopy,
        kMoneroScannerUnavailableCopy,
        kMoneroScannerNotStartedCopy,
        kMoneroScannerSyncingCopy,
        kMoneroScannerFailedCopy,
        kMoneroScannerStoppedCopy,
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

    test(
      'scanner error code closed set is what the taxonomy documents',
      () {
        expect(MoneroScannerErrorCode.allowedErrorCodes, contains(
          MoneroScannerErrorCode.daemonUnreachable,
        ));
        expect(MoneroScannerErrorCode.allowedErrorCodes, contains(
          MoneroScannerErrorCode.daemonRejectedRequest,
        ));
        expect(MoneroScannerErrorCode.allowedErrorCodes, contains(
          MoneroScannerErrorCode.invalidWalletSecret,
        ));
        expect(MoneroScannerErrorCode.allowedErrorCodes, contains(
          MoneroScannerErrorCode.scannerInternalError,
        ));
        expect(MoneroScannerErrorCode.allowedErrorCodes, contains(
          MoneroScannerErrorCode.scannerUnavailable,
        ));
        expect(MoneroScannerErrorCode.allowedErrorCodes, contains(
          MoneroScannerErrorCode.scanStopped,
        ));
      },
    );
  });


  group('Features model', () {
    test('backend flags flow into xmrClientScannerSupported', () {
      final f = CryptoWalletFeatures.fromBackend(const {
        'xmrEnabled':                true,
        'xmrClientScannerSupported': true,
        'xmrBackendScannerEnabled':  false,
      });
      expect(f.xmrClientScannerSupported, true);
      expect(f.xmrBackendScannerEnabled, false);
    });

    test('unknown() defaults both flags to false', () {
      const f = CryptoWalletFeatures.unknown();
      expect(f.xmrClientScannerSupported, false);
      expect(f.xmrBackendScannerEnabled, false);
    });
  });
}
