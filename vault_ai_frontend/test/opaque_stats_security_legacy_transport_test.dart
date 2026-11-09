import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;

void main() {
  const pin = '7319462085';

  String token(List<int> wire) => base64Url.encode(wire).replaceAll('=', '');

  for (final wire in <List<int>>[
    <int>[3, 0, ...List<int>.filled(48, 7)],
    <int>[4, 1, 0, ...List<int>.filled(48, 7)],
  ]) {
    test('signed OPAQUE session uses PIN-free stats and blocks old security paths',
        () async {
      final sent = <http.Request>[];
      final authToken = token(wire);
      st.SessionTermination.instance.bindSession(authToken);
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.invalid',
        httpClient: MockClient((request) async {
          sent.add(request);
          return http.Response('{}', 200);
        }),
      );

      await client.getSessionVaultStats(authToken: authToken);
      expect(sent, hasLength(1));
      expect(sent.single.method, 'GET');
      expect(sent.single.url.path, '/vault-stats/session');
      expect(sent.single.body, isEmpty);
      await expectLater(
        client.analyzePasswords(
            authToken: authToken, vaultName: 'Synthetic vault', pin: pin),
        throwsStateError,
      );
      await expectLater(
        client.rotateVaultKdf(
            vaultName: 'Synthetic vault', pin: pin, authToken: authToken),
        throwsStateError,
      );
      expect(sent, hasLength(1));
    });
  }

  test('old session reads stats without sending a PIN during migration', () async {
    final authToken = token(List<int>.filled(48, 7));
    st.SessionTermination.instance.bindSession(authToken);
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );

    await client.getSessionVaultStats(authToken: authToken);
    expect(sent, hasLength(1));
    expect(sent.single.method, 'GET');
    expect(sent.single.url.path, '/vault-stats/session');
    expect(sent.single.body, isEmpty);
  });
}
