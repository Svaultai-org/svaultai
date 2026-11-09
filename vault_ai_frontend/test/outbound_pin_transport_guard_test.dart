import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/inheritance_credentials.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/zk_pin_free_file_session.dart';

void main() {
  const token = 'synthetic-outbound-opaque-session';
  const sentinelPin = '7319462085';
  final origin = Uri.parse('https://synthetic.invalid');

  setUp(() {
    st.SessionTermination.instance.bindSession(token);
    PrivateZkPinTransportSession.clear();
    ZkPinFreeFileSession.instance.clear();
    PrivateZkPinTransportSession.bind(token);
  });

  tearDown(() {
    PrivateZkPinTransportSession.clear();
    ZkPinFreeFileSession.instance.clear();
  });

  test('a signed file offer rejects old PIN transport in a normal build', () {
    PrivateZkPinTransportSession.clear();
    ZkPinFreeFileSession.instance.bind(
      sessionToken: token,
      listOffered: true,
      downloadOffered: true,
    );
    final headers = <String, String>{'Authorization': 'Bearer $token'};
    expect(
      () => assertOutboundPinFreeRequest(
        origin.resolve('/list-files'),
        headers,
        body: jsonEncode({'pin': sentinelPin}),
      ),
      throwsStateError,
    );
    expect(
      () => assertOutboundPinFreeRequest(
        origin.resolve('/vault/files/list'),
        headers,
        body: '{}',
      ),
      returnsNormally,
    );
  });

  test(
    'ordinary client and streamed chat block a PIN before send',
    () async {
      expect(PrivateZkPinTransportSession.active, isTrue);
      final sent = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: '$origin',
        httpClient: MockClient((request) async {
          sent.add(request);
          return http.Response(jsonEncode({'used_bytes': 0}), 200);
        }),
      );

      await client.getZkVaultStats(authToken: token);
      await expectLater(
        client.analyzePasswords(
          authToken: token,
          vaultName: 'Synthetic vault',
          pin: sentinelPin,
        ),
        throwsStateError,
      );
      await expectLater(
        client
            .chatStream(
              encryptedMessage: 'synthetic-encrypted-message',
              vaultName: 'Synthetic vault',
              pin: sentinelPin,
              authToken: token,
            )
            .toList(),
        throwsStateError,
      );
      expect(sent.map((request) => request.url.path), ['/vault-stats/zk']);
      expect(sent.single.body, isNot(contains(sentinelPin)));
    },
    skip: !kEnableZkPrivateOnlyUnlock,
  );

  test(
    'multipart direct sends inspect fields and permit file bytes',
    () async {
      expect(PrivateZkPinTransportSession.active, isTrue);
      final sent = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: '$origin',
        httpClient: MockClient((request) async {
          sent.add(request);
          return http.Response('{}', 200);
        }),
      );

      await expectLater(
        client.nameVaultFile(
          vaultName: 'Synthetic vault',
          fileId: 'synthetic-file',
          savedName: 'Synthetic file',
          pin: sentinelPin,
          authToken: token,
        ),
        throwsStateError,
      );
      expect(sent, isEmpty);

      // A file can legitimately contain the same digits as a PIN. The guard
      // examines protocol fields, not user file bytes.
      await client.uploadChunk(
        authToken: token,
        fileId: 'synthetic-file',
        chunkIndex: 0,
        uploadToken: 'synthetic-upload-token',
        chunkFrameBytes: Uint8List.fromList(utf8.encode(sentinelPin)),
      );
      expect(sent, hasLength(1));
      expect(sent.single.url.path, '/upload-file/chunk');
    },
    skip: !kEnableZkPrivateOnlyUnlock,
  );

  test(
    'query, header, nested JSON, form and unknown stream fail closed',
    () {
      expect(PrivateZkPinTransportSession.active, isTrue);
      expect(
        () => assertOutboundPinFreeRequest(
          origin.replace(queryParameters: {'pin': sentinelPin}),
          const {},
        ),
        throwsStateError,
      );
      expect(
        () => assertOutboundPinFreeRequest(origin, const {
          'X-Vault-Pin': sentinelPin,
        }),
        throwsStateError,
      );
      expect(
        () => assertOutboundPinFreeRequest(
          origin,
          const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'nested': {'current_pin': sentinelPin},
          }),
        ),
        throwsStateError,
      );
      expect(
        () => assertOutboundPinFreeRequest(
            origin,
            const {
              'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: utf8.encode('vault_pin=$sentinelPin')),
        throwsStateError,
      );
      expect(
        () => assertOutboundPinFreeRequest(
          origin,
          const {'Content-Type': 'application/octet-stream'},
          body: utf8.encode(jsonEncode({'pin': sentinelPin})),
        ),
        throwsStateError,
      );
      expect(
        () => assertOutboundPinFreeRequest(
          origin,
          const {},
          body: utf8.encode(jsonEncode({'nested': {'vault_pin': sentinelPin}})),
        ),
        throwsStateError,
      );
      expect(
        () => assertOutboundPinFreeRequest(
          origin,
          const {},
          body: jsonEncode({'prompt': '{"pin":"example JSON field"}'}),
        ),
        returnsNormally,
      );
      expect(
        () => assertOutboundPinFreeBaseRequest(
          http.StreamedRequest('POST', origin),
        ),
        throwsStateError,
      );
      final multipart = http.MultipartRequest('POST', origin)
        ..fields['metadata'] = jsonEncode({'pin': sentinelPin});
      expect(
        () => assertOutboundPinFreeBaseRequest(multipart),
        throwsStateError,
      );
    },
    skip: !kEnableZkPrivateOnlyUnlock,
  );

  test(
    'locally encrypted inheritance package is allowed',
    () async {
      expect(PrivateZkPinTransportSession.active, isTrue);
      final beneficiary = await X25519().newKeyPair();
      final publicKey = await beneficiary.extractPublicKey();
      final encrypted = await encryptInheritanceCredentials(
        username: 'Synthetic vault',
        pin: sentinelPin,
        beneficiaryPkVaultPublic: Uint8List.fromList(publicKey.bytes),
      );
      final wire = jsonEncode(encrypted.toRequestBody(beneficiaryLinkId: 1));
      expect(wire, isNot(contains(sentinelPin)));
      expect(
        () => assertOutboundPinFreeRequest(
            origin,
            const {
              'Content-Type': 'application/json',
            },
            body: wire),
        returnsNormally,
      );
    },
    skip: !kEnableZkPrivateOnlyUnlock,
  );

  test(
    'direct API requests use the checked transport',
    () async {
      final sent = <http.Request>[];
      final client = MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      });
      final uri = origin.resolve('/vault/ciphertext/beneficiary-links');
      final headers = <String, String>{'Content-Type': 'application/json'};
      await sendPinCheckedHttp('GET', uri, headers: headers, client: client);
      await sendPinCheckedHttp('POST', uri,
          headers: headers,
          body: jsonEncode({'ciphertext': 'synthetic'}),
          client: client);
      await sendPinCheckedHttp('PUT', uri,
          headers: headers,
          body: jsonEncode({'ciphertext': 'synthetic'}),
          client: client);
      expect(sent.map((request) => request.method), ['GET', 'POST', 'PUT']);
      expect(
          sent.every((request) => !request.body.contains(sentinelPin)), isTrue);
    },
  );

  test(
    'strict direct API request rejects a PIN before transport',
    () async {
      final sent = <http.Request>[];
      final client = MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      });
      expect(
        () => sendPinCheckedHttp(
          'POST',
          origin.resolve('/vault/ciphertext/beneficiary-links'),
          headers: <String, String>{'Content-Type': 'application/json'},
          body: jsonEncode({'pin': sentinelPin}),
          client: client,
        ),
        throwsStateError,
      );
      expect(sent, isEmpty);
    },
    skip: !kEnableZkPrivateOnlyUnlock,
  );

  test(
    'unbound legacy session retains its existing route',
    () {
      PrivateZkPinTransportSession.clear();
      expect(
        () => assertOutboundPinFreeRequest(
          origin.resolve('/legacy-action'),
          const {'Content-Type': 'application/json'},
          body: jsonEncode({'pin': sentinelPin}),
        ),
        returnsNormally,
      );
    },
    skip: kEnableZkPrivateOnlyUnlock,
  );
}
