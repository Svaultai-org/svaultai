

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/crypto_vault_locked_card.dart';


Future<void> _pump(
  WidgetTester tester, {
  Map<String, dynamic>? envelope,
  VoidCallback? onLearnMore,
  VoidCallback? onUpgradeRequired,
  Map<String, WidgetBuilder>? routes,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      
      
      routes: routes ?? {
        '/storage': (_) => const Scaffold(
          body: Text('storage_route_target'),
        ),
      },
      home: Scaffold(
        body: SingleChildScrollView(
          child: CryptoVaultLockedCard(
            envelope: envelope,
            onLearnMore: onLearnMore,
            onUpgradeRequired: onUpgradeRequired,
          ),
        ),
      ),
    ),
  );
}

const _kForbiddenStrings = <String>[
  
  'you can send',
  'you can receive',
  'you can buy',
  'you can sell',
  'you can trade',
  'you can swap',
  'you can exchange',
  'send now',
  
  'guaranteed',
  'profit',
  'high return',
  'investment return',
  'make money',
  'double your',
  'triple your',
  '10x',
  '100x',
  'to the moon',
  
  'we are an exchange',
  'vaultai is an exchange',
  'we sell crypto',
  'vaultai sells',
  'we trade',
  'vaultai is a broker',
];

void _assertNoForbiddenStrings(WidgetTester tester) {
  
  
  final allTexts = tester
      .widgetList(find.byType(Text))
      .whereType<Text>()
      .map((t) => (t.data ?? '').toLowerCase())
      .toList();
  for (final body in allTexts) {
    for (final needle in _kForbiddenStrings) {
      expect(
        body.contains(needle),
        isFalse,
        reason:
            'crypto vault card text must NEVER contain "$needle"; '
            'found in: "$body"',
      );
    }
  }
}


void main() {
  group('CryptoVaultLockedCard — default operator strings', () {
    testWidgets('title is Crypto Vault', (tester) async {
      await _pump(tester);
      expect(find.text('Crypto Vault'), findsOneWidget);
      expect(
        find.byKey(const Key('crypto_vault_title')), findsOneWidget,
      );
    });

    testWidgets('status reads "Available with upgrade"',
        (tester) async {
      
      
      await _pump(tester);
      expect(find.text('Available with upgrade'), findsOneWidget);
      expect(find.text('Coming soon for upgraded users'), findsNothing);
    });

    testWidgets('body lists the operator-pinned storage items',
        (tester) async {
      await _pump(tester);
      final body = tester
          .widget<Text>(find.byKey(const Key('crypto_vault_body')))
          .data!;
      for (final fragment in [
        'Save wallet addresses',
        'crypto notes',
        'seed phrases',
        'private keys',
        'transaction records',
        'receive QR codes',
        'Send features will come later',
        'extra protection',
      ]) {
        expect(body, contains(fragment),
          reason: 'body must contain "$fragment"');
      }
      
      expect(body, isNot(contains('Coming soon')));
      expect(
        body,
        isNot(contains('Receive and send features will come later')),
      );
    });

    testWidgets('lock icon is rendered', (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_vault_lock_icon')),
        findsOneWidget,
      );
      expect(find.byIcon(Icons.lock_outline), findsOneWidget);
    });

    testWidgets('exactly two operator-pinned buttons exist',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_vault_learn_more_button')),
        findsOneWidget,
      );
      expect(
        find.byKey(
          const Key('crypto_vault_upgrade_required_button'),
        ),
        findsOneWidget,
      );
      expect(find.text('Learn more'), findsOneWidget);
      expect(find.text('Upgrade required'), findsOneWidget);
    });
  });


  group('CryptoVaultLockedCard — backend envelope render', () {
    testWidgets('renders envelope title/status/body when provided',
        (tester) async {
      
      
      await _pump(tester, envelope: const {
        'type':   kCryptoVaultLockedType,
        'title':  'Crypto Vault',
        'status': 'Available with upgrade',
        'body':   'Save wallet addresses, crypto notes, seed '
            'phrases, private keys, transaction records, and '
            'receive QR codes securely. Send features will come '
            'later with extra protection.',
      });
      expect(find.text('Crypto Vault'), findsOneWidget);
      expect(find.text('Available with upgrade'), findsOneWidget);
      final body = tester
          .widget<Text>(find.byKey(const Key('crypto_vault_body')))
          .data!;
      expect(body, contains('wallet addresses'));
      expect(body, contains('receive QR codes'));
    });

    testWidgets('falls back to defaults when envelope key missing',
        (tester) async {
      await _pump(tester, envelope: const {
        'type':   kCryptoVaultLockedType,
        
      });
      expect(find.text(kCryptoVaultDefaultTitle),  findsOneWidget);
      expect(find.text(kCryptoVaultDefaultStatus), findsOneWidget);
    });

    testWidgets('falls back when envelope value is empty string',
        (tester) async {
      await _pump(tester, envelope: const {
        'title':  '',
        'status': '   ',
        'body':   '',
      });
      expect(find.text(kCryptoVaultDefaultTitle),  findsOneWidget);
      expect(find.text(kCryptoVaultDefaultStatus), findsOneWidget);
    });
  });


  group('Learn more', () {
    testWidgets('tapping "Learn more" opens the modal with pinned copy',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_vault_learn_more_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_vault_learn_more_dialog')),
        findsOneWidget,
      );
      
      final bodyFinder = find.byKey(
        const Key('crypto_vault_learn_more_dialog_body'),
      );
      expect(bodyFinder, findsOneWidget);
      final body = tester.widget<Text>(bodyFinder).data!;
      for (final fragment in [
        
        
        'Crypto Vault is available for upgraded users',
        'wallet addresses',
        'seed phrases',
        'private keys',
        'crypto notes',
        'transaction records',
        'receive QR codes',
        'Send features will come later',
        'extra protection',
      ]) {
        expect(body, contains(fragment));
      }
      
      expect(body, isNot(contains('upcoming upgraded feature')));
      expect(
        body,
        isNot(contains('Receive and send features will come later')),
      );
    });

    testWidgets('modal Close button dismisses the dialog',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_vault_learn_more_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_vault_learn_more_dialog')),
        findsOneWidget,
      );
      await tester.tap(find.byKey(
        const Key('crypto_vault_learn_more_dialog_close'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_vault_learn_more_dialog')),
        findsNothing,
      );
    });

    testWidgets('onLearnMore override pre-empts the default modal',
        (tester) async {
      var calls = 0;
      await _pump(
        tester,
        onLearnMore: () { calls++; },
      );
      await tester.tap(find.byKey(
        const Key('crypto_vault_learn_more_button'),
      ));
      await tester.pumpAndSettle();
      expect(calls, 1);
      
      expect(
        find.byKey(const Key('crypto_vault_learn_more_dialog')),
        findsNothing,
      );
    });
  });


  group('Upgrade required', () {
    testWidgets(
      'tapping "Upgrade required" pushes /storage (subscription flow)',
      (tester) async {
        await _pump(tester, routes: {
          '/storage': (_) => const Scaffold(
            key: Key('storage_route_target_scaffold'),
            body: Text('storage_route_target'),
          ),
        });
        await tester.tap(find.byKey(
          const Key('crypto_vault_upgrade_required_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key('storage_route_target_scaffold')),
          findsOneWidget,
        );
      },
    );

    testWidgets('onUpgradeRequired override pre-empts the navigation',
        (tester) async {
      var calls = 0;
      await _pump(
        tester,
        onUpgradeRequired: () { calls++; },
      );
      await tester.tap(find.byKey(
        const Key('crypto_vault_upgrade_required_button'),
      ));
      await tester.pumpAndSettle();
      expect(calls, 1);
    });

    testWidgets(
      'route constants pin /storage + autoOpenPicker:true',
      (tester) async {
        expect(kCryptoUpgradeRoute, '/storage');
        expect(
          kCryptoUpgradeRouteArgs,
          containsPair('autoOpenPicker', true),
        );
      },
    );
  });


  group('Anti-claim guardrails', () {
    testWidgets('default card has no forbidden claim strings',
        (tester) async {
      await _pump(tester);
      _assertNoForbiddenStrings(tester);
    });

    testWidgets('Learn-more modal has no forbidden claim strings',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_vault_learn_more_button'),
      ));
      await tester.pumpAndSettle();
      _assertNoForbiddenStrings(tester);
    });

    test('module source carries no send/receive/wallet UI strings',
        () async {
      final src = await File(
        'lib/ui/crypto_vault_locked_card.dart',
      ).readAsString();
      const forbidden = <String>[
        
        "'Send'",
        "'Receive'",
        "'Send crypto'",
        "'Receive crypto'",
        "'Create wallet'",
        "'New wallet'",
        "'Buy'",
        "'Sell'",
        "'Trade'",
        "'Swap'",
        "'Exchange'",
        
        'TransactionScreen',
        'SendCryptoScreen',
        'ReceiveCryptoScreen',
        'WalletScreen',
        'BroadcastScreen',
        
        "import 'package:web3",
        "import 'package:bitcoin",
        "import 'package:eth_",
        "import 'package:solana",
        "import 'package:ethers",
      ];
      for (final needle in forbidden) {
        expect(
          src.contains(needle),
          isFalse,
          reason:
              'crypto_vault_locked_card.dart must NEVER carry '
              '"$needle"',
        );
      }
    });
  });


  group('Settings dashboard wiring', () {
    test('main.dart imports + mounts CryptoVaultLockedCard',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(
        src,
        contains("import 'ui/crypto_vault_locked_card.dart'"),
        reason: 'main.dart must import the locked card module',
      );
      expect(
        src,
        contains('CryptoVaultLockedCard'),
        reason:
            'main.dart must mount CryptoVaultLockedCard in the '
            'Settings dashboard so users see the locked card '
            'without opening a chat envelope',
      );
    });
  });
}
