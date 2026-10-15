import 'dart:async';
import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart' as zk;

const token = 'synthetic-current-session';
final session = st.SessionTermination.instance;

typedef Call = Future<Object?> Function(VaultAIClient client, bool Function() current);

class GuardedOperation {
  const GuardedOperation(this.name, this.method, this.path, this.call,
      {this.needsKey = false});
  final String name;
  final String method;
  final String path;
  final Call call;
  final bool needsKey;
}

final operations = <GuardedOperation>[
  GuardedOperation('catalog', 'GET', '/crypto/wallet/asset-catalog',
    (c, current) => c.getCryptoWalletAssetCatalog(authToken: token, responseIsCurrent: current)),
  GuardedOperation('features', 'GET', '/crypto/wallet/features',
    (c, current) => c.getCryptoWalletFeatures(authToken: token, responseIsCurrent: current)),
  GuardedOperation('file delete', 'POST', '/manage/file/delete',
    (c, current) => c.deleteVaultFile(vaultName: 'Synthetic', fileId: 'file',
      pin: '000000', authToken: token, responseIsCurrent: current)),
  GuardedOperation('legacy rename', 'POST', '/name-file',
    (c, current) => c.nameVaultFile(vaultName: 'Synthetic', fileId: 'file',
      savedName: 'New name', pin: '000000', authToken: token, responseIsCurrent: current)),
  GuardedOperation('ciphertext rename', 'POST', '/vault/ciphertext/uploaded-files',
    (c, current) => c.nameVaultFile(vaultName: 'Synthetic', fileId: 'file',
      savedName: 'New name', pin: '000000', authToken: token,
      requireCiphertext: true, responseIsCurrent: current), needsKey: true),
  GuardedOperation('memory list', 'GET', '/vault/ciphertext/vault-ai-memory',
    (c, _) => c.listZkMemories(authToken: token), needsKey: true),
  GuardedOperation('memory finalize', 'POST', '/vault/ciphertext/vault-ai-memory',
    (c, _) => c.tryZkFinalizeMemoryProposal(baseUrl: 'https://example.invalid',
      authToken: token, memoryType: 'note', memoryKey: 'Synthetic title',
      memoryValue: 'Synthetic value'), needsKey: true),
  GuardedOperation('memory upsert', 'POST', '/vault/ciphertext/vault-ai-memory',
    (c, _) => c.upsertZkMemory(authToken: token,
      data: {'title': 'Synthetic title', 'value': 'Synthetic value'}), needsKey: true),
  GuardedOperation('ciphertext saved item list', 'GET', '/vault/ciphertext/vault-items',
    (c, _) => c.listVaultSecureItems(vaultName: 'Synthetic', pin: '000000', authToken: token), needsKey: true),
  GuardedOperation('saved item legacy inventory', 'POST', '/list-secure-items',
    (c, _) => c.listVaultSecureItems(vaultName: 'Synthetic', pin: '000000', authToken: token), needsKey: true),
  GuardedOperation('generated draft legacy inventory', 'POST', '/list-secure-items',
    (c, _) => c.saveGeneratedLoginDraftCiphertext(authToken: token, pin: '000000',
      draftId: 'draft', service: 'Synthetic service', fields: {'username': 'Synthetic'}), needsKey: true),
  GuardedOperation('PAXG ciphertext history', 'POST', '/vault/ciphertext/crypto-history',
    (c, _) => c.postCryptoWalletPaxgOutgoingHistoryCiphertext(authToken: token,
      signatureLookupHash: 'synthetic-lookup', outcomePayloadCiphertext: 'synthetic-ciphertext')),
];

void main() {
  setUp(() {
    session.resetForTests();
    session.bindSession(token);
    zk.ZkActiveMvk.clear();
  });
  tearDown(() {
    session.resetForTests();
    zk.ZkActiveMvk.clear();
  });

  for (final operation in operations) {
    for (final status in [200, 401, 403]) {
      test('${operation.name} rejects outdated context before classifying $status', () async {
        var current = true;
        var terminations = 0;
        session.setHandler((_) async { terminations++; });
        if (operation.needsKey) {
          zk.ZkActiveMvk.set(mvk: SecretKey(List<int>.filled(32, 7)),
            vaultId: 'synthetic-vault', vaultHandle: 'synthetic-handle');
        }
        final started = Completer<void>();
        final response = Completer<http.Response>();
        final client = VaultAIClient(baseUrl: 'https://example.invalid',
          walletResponseIsCurrent: () => current,
          httpClient: MockClient((request) {
            if (request.method == operation.method && request.url.path == operation.path) {
              started.complete();
              return response.future;
            }
            // Existing ciphertext preflight requests precede the guarded write.
            if (request.method == 'GET' && request.url.path.startsWith('/vault/ciphertext/')) {
              return Future.value(http.Response('[]', 200));
            }
            throw StateError('Unexpected fixture request');
          }));
        final rejected = expectLater(operation.call(client, () => current), throwsStateError);
        await started.future;
        // The current bearer and session epoch stay unchanged. Only the
        // captured operation/key lease expires, as on lock or selection change.
        current = false;
        if (operation.needsKey) zk.ZkActiveMvk.clear();
        response.complete(http.Response(jsonEncode({'detail': {'code':
          status == 403 ? 'device_revoked' : 'session_superseded'}}), status));
        await rejected;
        expect(terminations, 0);
        expect(session.isTerminated, isFalse);
        expect(session.isCurrentRequest(session.captureRequest(token)), isTrue);
      });
    }
  }

  test('current wallet lease still terminates a confirmed displaced session', () async {
    var terminations = 0;
    session.setHandler((_) async { terminations++; });
    final client = VaultAIClient(baseUrl: 'https://example.invalid',
      walletResponseIsCurrent: () => true,
      httpClient: MockClient((_) async => http.Response(
        '{"detail":{"code":"session_superseded"}}', 401)));
    await expectLater(client.getCryptoWalletReceiveNetwork(network: 'ethereum_mainnet',
      asset: 'PAXG', authToken: token), throwsA(isA<SessionTerminatedException>()));
    expect(terminations, 1);
    expect(session.isTerminated, isTrue);
  });
}
