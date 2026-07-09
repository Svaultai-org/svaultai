

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';

class _StubVaultAIClient extends VaultAIClient {
  _StubVaultAIClient() : super(baseUrl: 'http://localhost:0');
}

void main() {
  group('CryptoWalletEngineSendPanel — slice 7 chat prefill', () {
    final stubClient = _StubVaultAIClient();

    Future<void> _pumpPanel(
      WidgetTester tester, {
      String? prefilledDestination,
      String? prefilledAmount,
      String asset = 'ETH',
    }) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineSendPanel(
              authToken: 'tok',
              fromAddress: '0x${'11' * 20}',
              client: stubClient,
              decryptForVault: (ct) async => 'x' * 64,
              isVaultKeyAvailable: () => true,
              asset: asset,
              prefilledDestination: prefilledDestination,
              prefilledAmount: prefilledAmount,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('P1: prefilledDestination seeds the destination field',
        (tester) async {
      const dest = '0xabababababababababababababababababababab';
      await _pumpPanel(tester, prefilledDestination: dest);
      
      
      final tf = find.byType(TextField);
      expect(tf, findsAtLeast(1));
      
      bool foundDest = false;
      for (final el in tf.evaluate()) {
        final w = el.widget as TextField;
        if (w.controller?.text == dest) foundDest = true;
      }
      expect(foundDest, isTrue,
          reason: 'Destination field must be seeded with the prefill');
    });

    testWidgets('P2: prefilledAmount seeds the amount field',
        (tester) async {
      await _pumpPanel(tester, prefilledAmount: '0.07');
      final tf = find.byType(TextField);
      bool foundAmount = false;
      for (final el in tf.evaluate()) {
        final w = el.widget as TextField;
        if (w.controller?.text == '0.07') foundAmount = true;
      }
      expect(foundAmount, isTrue,
          reason: 'Amount field must be seeded with the prefill');
    });

    testWidgets('P3: no-prefill mount leaves both fields empty',
        (tester) async {
      await _pumpPanel(tester);
      final tf = find.byType(TextField);
      for (final el in tf.evaluate()) {
        final w = el.widget as TextField;
        expect(
          w.controller?.text ?? '', isEmpty,
          reason: 'Without prefill, every text field starts empty',
        );
      }
    });

    testWidgets(
        'P4: prefilled mount still starts in FORM stage with the Review '
        'button — never the broadcast button', (tester) async {
      const dest = '0xcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd';
      await _pumpPanel(
        tester,
        prefilledDestination: dest,
        prefilledAmount: '0.5',
      );
      
      expect(find.text(kEthSendReviewButtonLabel), findsOneWidget);
      
      
      expect(find.text(kEthSendPinDialogConfirmLabel), findsNothing);
      
      
      expect(find.text(kEthSendSuccessHeading), findsNothing);
    });
  });
}
