


import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_design.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_mainnet_receive_card.dart';


final _hexRe = RegExp(r'Color\(0x([0-9A-Fa-f]{8})\)');

int _brightness(int argb) {
  final r = (argb >> 16) & 0xff;
  final g = (argb >> 8) & 0xff;
  final b = argb & 0xff;

  return ((r * 299 + g * 587 + b * 114) ~/ 1000);
}


bool _looksLikeLightBackground(int argb) {
  return _brightness(argb) > 200;
}

Set<int> _extractHexColors(String src) {

  final scrubbed = src.split('\n').map((l) {
    final idx = l.indexOf('//');
    return idx >= 0 ? l.substring(0, idx) : l;
  }).join('\n');
  final out = <int>{};
  for (final m in _hexRe.allMatches(scrubbed)) {
    final hex = m.group(1)!;
    final v = int.parse(hex, radix: 16);
    out.add(v);
  }
  return out;
}


void main() {
  group('Part A — copy compactness', () {

    test('Mainnet ETH receive headline is a compact one-liner', () {
      expect(kEvmNetworkMainnetReceiveRealFundsHeadline.length, lessThan(80));
      expect(
        kEvmNetworkMainnetReceiveRealFundsHeadline.contains('security review'),
        isFalse,
      );
      expect(
        kEvmNetworkMainnetReceiveRealFundsHeadline.contains(
          'non-custodial wallet engine ships',
        ),
        isFalse,
      );
    });

    test('Mainnet send blocker copy is a short pill message', () {
      expect(kEvmNetworkMainnetSendBlockedCopy, 'Sending is not enabled yet.');
    });

    test('Mainnet token receive headline is a compact one-liner', () {
      expect(
        kEvmNetworkMainnetTokenReceiveRealFundsHeadline.length,
        lessThan(90),
      );
      expect(
        kEvmNetworkMainnetTokenReceiveRealFundsHeadline
            .contains('security review'),
        isFalse,
      );
    });

    test('Mainnet token send blocker copy is a short pill message', () {
      expect(kEvmNetworkMainnetTokenSendBlockedCopy,
          'Sending is not enabled yet.');
    });

    test('Shared address + gas notes are one-line notes, no paragraphs', () {
      expect(kEvmNetworkMainnetTokenSharedAddressNote.length, lessThan(60));
      expect(kEvmNetworkMainnetTokenGasNote.length, lessThan(60));
    });
  });


  group('Part B — dark theme, no white/yellow warning backgrounds', () {

    test('Mainnet receive card source uses walletDarkCard, no hex '
        'light BoxDecoration colors', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_receive_card.dart',
      ).readAsStringSync();
      expect(src.contains('walletDarkCard('), isTrue,
          reason: 'card must be styled by the dark design token');

      for (final argb in _extractHexColors(src)) {
        expect(
          _looksLikeLightBackground(argb), isFalse,
          reason: 'card uses light color 0x${argb.toRadixString(16)} — '
              'expected only dark accents',
        );
      }

      expect(src.contains('0xFFFFF5E5'), isFalse);
      expect(src.contains('0xFFFCEAEA'), isFalse);
      expect(src.contains('0xFFFFE9C7'), isFalse);
      expect(src.contains('0xFFF5F5F5'), isFalse);
    });

    test('Mainnet ERC20 receive card source uses walletDarkCard, no '
        'hex light BoxDecoration colors', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart',
      ).readAsStringSync();
      expect(src.contains('walletDarkCard('), isTrue);

      for (final argb in _extractHexColors(src)) {
        expect(
          _looksLikeLightBackground(argb), isFalse,
          reason: 'ERC20 card uses light color 0x${argb.toRadixString(16)}',
        );
      }

      expect(src.contains('0xFFFFF5E5'), isFalse);
      expect(src.contains('0xFFFCEAEA'), isFalse);
      expect(src.contains('0xFFFFFCEC'), isFalse);
    });

    testWidgets('Mainnet ETH receive card renders on the dark background',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          backgroundColor: kWalletBgBase,
          body: CryptoWalletEngineMainnetReceiveCard(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMainnetReceiveCardKey)),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('Mainnet USDT receive card renders on the dark background',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          backgroundColor: kWalletBgBase,
          body: CryptoWalletEngineMainnetErc20ReceiveCard(
            asset: kMainnetErc20AssetUsdt,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMainnetErc20ReceiveCardKey)),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });
  });


  group('Part C — no long scary warnings', () {

    test('ETH receive card source contains no "security review" phrase', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_receive_card.dart',
      ).readAsStringSync();
      expect(src.toLowerCase().contains('security review'), isFalse);
    });

    test('ERC20 receive card source contains no "security review" phrase',
        () {
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart',
      ).readAsStringSync();
      expect(src.toLowerCase().contains('security review'), isFalse);
    });

    test(
      'Mainnet copy constants source does not contain "security review"',
      () {
        final src = File(
          'lib/services/evm_networks.dart',
        ).readAsStringSync();

        final relevantLines = src
            .split('\n')
            .where((l) => l.trim().startsWith("'"))
            .join('\n');
        expect(
          relevantLines.toLowerCase().contains('security review'),
          isFalse,
        );
      },
    );

    test(
      'no "not connected" fallback string in mainnet card sources',
      () {
        for (final path in const [
          'lib/ui/crypto_wallet_engine_mainnet_receive_card.dart',
          'lib/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart',
        ]) {
          final src = File(path).readAsStringSync();
          expect(
            src.toLowerCase().contains('not connected'),
            isFalse,
            reason: '$path uses "not connected" fallback instead of a '
                'closed-set reason',
          );
        }
      },
    );
  });


  group('Part D — speed instrumentation is dev-only + no secrets', () {

    test('main.dart guards timing logs behind kDebugMode', () {
      final src = File('lib/main.dart').readAsStringSync();
      expect(
        src.contains('_logDevTiming('),
        isTrue,
        reason: 'main.dart should route timing through _logDevTiming',
      );
      expect(
        src.contains('if (!kDebugMode) return'),
        isTrue,
        reason: 'timing helper must be a no-op in release',
      );
    });

    test('timing log names never include address/tx/rpc/api/key/token',
        () {
      final src = File('lib/main.dart').readAsStringSync();

      final callRe = RegExp(
        r"_logDevTiming\(\s*'([^']+)'",
      );
      final labels = callRe.allMatches(src).map((m) => m.group(1)!).toList();
      expect(labels, isNotEmpty,
          reason: 'at least one timing label must be emitted');
      for (final label in labels) {
        final low = label.toLowerCase();
        for (final banned in const [
          'address', 'txhash', 'tx_hash', 'rpc', 'api_key', 'apikey',
          'token', 'secret', 'private', 'seed', 'mnemonic',
        ]) {
          expect(low.contains(banned), isFalse,
              reason: 'timing label "$label" contains banned "$banned"');
        }
      }
    });

    test(
      'refreshBilling wraps HTTP with a bounded timeout so the access '
      'gate cannot hang forever',
      () {
        final src = File('lib/main.dart').readAsStringSync();
        final start = src.indexOf('Future<void> refreshBilling');
        expect(start, greaterThan(0),
            reason: 'refreshBilling method must be present');

        final scope = src.substring(start, start + 3000);
        expect(scope.contains('.timeout('), isTrue,
            reason: 'refreshBilling must add a timeout to the billing call');
        expect(scope.contains('TimeoutException'), isTrue,
            reason: 'refreshBilling must throw TimeoutException on slow API');



        expect(scope.contains('Duration(seconds: 12)'), isTrue,
            reason: 'refreshBilling timeout must be 12 seconds — widened '
                'from 5s so cold-start DB queries do not falsely trip the '
                '"Subscription status is temporarily unavailable" banner.');
      },
    );

    test('billing-status banner copy is honest, compact, and '
        'non-blocking (no full-page timeout card)', () {
      final src = File('lib/main.dart').readAsStringSync();


      expect(
        src.contains(
          'Subscription status is temporarily unavailable.',
        ),
        isTrue,
        reason: 'error banner must state a specific reason for the '
            'subscription refresh failure',
      );

      expect(
        src.contains('_CryptoVaultAccessErrorCard'),
        isFalse,
        reason: 'the old full-page "Access check timed out" card must be '
            'removed — billing timeout must not block Crypto Vault',
      );
      expect(
        src.contains("Key('crypto_vault_page_card_error')"),
        isFalse,
        reason: 'the full-page timeout error card key must be gone',
      );
      expect(
        src.contains("Key('crypto_vault_page_card_loading')"),
        isFalse,
        reason: 'the full-page loading card key must be gone — the '
            'crypto vault shell must render instead of a blocking card',
      );

      expect(
        src.contains(
          'crypto_vault_access_error_retry_button',
        ),
        isTrue,
        reason: 'billing-status banner must still expose an explicit '
            'Retry action',
      );
      expect(
        src.contains('_CryptoVaultBillingStatusBanner'),
        isTrue,
        reason: 'a non-blocking billing status banner widget must exist',
      );
    });
  });


  group('Part E — mobile 360 px no overflow', () {

    testWidgets('Mainnet ETH receive card fits at 360 x 720',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          backgroundColor: kWalletBgBase,
          body: SingleChildScrollView(
            child: CryptoWalletEngineMainnetReceiveCard(),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('Mainnet USDT receive card fits at 360 x 720',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          backgroundColor: kWalletBgBase,
          body: SingleChildScrollView(
            child: CryptoWalletEngineMainnetErc20ReceiveCard(
              asset: kMainnetErc20AssetUsdt,
            ),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('Mainnet USDC receive card fits at 360 x 720',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          backgroundColor: kWalletBgBase,
          body: SingleChildScrollView(
            child: CryptoWalletEngineMainnetErc20ReceiveCard(
              asset: kMainnetErc20AssetUsdc,
            ),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });


  group('Part F — no exchange copy, no Lite UI', () {

    test('mainnet card sources never mention exchange verbs', () {
      const forbiddenWithSpaces = [
        ' buy ', ' sell ', ' swap ', ' trade ', ' stake ',
        ' bridge ', ' exchange ', ' market ',
      ];
      for (final path in const [
        'lib/ui/crypto_wallet_engine_mainnet_receive_card.dart',
        'lib/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart',
      ]) {
        final src = File(path).readAsStringSync();

        final strings = RegExp(r"'([^'\\]|\\.)*'").allMatches(src)
            .map((m) => m.group(0)!.toLowerCase())
            .toList();
        for (final s in strings) {
          for (final banned in forbiddenWithSpaces) {
            expect(' $s ', isNot(contains(banned)),
                reason: '$path literal $s contains forbidden verb $banned');
          }
        }
      }
    });

    test('mainnet card sources never reference the old Lite UI', () {
      for (final path in const [
        'lib/ui/crypto_wallet_engine_mainnet_receive_card.dart',
        'lib/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart',
      ]) {
        final src = File(path).readAsStringSync();
        expect(
          src.contains('crypto_vault_lite'),
          isFalse,
          reason: '$path must not import or reference Lite UI',
        );
      }
    });
  });
}
