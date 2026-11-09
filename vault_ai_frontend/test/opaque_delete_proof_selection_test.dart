import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/delete_vault_flow.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  setUp(ZkActiveMvk.clear);
  tearDown(ZkActiveMvk.clear);

  void unlockPrivateVault() => ZkActiveMvk.set(
        mvk: SecretKey(List<int>.filled(32, 11)),
        vaultId: 'synthetic-vault',
        vaultHandle: 'synthetic-handle',
      );

  test('active private key rejects PIN deletion before HTTP', () async {
    unlockPrivateVault();
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('', 204);
      }),
    );
    await expectLater(
      client.confirmDeleteVault(
        authToken: 'unsigned-session',
        requestToken: 'request',
        pin: 'synthetic-pin',
        confirmationPhrase: kDeleteVaultConfirmationPhrase,
      ),
      throwsStateError,
    );
    expect(sent, isEmpty);
    expect(
      () => assertOutboundPinFreeRequest(
        Uri.parse('https://synthetic.example/vault/delete/confirm'),
        const <String, String>{},
        body: '{"pin":"synthetic-pin"}',
      ),
      throwsStateError,
    );
  });

  test('active private key sends proof deletion without a PIN', () async {
    unlockPrivateVault();
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('', 204);
      }),
    );
    await client.confirmDeleteVault(
      authToken: 'unsigned-session',
      requestToken: 'request',
      zkProofToken: 'one-use-proof',
      confirmationPhrase: kDeleteVaultConfirmationPhrase,
    );
    expect(sent.single.url.path, '/vault/delete/confirm-proof');
    expect((jsonDecode(sent.single.body) as Map).keys.toSet(),
        {'request_token', 'zk_proof_token', 'confirmation_phrase'});
  });

  test('a PIN-shaped proof is rejected before HTTP', () async {
    unlockPrivateVault();
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('', 204);
      }),
    );
    await expectLater(
      client.confirmDeleteVault(
        authToken: 'unsigned-session',
        requestToken: 'request',
        zkProofToken: '123456',
        confirmationPhrase: kDeleteVaultConfirmationPhrase,
      ),
      throwsArgumentError,
    );
    expect(sent, isEmpty);
  });

  Future<List<http.Request>> runDialog(
    WidgetTester tester, {
    required bool privateVault,
    bool unlockOnRequest = false,
  }) async {
    if (privateVault) unlockPrivateVault();
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        if (request.url.path == '/vault/delete/status') {
          return http.Response(
            '{"requires_pin":true,"requires_opaque_verification":false}',
            200,
          );
        }
        if (request.url.path == '/vault/delete/request') {
          if (unlockOnRequest) unlockPrivateVault();
          return http.Response('{"request_token":"synthetic-request"}', 200);
        }
        return http.Response('', 204);
      }),
    );
    String? proofPin;
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: DeleteVaultFlow(
          client: client,
          authToken: 'unsigned-session',
          zkProofForPin: privateVault || unlockOnRequest
              ? (pin) async {
                  proofPin = pin;
                  return 'one-use-proof';
                }
              : null,
        ),
      ),
    ));
    await tester.enterText(
      find.byKey(const Key('delete_vault_phrase_field')),
      kDeleteVaultConfirmationPhrase,
    );
    await tester.enterText(
      find.byKey(const Key('delete_vault_pin_field')),
      '123456',
    );
    await tester.pump();
    await tester.tap(find.byKey(const Key('delete_vault_confirm_button')));
    await tester.pumpAndSettle();
    expect(proofPin, privateVault || unlockOnRequest ? '123456' : null);
    return sent;
  }

  testWidgets('stale delete status cannot select PIN for private vault',
      (tester) async {
    final sent = await runDialog(tester, privateVault: true);
    expect(sent.map((r) => r.url.path), [
      '/vault/delete/status',
      '/vault/delete/request',
      '/vault/delete/confirm-proof',
    ]);
    expect(sent.last.body, isNot(contains('"pin"')));
  });

  testWidgets('legacy-only vault cannot start raw-PIN deletion',
      (tester) async {
    final sent = await runDialog(tester, privateVault: false);
    expect(sent, isEmpty);
  });

  testWidgets('private unlock during delete request cannot fall back to PIN',
      (tester) async {
    final sent = await runDialog(
      tester,
      privateVault: false,
      unlockOnRequest: true,
    );
    expect(sent.last.url.path, '/vault/delete/confirm-proof');
    expect(sent.last.body, isNot(contains('"pin"')));
  });
}
