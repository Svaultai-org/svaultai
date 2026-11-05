import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;

void main() {
  const token = 'synthetic-private-session';
  const rawPin = '123456';

  setUp(() {
    st.SessionTermination.instance.bindSession(token);
    PrivateZkPinTransportSession.clear();
  });

  tearDown(PrivateZkPinTransportSession.clear);

  test(
      'private session permits read-only wallet metadata and ZK stats, '
      'but blocks legacy PIN actions before the network', () async {
    PrivateZkPinTransportSession.bind(token);
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        if (request.url.path ==
            '/crypto/wallet/network/ethereum_mainnet/ETH/receive') {
          return http.Response(
            jsonEncode({'wallet_engine': 'no_account'}),
            200,
          );
        }
        if (request.url.path == '/vault-stats/zk') {
          return http.Response(jsonEncode({'used_bytes': 0}), 200);
        }
        return http.Response('{}', 404);
      }),
    );

    await client.getCryptoWalletReceiveNetwork(
      network: 'ethereum_mainnet',
      asset: 'ETH',
      authToken: token,
    );
    await client.getZkVaultStats(authToken: token);
    expect(requests.map((r) => r.url.path), [
      '/crypto/wallet/network/ethereum_mainnet/ETH/receive',
      '/vault-stats/zk',
    ]);
    for (final request in requests) {
      expect(request.body, isNot(contains(rawPin)));
      expect(request.body, isNot(contains('"pin"')));
    }

    final legacyPinActions = <Future<Object?> Function()>[
      () => client.analyzePasswords(
            authToken: token,
            vaultName: 'Synthetic vault',
            pin: rawPin,
          ),
      () => client.rotateVaultKdf(
            authToken: token,
            vaultName: 'Synthetic vault',
            pin: rawPin,
          ),
      // Deliberately omit the handle: the transport guard is a second line
      // of defense even if a caller forgets the related-files UI guard.
      () => client.fetchRelatedFiles(
            fileId: 'synthetic-file',
            pin: rawPin,
            authToken: token,
          ),
    ];
    for (final action in legacyPinActions) {
      await expectLater(action(), throwsStateError);
    }
    expect(requests, hasLength(2));
  }, skip: !kEnableZkPrivateOnlyUnlock);
}
