import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/private_content_pin_guard.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  const syntheticPin = 'synthetic-test-pin';

  setUp(() {
    ZkActiveMvk.clear();
    setApiClientDeviceId('synthetic-private-guard-device');
  });
  tearDown(() {
    ZkActiveMvk.clear();
    setApiClientDeviceId('');
  });

  test('private ZK unlock never dispatches deep start, poll or related search',
      () async {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 11)),
      vaultId: 'synthetic-vault-id',
      vaultHandle: 'synthetic-zk-handle',
    );
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        fail('A private content route reached the network');
      }),
    );

    await expectLater(
      client.startDeepAnswer(
        pin: syntheticPin,
        authToken: 'synthetic-session',
      ),
      throwsA(isA<PrivateContentSearchUnavailable>()),
    );
    await expectLater(
      client.pollDeepAnswerJob(
        pin: syntheticPin,
        authToken: 'synthetic-session',
        jobId: 'synthetic-job',
      ),
      throwsA(isA<PrivateContentSearchUnavailable>()),
    );
    await expectLater(
      client.fetchRelatedFiles(
        fileId: 'synthetic-file',
        pin: syntheticPin,
        authToken: 'synthetic-session',
      ),
      throwsA(isA<PrivateContentSearchUnavailable>()),
    );
    expect(requests, isEmpty);
    expect(blocksZkLegacyContentRoute(vaultHandle: 'synthetic-zk-handle'), true);
    // A key-loss race must still be blocked when the authenticated UI says
    // this session belongs to a ZK vault.
    ZkActiveMvk.clear();
    await expectLater(
      client.startDeepAnswer(
        pin: syntheticPin,
        authToken: 'synthetic-session',
        vaultHandle: 'synthetic-zk-handle',
      ),
      throwsA(isA<PrivateContentSearchUnavailable>()),
    );
    expect(requests, isEmpty);
  }, skip: !kGuardZkPrivateContentPinRoutes);

  test('legacy-only vault keeps its existing PIN-bearing route contract',
      () async {
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-private-guard-device');
        expect((jsonDecode(request.body) as Map)['pin'], syntheticPin);
        return http.Response('{}', 200);
      }),
    );

    await client.startDeepAnswer(
      pin: syntheticPin,
      authToken: 'synthetic-session',
    );
    await client.pollDeepAnswerJob(
      pin: syntheticPin,
      authToken: 'synthetic-session',
      jobId: 'synthetic-job',
    );
    await client.fetchRelatedFiles(
      fileId: 'synthetic-file',
      pin: syntheticPin,
      authToken: 'synthetic-session',
    );
    expect(requests.map((request) => request.url.path), <String>[
      '/vault-analysis/deep-answer',
      '/vault-analysis/deep-answer/synthetic-job/poll',
      '/files/synthetic-file/related',
    ]);
    expect(blocksZkLegacyContentRoute(), false);
  }, skip: kEnableZkPrivateOnlyUnlock);

  test('guard is dormant in ordinary builds', () {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 11)),
      vaultId: 'synthetic-vault-id',
      vaultHandle: 'synthetic-zk-handle',
    );
    expect(blocksZkLegacyContentRoute(), false);
    expect(blocksZkRelatedFilesPinRoute(), false);
  }, skip: kGuardZkPrivateContentPinRoutes || kEnableZkLocalRelatedFiles);

  test('an active private key blocks old content even if its handle is missing',
      () {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 11)),
      vaultId: 'synthetic-vault-id',
      vaultHandle: '',
    );
    if (kGuardZkPrivateContentPinRoutes) {
      expect(blocksZkLegacyContentRoute(), true);
    }
    expect(blocksZkRelatedFilesPinRoute(), true);
  }, skip: !kGuardZkPrivateContentPinRoutes && !kEnableZkLocalRelatedFiles);

  test('related-files opt-in blocks only the OPAQUE PIN request', () async {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 11)),
      vaultId: 'synthetic-vault-id',
      vaultHandle: 'synthetic-zk-handle',
    );
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{}', 200);
      }),
    );
    expect(blocksZkRelatedFilesPinRoute(), true);
    expect(blocksZkLegacyContentRoute(), false);
    await expectLater(
      client.fetchRelatedFiles(
        fileId: 'synthetic-file',
        pin: syntheticPin,
        authToken: 'synthetic-session',
      ),
      throwsA(isA<PrivateContentSearchUnavailable>()),
    );
    expect(requests, isEmpty);
    await client.startDeepAnswer(
      pin: syntheticPin,
      authToken: 'synthetic-session',
    );
    expect(requests.single.url.path, '/vault-analysis/deep-answer');
  }, skip: !kEnableZkLocalRelatedFiles || kGuardZkPrivateContentPinRoutes);
}
