import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;

const _token = 'synthetic-session';

void main() {
  setUp(() {
    st.SessionTermination.instance.resetForTests();
    st.SessionTermination.instance.bindSession(_token);
  });
  tearDown(() => st.SessionTermination.instance.resetForTests());

  VaultAIClient clientFor(List<http.Request> requests) => VaultAIClient(
    baseUrl: 'https://example.invalid',
    httpClient: MockClient((request) async {
      requests.add(request);
      return http.Response(
        '{"status":"ok","import_id":"synthetic-import"}',
        200,
      );
    }),
  );

  test('beneficiary deletion uses one-time proof without raw PIN', () async {
    final requests = <http.Request>[];
    await clientFor(requests).deleteBeneficiary(
      linkId: 7,
      vaultName: 'synthetic',
      zkProofToken: 'synthetic-proof',
      authToken: _token,
    );
    expect(requests.single.url.path, kEnableZkPrivateOnlyUnlock
        ? '/beneficiary/proof/delete' : '/beneficiary/delete');
    final body = jsonDecode(requests.single.body) as Map<String, dynamic>;
    expect(body['zk_proof_token'], 'synthetic-proof');
    expect(body.containsKey('pin'), isFalse);
    expect(body['link_id'], 7);
    if (kEnableZkPrivateOnlyUnlock) {
      expect(body.keys.toSet(), {'link_id', 'zk_proof_token'});
    }
  });

  test('strict beneficiary lists and cancellation use proof-only routes',
      () async {
    final requests = <http.Request>[];
    final client = clientFor(requests);
    await client.listBeneficiaries(
      vaultName: 'synthetic private name',
      zkProofToken: 'proof-one', authToken: _token,
    );
    await client.listInheritances(
      vaultName: 'synthetic private name',
      zkProofToken: 'proof-two', authToken: _token,
    );
    await client.cancelTransfer(
      linkId: 7, vaultName: 'synthetic private name',
      zkProofToken: 'proof-three', authToken: _token,
    );
    expect(requests.map((r) => r.url.path), [
      '/beneficiary/proof/list-mine',
      '/beneficiary/proof/list-inheritances',
      '/beneficiary/proof/cancel-transfer',
    ]);
    for (final request in requests) {
      expect(request.body, isNot(contains('synthetic private name')));
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body.containsKey('pin'), isFalse);
      expect(body.containsKey('vault_name'), isFalse);
    }
    expect((jsonDecode(requests.last.body) as Map).keys.toSet(),
        {'link_id', 'zk_proof_token'});
  }, skip: !kEnableZkPrivateOnlyUnlock);

  test('legacy file deletion uses one-time proof without raw PIN', () async {
    final requests = <http.Request>[];
    await clientFor(requests).deleteVaultFile(
      vaultName: 'synthetic',
      fileId: 'synthetic-file',
      zkProofToken: 'synthetic-proof',
      authToken: _token,
    );
    expect(requests.single.url.path, '/manage/file/delete');
    final body = jsonDecode(requests.single.body) as Map<String, dynamic>;
    expect(body['zk_proof_token'], 'synthetic-proof');
    expect(body.containsKey('pin'), isFalse);
    expect(body['file_id'], 'synthetic-file');
  });

  test('signed file mutation uses proof-only delete route and fences old paths',
      () async {
    final signed = base64UrlEncode(<int>[
      3, 39, ...List<int>.filled(48, 7),
    ]);
    final offer = <String, dynamic>{
      'session_token': signed,
      'pin_free_read_offers_signed': true,
      'pin_free_file_mutation_signed': true,
      'pin_free_legacy_item_read': true,
      'pin_free_legacy_file_list': true,
      'pin_free_legacy_file_download': true,
    };
    expect(signedOfferTokenMatches(offer,
        requireFileMutationOffer: true), isTrue);
    expect(signedOfferTokenMatches(offer), isFalse);
    st.SessionTermination.instance.bindSession(signed);
    final requests = <http.Request>[];
    final client = clientFor(requests);
    await client.deleteVaultFile(
      vaultName: 'synthetic',
      fileId: 'synthetic-file',
      zkProofToken: 'synthetic-proof',
      authToken: signed,
    );
    expect(requests.single.url.path, '/manage/file/delete-proof');
    final body = jsonDecode(requests.single.body) as Map<String, dynamic>;
    expect(body['zk_proof_token'], 'synthetic-proof');
    expect(body.containsKey('pin'), isFalse);
    await expectLater(
      client.deleteVaultFile(
        vaultName: 'synthetic', fileId: 'synthetic-file',
        pin: '123456', authToken: signed,
      ),
      throwsStateError,
    );
    await expectLater(
      client.nameVaultFile(
        vaultName: 'synthetic', fileId: 'synthetic-file',
        savedName: 'private title', pin: '123456', authToken: signed,
      ),
      throwsStateError,
    );
    expect(requests, hasLength(1));
  });

  test('proof actions reject ambiguous or absent credentials', () async {
    final requests = <http.Request>[];
    final client = clientFor(requests);
    await expectLater(
      client.deleteBeneficiary(
        linkId: 1,
        vaultName: 'synthetic',
        pin: '123456',
        zkProofToken: 'proof',
        authToken: _token,
      ),
      kEnableZkPrivateOnlyUnlock ? throwsStateError : throwsArgumentError,
    );
    await expectLater(
      client.deleteVaultFile(
        vaultName: 'synthetic',
        fileId: 'synthetic-file',
        authToken: _token,
      ),
      throwsArgumentError,
    );
    expect(requests, isEmpty);
  });

  test('trusted ZK import bookkeeping omits PIN for all actions', () async {
    final requests = <http.Request>[];
    final client = clientFor(requests);
    await client.startImport(
      vaultName: 'synthetic',
      pin: null,
      zkSessionOnly: true,
      authToken: _token,
      totalFiles: 2,
    );
    await client.completeImport(
      vaultName: 'synthetic',
      pin: null,
      zkSessionOnly: true,
      authToken: _token,
      importId: 'synthetic-import',
    );
    await client.cancelImport(
      vaultName: 'synthetic',
      pin: null,
      zkSessionOnly: true,
      authToken: _token,
      importId: 'synthetic-import',
    );
    expect(requests.length, 3);
    expect(requests.map((r) => r.url.path), [
      '/imports/session/start',
      '/imports/session/synthetic-import/complete',
      '/imports/session/synthetic-import/cancel',
    ]);
    for (final request in requests) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body.containsKey('pin'), isFalse);
      expect(body.containsKey('vault_name'), isFalse);
      expect(body.containsKey('root_folder_name'), isFalse);
    }
  });

  test(
    'trusted import rejects PIN and plaintext folder name before wire',
    () async {
      final requests = <http.Request>[];
      final client = clientFor(requests);
      await expectLater(
        client.startImport(
          vaultName: 'synthetic',
          pin: '123456',
          zkSessionOnly: true,
          authToken: _token,
        ),
        throwsArgumentError,
      );
      await expectLater(
        client.startImport(
          vaultName: 'synthetic',
          pin: null,
          zkSessionOnly: true,
          authToken: _token,
          rootFolderName: 'private name',
        ),
        throwsArgumentError,
      );
      expect(requests, isEmpty);
    },
  );

  test('legacy request shape remains explicit when flags are off', () async {
    final requests = <http.Request>[];
    final client = clientFor(requests);
    await client.deleteBeneficiary(
      linkId: 1,
      vaultName: 'synthetic',
      pin: '123456',
      authToken: _token,
    );
    await client.deleteVaultFile(
      vaultName: 'synthetic',
      fileId: 'synthetic-file',
      pin: '123456',
      authToken: _token,
    );
    await client.startImport(
      vaultName: 'synthetic',
      pin: '123456',
      authToken: _token,
    );
    expect(requests.length, 3);
    for (final request in requests) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body['pin'], '123456');
      expect(body.containsKey('zk_proof_token'), isFalse);
    }
  }, skip: kPrivateOnlyTransportRejectPin);

  test('strict build blocks direct legacy actions before HTTP', () async {
    final requests = <http.Request>[];
    final client = clientFor(requests);
    await expectLater(
      client.deleteBeneficiary(
        linkId: 1,
        vaultName: 'synthetic',
        pin: '123456',
        authToken: _token,
      ),
      throwsStateError,
    );
    await expectLater(
      client.deleteVaultFile(
        vaultName: 'synthetic',
        fileId: 'synthetic-file',
        pin: '123456',
        authToken: _token,
      ),
      throwsStateError,
    );
    await expectLater(
      client.startImport(
        vaultName: 'synthetic',
        pin: '123456',
        authToken: _token,
      ),
      throwsStateError,
    );
    expect(requests, isEmpty);
  }, skip: !kPrivateOnlyTransportRejectPin);

  test('strict delete and device actions use proof-only request shapes',
      () async {
    final requests = <http.Request>[];
    final client = clientFor(requests);
    await client.confirmDeleteVault(
      authToken: _token, requestToken: 'delete-request',
      zkProofToken: 'proof-delete', confirmationPhrase: 'DELETE MY VAULT',
    );
    await client.requestSelfApproval(
      authToken: _token, zkProofToken: 'proof-request',
    );
    await client.finalizeSelfApproval(
      authToken: _token, zkProofToken: 'proof-finalize',
    );
    expect(requests.map((r) => r.url.path), [
      '/vault/delete/confirm-proof',
      '/devices/request-self-approval-proof',
      '/devices/finalize-self-approval-proof',
    ]);
    for (final request in requests) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body.containsKey('pin'), isFalse);
      expect(body.containsKey('vault_name'), isFalse);
    }
    final before = requests.length;
    await expectLater(client.confirmDeleteVault(
      authToken: _token, requestToken: 'delete-request', pin: '123456',
      confirmationPhrase: 'DELETE MY VAULT',
    ), throwsStateError);
    await expectLater(client.requestSelfApproval(
      authToken: _token, pin: '123456',
    ), throwsStateError);
    expect(requests.length, before);
  }, skip: !kEnableZkPrivateOnlyUnlock);
}
