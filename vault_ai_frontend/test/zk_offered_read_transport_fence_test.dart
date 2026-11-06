import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_file_session.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_item_read_session.dart';

void main() {
  const token = 'synthetic-opaque-bearer';
  const pinMarker = 'synthetic-pin-marker';
  final headers = <String, String>{'Authorization': 'Bearer $token'};

  setUp(() {
    SessionTermination.instance.resetForTests();
    ZkPinFreeFileSession.instance.clear();
    ZkPinFreeItemReadSession.instance.clear();
    setApiClientDeviceId('synthetic-device');
    SessionTermination.instance.bindSession(token);
  });

  tearDown(() {
    ZkPinFreeFileSession.instance.clear();
    ZkPinFreeItemReadSession.instance.clear();
    SessionTermination.instance.resetForTests();
  });

  test('file list and download offers fence only their old read routes', () {
    ZkPinFreeFileSession.instance.bind(
      sessionToken: token,
      listOffered: true,
      downloadOffered: false,
    );
    void request(String path, {Object? body}) =>
        assertOfferedReadPinFreeRequest(
          Uri.parse('https://synthetic.example$path'),
          headers,
          body: body,
        );

    expect(
      () => request('/list-files', body: '{"pin":"$pinMarker"}'),
      throwsStateError,
    );
    expect(
      () => request(
        '/files/synthetic-id/related',
        body: <String, String>{'pin': pinMarker},
      ),
      throwsStateError,
    );
    // The server offered list only. The older download remains available
    // until a separate authenticated download offer exists.
    request('/download-file', body: '{"pin":"$pinMarker"}');
    request('/upload-file/abort', body: '{"pin":"$pinMarker"}');

    ZkPinFreeFileSession.instance.bind(
      sessionToken: token,
      listOffered: true,
      downloadOffered: true,
    );
    expect(
      () => request('/download-file', body: '{"pin":"$pinMarker"}'),
      throwsStateError,
    );
    expect(
      () => request('/download-file/', body: '{"pin":"$pinMarker"}'),
      throwsStateError,
    );
    expect(
      () => request('/download-file/manifest', body: '{"pin":"$pinMarker"}'),
      throwsStateError,
    );
    expect(() => request('/download-file?pin=$pinMarker'), throwsStateError);
    request('/download-file', body: '{}');
  });

  test('saved-item offer remains fenced after local lock', () {
    ZkPinFreeItemReadSession.instance.bind(sessionToken: token, offered: true);
    ZkPinFreeItemReadSession.instance.lock();
    for (final path in <String>['/list-secure-items', '/get-secure-item']) {
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://synthetic.example$path'),
          headers,
          body: jsonEncode(<String, String>{'pin': pinMarker}),
        ),
        throwsStateError,
      );
    }
    // A mutation still uses its older route while its own migration is
    // incomplete. This read offer does not change that authorization.
    assertOfferedReadPinFreeRequest(
      Uri.parse('https://synthetic.example/update-secure-item'),
      headers,
      body: jsonEncode(<String, String>{'pin': pinMarker}),
    );
  });

  test('a new bearer does not inherit the old bearer offer', () {
    ZkPinFreeFileSession.instance.bind(
      sessionToken: token,
      listOffered: true,
      downloadOffered: true,
    );
    SessionTermination.instance.bindSession('replacement-bearer');
    assertOfferedReadPinFreeRequest(
      Uri.parse('https://synthetic.example/download-file'),
      <String, String>{'Authorization': 'Bearer replacement-bearer'},
      body: '{"pin":"$pinMarker"}',
    );
  });

  test('actual API download cannot transmit a PIN after its offer', () async {
    ZkPinFreeFileSession.instance.bind(
      sessionToken: token,
      listOffered: true,
      downloadOffered: true,
    );
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await expectLater(
      client.downloadVaultFile(
        vaultName: 'synthetic-vault',
        fileId: 'synthetic-file',
        pin: pinMarker,
        authToken: token,
      ),
      throwsStateError,
    );
    await expectLater(
      client.getDownloadManifest(
        authToken: token,
        vaultName: 'synthetic-vault',
        pin: pinMarker,
        fileId: 'synthetic-file',
      ),
      throwsStateError,
    );
    expect(sent, isEmpty);
  });

  test(
    'old download remains available without an authenticated offer',
    () async {
      ZkPinFreeFileSession.instance.bind(
        sessionToken: token,
        listOffered: true,
        downloadOffered: false,
      );
      final sent = <http.Request>[];
      final client = VaultAIClient(
        baseUrl: 'https://synthetic.example',
        httpClient: MockClient((request) async {
          sent.add(request);
          return http.Response(
            '{"base64_data":"","file_name":"synthetic"}',
            200,
          );
        }),
      );
      final result = await client.downloadVaultFile(
        vaultName: 'synthetic-vault',
        fileId: 'synthetic-file',
        pin: pinMarker,
        authToken: token,
      );
      expect(result['file_name'], 'synthetic');
      expect(sent, hasLength(1));
      expect(sent.single.url.path, '/download-file');
    },
  );
}
