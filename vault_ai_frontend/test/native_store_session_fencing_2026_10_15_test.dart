import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;

const _old = 'synthetic-old-native-session';
const _new = 'synthetic-replacement-native-session';
final _termination = st.SessionTermination.instance;

typedef _StoreCall = Future<Map<String, dynamic>> Function(VaultAIClient client);

void main() {
  setUp(_termination.resetForTests);
  tearDown(_termination.resetForTests);

  final calls = <String, _StoreCall>{
    'Apple verification': (client) => client.verifyAppleStoragePurchase(
          authToken: _old,
          signedTransaction: 'synthetic-receipt-never-a-purchase',
        ),
    'Google billing state': (client) =>
        client.getGooglePlayBillingMe(authToken: _old),
  };

  for (final entry in calls.entries) {
    for (final status in [200, 401]) {
      test('${entry.key} delayed $status cannot affect a replacement login',
          () async {
        final entered = Completer<void>();
        final response = Completer<http.Response>();
        final client = VaultAIClient(
          baseUrl: 'https://example.invalid',
          httpClient: MockClient((request) async {
            entered.complete();
            return response.future;
          }),
        );
        _termination.bindSession(_old);
        final pending = entry.value(client);
        await entered.future;
        _termination.bindSession(_new);
        response.complete(http.Response(
          status == 200
              ? '{"verified":true}'
              : '{"detail":{"code":"session_superseded"}}',
          status,
        ));
        await expectLater(pending, throwsA(isA<StaleSessionResponseException>()));
        expect(_termination.isTerminated, isFalse);
        expect(
          _termination.isCurrentRequest(_termination.captureRequest(_new)),
          isTrue,
        );
      });
    }

    test('${entry.key} retains current coded termination classification',
        () async {
      _termination.bindSession(_old);
      final client = VaultAIClient(
        baseUrl: 'https://example.invalid',
        httpClient: MockClient((_) async => http.Response(
              '{"detail":{"code":"session_superseded"}}',
              401,
            )),
      );
      await expectLater(
        entry.value(client),
        throwsA(isA<SessionTerminatedException>().having(
          (error) => error.code,
          'code',
          st.SessionTerminationCode.superseded,
        )),
      );
      expect(_termination.isTerminated, isTrue);
    });
  }
}
