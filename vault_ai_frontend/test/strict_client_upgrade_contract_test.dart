import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/zk_auth_service.dart';

const _token = 'synthetic-session';

void main() {
  setUp(() {
    st.SessionTermination.instance.resetForTests();
    st.SessionTermination.instance.bindSession(_token);
  });
  tearDown(() => st.SessionTermination.instance.resetForTests());

  test('strict version header is sent only by complete private builds', () {
    expect(
      strictPinFreeClientHeaders(privateOnlyBuild: true, clientReady: true),
      {'X-SVaultAI-Strict-Pin-Free-Client': 'v1'},
    );
    for (final readiness in <(bool, bool)>[(false, true), (true, false)]) {
      expect(
        strictPinFreeClientHeaders(
          privateOnlyBuild: readiness.$1,
          clientReady: readiness.$2,
        ),
        isEmpty,
      );
    }
  });

  test('only coded 426 is classified as a required client update', () {
    const required =
        '{"detail":{"code":"client_upgrade_required","message":"ignored"}}';
    expect(isClientUpgradeRequiredResponse(426, required), isTrue);
    expect(isClientUpgradeRequiredResponse(409, required), isFalse);
    expect(
      isClientUpgradeRequiredResponse(426, '{"detail":"upgrade"}'),
      isFalse,
    );
    expect(isClientUpgradeRequiredResponse(426, 'not-json'), isFalse);
    expect(
      () => throwIfClientUpgradeRequired(426, required),
      throwsA(isA<ClientUpgradeRequiredException>()),
    );
    expect(
      const ClientUpgradeRequiredException().toString(),
      ClientUpgradeRequiredException.message,
    );
  });

  test(
    'coded 426 keeps the active session and discards server wording',
    () async {
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.invalid',
        httpClient: MockClient((request) async {
          expect(request.url.path, '/vault-stats/zk');
          return http.Response(
            '{"detail":{"code":"client_upgrade_required",'
            '"message":"untrusted backend wording"}}',
            426,
          );
        }),
      );
      await expectLater(
        client.getZkVaultStats(authToken: _token),
        throwsA(isA<ClientUpgradeRequiredException>()),
      );
      expect(st.SessionTermination.instance.hasBoundSession, isTrue);
      expect(st.SessionTermination.instance.isTerminated, isFalse);
    },
  );
}
