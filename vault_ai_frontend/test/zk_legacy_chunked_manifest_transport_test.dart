import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';

void main() {
  test('chunk manifest sends only the one-use proof and file id', () async {
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': 'synthetic-file',
              'storage_mode': 'chunks',
              'file_size': 3,
              'chunk_size': 3,
              'chunk_count': 1,
              'download_token': 'synthetic-token',
            }),
            200);
      }),
    );
    await expectLater(
      client.getZkLegacyChunkedManifest(
        authToken: 'synthetic-session',
        fileId: 'synthetic-file',
        zkProofToken: '123456',
      ),
      throwsArgumentError,
    );
    expect(requests, isEmpty);
    const proof = 'synthetic-opaque-proof';
    final manifest = await client.getZkLegacyChunkedManifest(
      authToken: 'synthetic-session',
      fileId: 'synthetic-file',
      zkProofToken: proof,
    );
    expect(manifest['file_size'], 3);
    expect(requests, hasLength(1));
    expect(requests.single.url.path, '/vault/legacy-file/chunked/manifest');
    expect(jsonDecode(requests.single.body), <String, dynamic>{
      'file_id': 'synthetic-file',
      'zk_proof_token': proof,
    });
  });
}
