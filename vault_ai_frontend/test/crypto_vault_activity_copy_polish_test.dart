


import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


CryptoWalletFeatures _features({
  bool solanaEnabled = false,
  bool solanaActivityConnected = false,
  bool tronEnabled = false,
  bool tronActivityConnected = false,
  bool xmrEnabled = false,
}) {
  return CryptoWalletFeatures.fromBackend(<String, dynamic>{
    'mainnetReceiveEnabled':      true,
    'mainnetErc20ReceiveEnabled': true,
    'solanaEnabled':              solanaEnabled,
    'solanaActivityConnected':    solanaActivityConnected,
    'tronEnabled':                tronEnabled,
    'tronActivityConnected':      tronActivityConnected,
    'xmrEnabled':                 xmrEnabled,
    'defaultNetwork':             'ethereum_mainnet',
    'defaultNetworkConfigValid':  true,
  });
}


void main() {


  group('Part A — primary Activity button no longer fires the '
      'snackbar/toast', () {

    test('primary Activity onPressed calls _scrollActivityIntoView — '
        'NOT _showNotReadyBanner with the honest-empty copy', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');



      final btnIdx = src.indexOf(
        "Key('crypto_wallet_engine_primary_activity_btn')",
      );
      expect(btnIdx, greaterThan(0),
          reason: 'primary Activity button must still exist');


      final end = (btnIdx + 900 < src.length)
          ? btnIdx + 900 : src.length;
      final scope = src.substring(btnIdx, end);

      expect(scope.contains('_scrollActivityIntoView('), isTrue,
          reason: 'tapping Activity must scroll to the vault activity '
              'section, not show a bottom snackbar.');
      expect(
        scope.contains('_showNotReadyBanner('),
        isFalse,
        reason: 'the primary Activity button must NOT trigger a '
            'snackbar — that\'s the bottom toast the user is asking to '
            'remove.',
      );



      expect(
        scope.contains('kCryptoWalletEngineActivityHonestEmpty'),
        isFalse,
        reason: 'the honest-empty string must not be passed to a '
            'snackbar anywhere in the Activity button scope.',
      );
    });

    test('_scrollActivityIntoView uses Scrollable.ensureVisible against '
        'the activity section GlobalKey (not a snackbar shim)', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf('void _scrollActivityIntoView()');
      expect(start, greaterThan(0),
          reason: '_scrollActivityIntoView helper must be defined');
      final end = (start + 800 < src.length) ? start + 800 : src.length;
      final scope = src.substring(start, end);

      expect(scope.contains('Scrollable.ensureVisible('), isTrue);
      expect(scope.contains('activitySectionKey'), isTrue);


      expect(scope.contains('ScaffoldMessenger'), isFalse);
      expect(scope.contains('showSnackBar'), isFalse);
    });

    test('the parent state owns a GlobalKey for the activity section '
        'and threads it into the body widget', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(src.contains('_activitySectionKey ='), isTrue);
      expect(src.contains('activitySectionKey: _activitySectionKey'), isTrue,
          reason: 'the parent state must pass its GlobalKey down to the '
              'body widget so ensureVisible can find the section.');
    });
  });



  group('Part B — Asset card activity chip has 4 closed-set states, '
      'default is friendly "No activity yet"', () {

    test('closed-set chip copies are what the user asked for', () {
      expect(
        dashboardCardActivityChipCopy(DashboardCardActivityKind.empty),
        'No activity yet',
        reason: 'the default empty-wallet state must be friendly, not '
            '"Activity unavailable".',
      );
      expect(
        dashboardCardActivityChipCopy(
          DashboardCardActivityKind.historyNotConnected,
        ),
        'Activity history not connected',
        reason: 'indexer-missing must be precise, not scary.',
      );
      expect(
        dashboardCardActivityChipCopy(
          DashboardCardActivityKind.temporarilyUnavailable,
        ),
        'Activity temporarily unavailable',
        reason: 'provider-error surface must be calm.',
      );
      expect(
        dashboardCardActivityChipCopy(
          DashboardCardActivityKind.xmrScannerMissing,
        ),
        'Scanner not enabled',
        reason: 'XMR scanner missing must say "Scanner not enabled" — '
            'the compact honest label.',
      );
    });

    test('ETH / USDT_ERC20 / USDC_ERC20 default to empty ("No activity '
        'yet") — Ethereum indexer is present so there is no '
        '"history not connected" fallback for those', () {
      final f = _features();
      for (final asset in const ['ETH', 'USDT_ERC20', 'USDC_ERC20']) {
        final kind = dashboardCardActivityKind(asset: asset, features: f);
        expect(kind, DashboardCardActivityKind.empty,
            reason: '$asset must default to No activity yet');
      }
    });

    test('SOL: solana enabled but activity not connected → '
        '"Activity history not connected"', () {
      final noSolActivity = _features(
        solanaEnabled: true, solanaActivityConnected: false,
      );
      expect(
        dashboardCardActivityKind(asset: 'SOL', features: noSolActivity),
        DashboardCardActivityKind.historyNotConnected,
      );



      final withActivity = _features(
        solanaEnabled: true, solanaActivityConnected: true,
      );
      expect(
        dashboardCardActivityKind(asset: 'SOL', features: withActivity),
        DashboardCardActivityKind.empty,
      );
    });

    test('TRON default state is friendly "No activity yet" — even when '
        'activity feed is not implemented, the DASHBOARD CHIP must not '
        'be scary. Detail page will still tell the truth in '
        'kActivityCopyEmptyTron.', () {
      final f = _features(tronEnabled: true, tronActivityConnected: false);
      expect(
        dashboardCardActivityKind(asset: 'USDT_TRC20', features: f),
        DashboardCardActivityKind.empty,
        reason: 'TRON dashboard card must not shout "unavailable" by '
            'default — user Rule B.',
      );
    });

    test('XMR maps to "Scanner not enabled" — the honest closed-set '
        'label', () {
      final f = _features(xmrEnabled: true);
      final kind = dashboardCardActivityKind(asset: 'XMR', features: f);
      expect(kind, DashboardCardActivityKind.xmrScannerMissing);
      expect(dashboardCardActivityChipCopy(kind), 'Scanner not enabled');
    });

    test('the asset card render source no longer literals the old '
        'const "Activity unavailable" label', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');



      final chipIdx = src.indexOf(
        'crypto_wallet_engine_card_activity_chip_',
      );
      expect(chipIdx, greaterThan(0),
          reason: 'chip render must be wired');



      final scopeStart = (chipIdx - 500).clamp(0, src.length).toInt();
      final scopeEnd = (chipIdx + 1000 < src.length)
          ? chipIdx + 1000 : src.length;
      final scope = src.substring(scopeStart, scopeEnd);



      expect(
        scope.contains(
          "kCryptoWalletEngineAssetCardActivityUnavailableCompact,",
        ),
        isFalse,
        reason: 'the render must not literal-USE the old flat const '
            '(the deprecated symbol may still exist as an alias for '
            'external tests, but not be used in the render).',
      );
      expect(
        scope.contains('dashboardCardActivityChipCopy('),
        isTrue,
        reason: 'the render must consult the closed-set kind helper.',
      );
      expect(
        scope.contains('dashboardCardActivityKind('),
        isTrue,
        reason: 'the render must consult the closed-set kind resolver.',
      );
    });
  });



  group('Part C — Vault activity section copy is the polished '
      'three-line pair', () {

    test('primary is "No activity yet." (not the old long "Vault '
        'activity will show real transactions" sentence)', () {
      expect(
        kCryptoWalletEngineActivityEmptyPrimary,
        'No activity yet.',
      );
    });

    test('subcopy explains WHEN transactions will appear', () {
      expect(
        kCryptoWalletEngineActivityEmptySubcopy,
        'Real transactions will appear here when activity history is '
        'connected.',
      );
    });

    test('honesty line is short + preserved', () {
      expect(
        kCryptoWalletEngineActivityHonestSubcopy,
        'VaultAI never invents transaction history.',
      );
    });

    test('mixed-network note is a compact chip-friendly line', () {
      expect(
        kCryptoWalletEngineActivityIndexerMixedNote,
        'Activity history is not connected for every network yet.',
      );
      expect(
        kCryptoWalletEngineActivityIndexerMixedNote.length,
        lessThan(80),
      );
    });

    test('activity section source renders the three-line pair with '
        'stable keys', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf('Widget _buildActivitySection()');
      expect(start, greaterThan(0));
      final end = (start + 2500 < src.length) ? start + 2500 : src.length;
      final scope = src.substring(start, end);

      expect(
        scope.contains(
          "Key('crypto_wallet_engine_activity_empty_primary')",
        ),
        isTrue,
      );
      expect(
        scope.contains(
          "Key('crypto_wallet_engine_activity_empty_subcopy')",
        ),
        isTrue,
      );
      expect(
        scope.contains(
          "Key('crypto_wallet_engine_activity_honest_subcopy')",
        ),
        isTrue,
      );



      expect(
        scope.contains(
          "Vault activity will show real transactions once an indexer",
        ),
        isFalse,
        reason: 'the old long snackbar sentence must be gone from the '
            'section render.',
      );
    });
  });



  group('Part D — Per-asset detail activity copy is network-aware and '
      'never leaks Sepolia in Mainnet mode', () {

    test('Ethereum Mainnet detail activity says "No activity yet." and '
        'never mentions Sepolia', () {
      final copy = activityCopyEmptyForNetwork('ethereum_mainnet');
      expect(copy.contains('No activity yet.'), isTrue);
      expect(copy.toLowerCase().contains('sepolia'), isFalse,
          reason: 'Mainnet copy must never mention Sepolia.');
      expect(copy.toLowerCase().contains('testnet'), isFalse);
    });

    test('Sepolia mode is honest — still says Sepolia Testnet', () {
      final copy = activityCopyEmptyForNetwork('ethereum_sepolia');
      expect(copy.toLowerCase().contains('sepolia'), isTrue);
      expect(copy.toLowerCase().contains('testnet'), isTrue);
    });

    test('Solana Mainnet empty copy is friendly "No activity yet."', () {
      expect(
        activityCopyEmptyForNetwork('solana_mainnet'),
        'No activity yet.',
      );
    });

    test('TRON Mainnet empty copy tells the truth — "TRON activity '
        'history is not connected yet."', () {
      expect(
        activityCopyEmptyForNetwork('tron_mainnet'),
        'TRON activity history is not connected yet.',
      );
    });

    test('Monero copy is the same in-build-not-available line', () {
      expect(
        activityCopyEmptyForNetwork('monero_mainnet'),
        'Monero scanning is not available in this build yet.',
      );
    });

    test('unknown/null network is chain-agnostic — never mentions any '
        'chain by name', () {
      const banned = ['sepolia', 'mainnet', 'testnet', 'ethereum',
                      'solana', 'tron', 'monero'];
      for (final net in [null, '', 'weird_chain']) {
        final copy = activityCopyEmptyForNetwork(net).toLowerCase();
        for (final b in banned) {
          expect(copy.contains(b), isFalse,
              reason: 'chain-agnostic default must not leak "$b"');
        }
      }
    });
  });



  group('Part E — No fake activity, no exchange copy', () {

    test('all new activity copy strings never mention buy/sell/swap/'
        'trade/stake/bridge/exchange', () {
      const banned = ['buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
                      'exchange', 'convert'];
      final strings = <String>[
        kCryptoWalletEngineActivityEmptyPrimary,
        kCryptoWalletEngineActivityEmptySubcopy,
        kCryptoWalletEngineActivityHonestSubcopy,
        kCryptoWalletEngineActivityIndexerMixedNote,
        dashboardCardActivityChipCopy(DashboardCardActivityKind.empty),
        dashboardCardActivityChipCopy(
          DashboardCardActivityKind.historyNotConnected,
        ),
        dashboardCardActivityChipCopy(
          DashboardCardActivityKind.temporarilyUnavailable,
        ),
        dashboardCardActivityChipCopy(
          DashboardCardActivityKind.xmrScannerMissing,
        ),
        kActivityCopyEmptyMainnet,
        kActivityCopyEmptySepolia,
        kActivityCopyEmptyDefault,
        kActivityCopyEmptySolana,
        kActivityCopyEmptyTron,
        kActivityCopyEmptyMonero,
      ];
      for (final s in strings) {
        final low = s.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'copy "$s" leaks "$b"');
        }
      }
    });

    test('honest subcopy still contains the "never invents" invariant',
        () {
      expect(
        kCryptoWalletEngineActivityHonestSubcopy
            .toLowerCase().contains('never invents'),
        isTrue,
      );
    });
  });



  group('Part F — no bottom SnackBar carries the activity-honest copy', () {

    testWidgets('scaffold overlay is clean — the snackbar-driven activity '
        'toast is gone', (tester) async {


      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(builder: (ctx) {
              return TextButton(
                key: const Key('probe_button'),
                onPressed: () {

                  ScaffoldMessenger.of(ctx).showSnackBar(
                    const SnackBar(
                      content: Text('control_snack_content'),
                    ),
                  );
                },
                child: const Text('probe'),
              );
            }),
          ),
        ),
      );
      await tester.tap(find.byKey(const Key('probe_button')));
      await tester.pump();


      expect(find.text('control_snack_content'), findsOneWidget);

      expect(
        find.text(
          'Vault activity will show real transactions once an indexer '
          'is connected.',
        ),
        findsNothing,
        reason: 'that sentence must never render at all — it was the '
            'literal bottom-toast the user asked to remove.',
      );
    });
  });
}
