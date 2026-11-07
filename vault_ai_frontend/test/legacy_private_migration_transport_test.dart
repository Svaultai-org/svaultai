import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/legacy_private_migration_transport.dart';

void main() {
  test('private stage sends only ciphertext with the bound device session',
      () async {
    final sent = <http.Request>[];
    final transport = LegacyPrivateMigrationTransport(
      backendBaseUrl: 'https://synthetic.invalid',
      sessionToken: 'synthetic-token',
      deviceId: 'synthetic-device',
      accessIsCurrent: () => true,
      client: MockClient((request) async {
        sent.add(request);
        return http.Response('{"ok":true}', 200);
      }),
    );
    try {
      await transport.request('GET',
          '/vault/legacy-ciphertext/migrate/item-staged/17');
      await transport.request('POST',
          '/vault/legacy-ciphertext/migrate/item-stage', {
        'item_id': 17,
        'payload_ciphertext': 'synthetic-ciphertext',
        'source_snapshot': 'synthetic-snapshot',
      });
      await transport.request('PUT', '/vault/file-v2/chunk', {
        'file_id': 'synthetic-file',
        'ciphertext': 'synthetic-chunk',
      });
      expect(sent.map((request) => request.method),
          <String>['GET', 'POST', 'PUT']);
      for (final request in sent) {
        expect(request.headers['Authorization'], 'Bearer synthetic-token');
        expect(request.headers['X-Device-Id'], 'synthetic-device');
        expect(request.body.contains('pin'), isFalse);
      }
      final body = jsonDecode(sent[1].body) as Map<String, dynamic>;
      expect(body['payload_ciphertext'], 'synthetic-ciphertext');
    } finally {
      transport.close();
    }
  });

  test('private stage rejects retirement, PIN fields, and changed access',
      () async {
    var current = true;
    var calls = 0;
    final transport = LegacyPrivateMigrationTransport(
      backendBaseUrl: 'https://synthetic.invalid',
      sessionToken: 'synthetic-token',
      deviceId: 'synthetic-device',
      accessIsCurrent: () => current,
      client: MockClient((request) async {
        calls++;
        current = false;
        return http.Response('{"ok":true}', 200);
      }),
    );
    try {
      await expectLater(
        transport.request('POST',
            '/vault/legacy-ciphertext/migrate/file-retire', {
          'file_id': 'synthetic-file',
        }),
        throwsStateError,
      );
      await expectLater(
        transport.request('POST',
            '/vault/legacy-ciphertext/migrate/item-stage', {
          'pin': '123456',
        }),
        throwsStateError,
      );
      expect(calls, 0);
      await expectLater(
        transport.request('GET',
            '/vault/legacy-ciphertext/migrate/item-staged/17'),
        throwsStateError,
      );
      expect(calls, 1);
    } finally {
      transport.close();
    }
  });

  test('required upgrade response is fixed and does not return server text',
      () async {
    final transport = LegacyPrivateMigrationTransport(
      backendBaseUrl: 'https://synthetic.invalid',
      sessionToken: 'synthetic-token',
      deviceId: 'synthetic-device',
      accessIsCurrent: () => true,
      client: MockClient((_) async => http.Response(
        '{"detail":{"code":"client_upgrade_required",'
        '"message":"untrusted details"}}', 426,
      )),
    );
    try {
      await expectLater(
        transport.request('GET',
            '/vault/legacy-ciphertext/migrate/item-staged/17'),
        throwsA(isA<ClientUpgradeRequiredException>()),
      );
    } finally {
      transport.close();
    }
  });
}
