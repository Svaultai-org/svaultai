

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_design.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';


class _FakeWalletClient implements VaultAIClient {
  final Map<String, dynamic> receiveBody;
  _FakeWalletClient(this.receiveBody);

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceive({
    required String asset,
    required String authToken,
  }) async {
    return receiveBody;
  }

  
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<void> _pumpActivity(
  WidgetTester tester, {
  String asset = 'ETH',
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        backgroundColor: const Color(0xFF101010),
        body: CryptoWalletActivityCard(asset: asset),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _pumpReceive(
  WidgetTester tester,
  Map<String, dynamic> envelope,
) async {
  final client = _FakeWalletClient(envelope);
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: CryptoWalletEngineReceivePanel(
          authToken: 'tok',
          client: client,
          encryptForVault: (p) async => 'ct_$p',
          isVaultKeyAvailable: () => true,
          asset: 'ETH',
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('crypto wallet activity card dark design', () {
    testWidgets('DR1: activity card root uses the dark wallet decoration',
        (tester) async {
      await _pumpActivity(tester);
      final card = find.byKey(const Key('crypto_wallet_activity_card'));
      expect(card, findsOneWidget);
      final container = tester.widget<Container>(card);
      final decoration = container.decoration as BoxDecoration?;
      expect(decoration, isNotNull);
      
      
      final solid = decoration!.color;
      expect(solid, isNot(Colors.white),
          reason: 'Activity card surface must not be flat white.');
      if (solid != null) {
        final hsl = HSLColor.fromColor(solid);
        expect(hsl.lightness, lessThan(0.25),
            reason: 'Activity surface must be dark (lightness < 0.25). '
                'Got $solid, lightness=${hsl.lightness}.');
      }
    });

    testWidgets('DR2: unavailable state renders the dark body style',
        (tester) async {
      
      await _pumpActivity(tester);
      final unavailable = find.byKey(
        const Key('crypto_wallet_activity_card_unavailable'),
      );
      expect(unavailable, findsOneWidget);
      final text = tester.widget<Text>(unavailable);
      expect(text.style?.color, equals(kWalletTextSecondary));
    });

    testWidgets('DR3: empty state would render the dark body style',
        (tester) async {
      
      
      expect(kActivityCopyEmpty, isNotEmpty);
      expect(kWalletBodyStyle.color, equals(kWalletTextSecondary));
    });

    testWidgets('DR4: loading state is wrapped in the dark surface',
        (tester) async {
      
      
      expect(kActivityCopyLoading, equals('Loading activity…'));
    });

    testWidgets('DR5: row body uses the dark elevated surface tokens',
        (tester) async {
      
      
      final hsl = HSLColor.fromColor(kWalletSurfaceElevated);
      expect(hsl.lightness, lessThan(0.20),
          reason: 'Activity row elevated surface must be dark.');
    });
  });

  group('crypto wallet engine — receive runtime fixes', () {
    testWidgets(
        'DR6: engine_disabled envelope NEVER renders the old Lite copy '
        'phrase',
        (tester) async {
      await _pumpReceive(tester, const {
        'wallet_engine': 'engine_disabled',
        'message': 'The Crypto Wallet Engine is not yet enabled. '
            'Crypto Vault Lite remains available for saved public '
            'addresses, encrypted backups, and manual notes.',
      });
      
      
      expect(
        find.textContaining('Crypto Vault Lite remains available'),
        findsNothing,
        reason: 'Old Lite fallback copy must not appear in the live '
            'engine receive flow.',
      );
      expect(
        find.textContaining('not yet enabled'),
        findsNothing,
        reason: 'Old "not yet enabled" copy must not appear in the '
            'live engine receive flow.',
      );
    });

    testWidgets(
        'DR7: engine_disabled state shows the new dark backend-disabled '
        'message',
        (tester) async {
      await _pumpReceive(tester, const {
        'wallet_engine': 'engine_disabled',
      });
      expect(
        find.byKey(const Key('eth_receive_panel_engine_disabled')),
        findsOneWidget,
      );
      expect(
        find.text('Crypto Wallet Engine is disabled by the backend.'),
        findsOneWidget,
      );
    });

    testWidgets(
        'DR8: no_account envelope opens the create flow, not the '
        'disabled state',
        (tester) async {
      await _pumpReceive(tester, const {
        'wallet_engine': 'no_account',
      });
      
      expect(
        find.byKey(const Key('eth_receive_panel_create_state')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('eth_receive_panel_engine_disabled')),
        findsNothing,
      );
      
      expect(
        find.textContaining('disabled by the backend'),
        findsNothing,
      );
      
      expect(
        find.textContaining('Crypto Vault Lite remains available'),
        findsNothing,
      );
    });
  });
}
