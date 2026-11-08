import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_file_session.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_item_read_session.dart';

void main() {
  const token = 'synthetic-opaque-bearer';
  String signedToken(int bits) => base64Url.encode(
        <int>[3, bits, ...List<int>.filled(48, 7)],
      ).replaceAll('=', '');
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
    expect(() => request('/download-file', body: '{}'), throwsStateError);
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

  test('offered old read routes never leave the device without a PIN field',
      () {
    final offeredToken = signedToken(7);
    final offeredHeaders = <String, String>{
      'Authorization': 'Bearer $offeredToken',
    };
    for (final path in <String>[
      '/list-secure-items', '/get-secure-item', '/list-login-names',
      '/get-login', '/login-count', '/manage/list-login-names',
      '/manage/list-secure-items', '/manage/logins-full',
      '/list-files', '/download-file', '/download-file/manifest',
    ]) {
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://synthetic.example$path'),
          offeredHeaders,
          body: const <String, String>{'vault_name': 'private name'},
        ),
        throwsStateError,
        reason: path,
      );
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://synthetic.example$path'),
          offeredHeaders,
          body: '{}',
        ),
        throwsStateError,
        reason: path,
      );
    }
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

  test('signed bearer retains read and create fences after local state clears',
      () {
    final offeredToken = signedToken(15);
    final offeredHeaders = <String, String>{
      'Authorization': 'Bearer $offeredToken',
    };
    ZkPinFreeFileSession.instance.clear();
    ZkPinFreeItemReadSession.instance.clear();
    for (final path in <String>[
      '/list-secure-items',
      '/list-files',
      '/download-file',
      '/upload-file',
      '/upload-file/init',
      '/upload-file/chunk',
      '/upload-file/finalize',
      '/upload-file/abort',
      '/upload-file/finalize-token',
      '/upload-file/abort-token',
    ]) {
      expect(
        () => assertOfferedReadPinFreeRequest(
          Uri.parse('https://synthetic.example$path'),
          offeredHeaders,
          body: <String, String>{'pin': pinMarker},
        ),
        throwsStateError,
      );
    }
    // A previously initialized upload keeps its file ID and token, so its
    // PIN-free completion routes remain available after the offer.
    for (final path in <String>[
      '/upload-file/chunk',
      '/upload-file/finalize-token',
      '/upload-file/abort-token',
    ]) {
      assertOfferedReadPinFreeRequest(
        Uri.parse('https://synthetic.example$path'),
        offeredHeaders,
        body: <String, String>{'upload_token': 'synthetic-upload-token'},
      );
    }
  });

  test('negotiated token shape must match exact server offer fields', () {
    final response = <String, dynamic>{
      'session_token': signedToken(15),
      'pin_free_read_offers_signed': true,
      'pin_free_file_create_signed': true,
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': true,
      'pin_free_legacy_file_download': true,
      'pin_free_v2_file_upload': true,
    };
    expect(signedOfferTokenMatches(response, requireFileCreateOffer: true),
        isTrue);
    response['pin_free_v2_file_upload'] = false;
    // Capability can disappear while the signed legacy-PIN fence remains.
    expect(signedOfferTokenMatches(response, requireFileCreateOffer: true),
        isTrue);
    response['session_token'] = signedToken(7);
    expect(signedOfferTokenMatches(response, requireFileCreateOffer: true),
        isFalse);
    response['session_token'] = token;
    expect(signedOfferTokenMatches(response, requireFileCreateOffer: true),
        isFalse);
  });

  test('auth and device offer fences old PIN routes and matches token shape', () {
    final offered = signedToken(128);
    final offeredHeaders = <String, String>{
      'Authorization': 'Bearer $offered',
    };
    final response = <String, dynamic>{
      'session_token': offered,
      'pin_free_read_offers_signed': true,
      'pin_free_auth_device_signed': true,
      'pin_free_legacy_item_read': false,
      'pin_free_legacy_file_list': false,
      'pin_free_legacy_file_download': false,
    };
    expect(signedOfferTokenMatches(response, requireAuthDeviceOffer: true),
        isTrue);
    expect(signedOfferTokenMatches(response), isFalse);
    for (final path in <String>[
      '/get-or-create-vault-meta', '/verify-pin', '/rotate-vault-kdf',
      '/vault-stats', '/devices/request-self-approval',
      '/devices/finalize-self-approval', '/vault/delete/confirm',
    ]) {
      expect(() => assertOfferedReadPinFreeRequest(
        Uri.parse('https://synthetic.example$path'), offeredHeaders,
        body: const <String, String>{'pin': '123456'},
      ), throwsStateError);
    }
    assertOfferedReadPinFreeRequest(
      Uri.parse('https://synthetic.example/vault-stats/zk'), offeredHeaders,
    );
  });

  test('actual multipart and chunk-init uploads cannot send PIN after offer',
      () async {
    final offeredToken = signedToken(8);
    SessionTermination.instance.bindSession(offeredToken);
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await expectLater(
      client.uploadVaultFile(
        vaultName: 'synthetic-vault',
        pin: pinMarker,
        authToken: offeredToken,
        filename: 'synthetic.txt',
        fileBytes: Uint8List.fromList(<int>[1, 2, 3]),
      ),
      throwsStateError,
    );
    await expectLater(
      client.initChunkedUpload(
        vaultName: 'synthetic-vault',
        pin: pinMarker,
        authToken: offeredToken,
        filename: 'synthetic.txt',
        contentType: 'text/plain',
        totalBytes: 3,
        chunkSize: 3,
      ),
      throwsStateError,
    );
    expect(sent, isEmpty);
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
