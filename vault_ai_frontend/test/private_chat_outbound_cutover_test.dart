import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/private_content_pin_guard.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  tearDown(ZkActiveMvk.clear);

  test('private chat key activated after route choice stops old wire calls',
      () {
    var wireCalls = 0;
    final mock = MockClient((request) async {
      wireCalls++;
      return http.Response('{}', 200);
    });
    final oldChat = Uri.parse('https://synthetic.example/chat');
    final oldStart = Uri.parse(
      'https://synthetic.example/vault-analysis/deep-answer',
    );
    final oldPoll = Uri.parse(
      'https://synthetic.example/vault-analysis/deep-answer/job-1/poll',
    );
    final body = jsonEncode({'pin': 'synthetic-pin'});
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 7)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'VLT-synthetic',
    );
    for (final uri in [oldChat, oldStart, oldPoll]) {
      expect(
        () => sendPinCheckedHttp('POST', uri, body: body, client: mock),
        throwsStateError,
      );
    }
    expect(wireCalls, 0);
    // The separate general endpoint and proof-only inspection route are not
    // server-side PIN-decryption routes.
    expect(
      () => assertOutboundPinFreeRequest(
        Uri.parse('https://synthetic.example/chat/zk/general'),
        null,
        body: jsonEncode({'message': 'Hello'}),
      ),
      returnsNormally,
    );
    expect(
      () => assertOutboundPinFreeRequest(
        Uri.parse(
          'https://synthetic.example/vault-analysis/deep-answer/job-1/debug',
        ),
        null,
        body: jsonEncode({'zk_proof_token': 'synthetic-proof'}),
      ),
      returnsNormally,
    );
    mock.close();
  }, skip: !kGuardZkPrivateContentPinRoutes);

  test('narrow local scan fence leaves unrelated legacy chat accessible', () {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 9)),
      vaultId: 'synthetic-vault',
      vaultHandle: 'VLT-synthetic',
    );
    expect(
      () => assertOutboundPinFreeRequest(
        Uri.parse('https://synthetic.example/vault-analysis/deep-answer'),
        null,
        body: jsonEncode({'pin': 'synthetic-pin'}),
      ),
      throwsStateError,
    );
    expect(
      () => assertOutboundPinFreeRequest(
        Uri.parse('https://synthetic.example/chat'),
        null,
        body: jsonEncode({'pin': 'synthetic-pin'}),
      ),
      returnsNormally,
    );
  }, skip: !kEnableZkLocalDeepScan || kGuardZkPrivateContentPinRoutes);
}
