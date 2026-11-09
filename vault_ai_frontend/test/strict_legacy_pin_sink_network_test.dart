import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;

void main() {
  const token = 'synthetic-strict-session';
  const pin = '7319462085';

  setUp(() {
    st.SessionTermination.instance.resetForTests();
    st.SessionTermination.instance.bindSession(token);
    PrivateZkPinTransportSession.bind(token);
  });
  tearDown(() {
    PrivateZkPinTransportSession.clear();
    st.SessionTermination.instance.resetForTests();
  });

  test('strict chat refuses to construct a legacy PIN request body', () {
    expect(
      () => buildChatRequestBody(
        encryptedMessage: 'ciphertext',
        vaultName: 'Private name',
        pin: pin,
      ),
      throwsStateError,
    );
  }, skip: !kPrivateOnlyTransportRejectPin);

  test('legacy action calls cannot send raw PIN or vault name in strict build',
      () async {
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{}', 200);
      }),
    );

    final actions = <String, Future<void> Function()>{
      'chat': () async => client
          .chatStream(
            encryptedMessage: 'ciphertext',
            vaultName: 'Private name',
            pin: pin,
            authToken: token,
          )
          .toList(),
      'delete confirmation': () async => client.confirmDeleteVault(
            authToken: token,
            requestToken: 'request',
            pin: pin,
            confirmationPhrase: 'DELETE MY VAULT',
          ),
      'password analysis': () async => client.analyzePasswords(
            authToken: token,
            vaultName: 'Private name',
            pin: pin,
          ),
      'device request': () async => client.requestSelfApproval(
            authToken: token,
            pin: pin,
          ),
      'device finalize': () async => client.finalizeSelfApproval(
            authToken: token,
            pin: pin,
          ),
      'deep answer': () async => client.startDeepAnswer(
            authToken: token,
            pin: pin,
            vaultHandle: 'opaque-handle',
          ),
      'deep answer poll': () async => client.pollDeepAnswerJob(
            authToken: token,
            pin: pin,
            jobId: 'job',
            vaultHandle: 'opaque-handle',
          ),
      'beneficiary create': () async => client.createBeneficiary(
            vaultName: 'Private name',
            pin: pin,
            label: 'Synthetic',
            authToken: token,
          ),
      'beneficiary link': () async => client.linkBeneficiary(
            vaultName: 'Private name',
            pin: pin,
            pairingCode: '123456',
            authToken: token,
          ),
      'beneficiary claim': () async => client.claimTransfer(
            linkId: 1,
            vaultName: 'Private name',
            pin: pin,
            authToken: token,
          ),
      'KDF rotation': () async => client.rotateVaultKdf(
            vaultName: 'Private name',
            pin: pin,
            authToken: token,
          ),
      'saved item list': () async => client.listVaultSecureItems(
            vaultName: 'Private name',
            pin: pin,
            authToken: token,
          ),
      'saved item detail': () async => client.getVaultSecureItem(
            vaultName: 'Private name',
            service: 'Synthetic',
            itemType: 'login',
            pin: pin,
            authToken: token,
          ),
      'file upload': () async => client.uploadVaultFile(
            vaultName: 'Private name',
            pin: pin,
            authToken: token,
            filename: 'synthetic.txt',
            fileBytes: Uint8List(0),
          ),
      'import start': () async => client.startImport(
            vaultName: 'Private name',
            pin: pin,
            authToken: token,
          ),
      'file rename': () async => client.nameVaultFile(
            vaultName: 'Private name',
            fileId: 'file',
            savedName: 'Synthetic',
            pin: pin,
            authToken: token,
          ),
      'file list': () async => client.listVaultFiles(
            vaultName: 'Private name',
            pin: pin,
            authToken: token,
          ),
      'file download': () async => client.downloadVaultFile(
            vaultName: 'Private name',
            fileId: 'file',
            pin: pin,
            authToken: token,
          ),
      'chunked upload init': () async => client.initChunkedUpload(
            vaultName: 'Private name',
            pin: pin,
            authToken: token,
            filename: 'synthetic.txt',
            contentType: 'text/plain',
            totalBytes: 1,
            chunkSize: 1,
          ),
      'download manifest': () async => client.getDownloadManifest(
            authToken: token,
            vaultName: 'Private name',
            pin: pin,
            fileId: 'file',
          ),
      'saved item edit': () async => client.updateVaultSecureItem(
            vaultName: 'Private name',
            oldService: 'Synthetic',
            itemType: 'login',
            pin: pin,
            authToken: token,
          ),
      'saved item delete': () async => client.deleteVaultSecureItem(
            vaultName: 'Private name',
            service: 'Synthetic',
            itemType: 'login',
            pin: pin,
            authToken: token,
          ),
      'related files': () async => client.fetchRelatedFiles(
            fileId: 'file',
            pin: pin,
            authToken: token,
            vaultHandle: 'opaque-handle',
          ),
    };

    for (final entry in actions.entries) {
      try {
        await entry.value();
      } catch (_) {
        // A strict client may reject an obsolete action before transport.
      }
      for (final request in requests) {
        expect(request.url.toString(), isNot(contains('Private name')),
            reason: entry.key);
        expect(request.headers.keys.any((key) => key.toLowerCase() == 'pin'),
            isFalse,
            reason: entry.key);
        expect(request.body, isNot(contains(pin)), reason: entry.key);
        if (request.headers['Content-Type']?.contains('application/json') ==
                true &&
            request.body.isNotEmpty) {
          final decoded = jsonDecode(request.body);
          if (decoded is Map) {
            expect(decoded.containsKey('pin'), isFalse, reason: entry.key);
            expect(decoded.containsKey('vault_name'), isFalse,
                reason: entry.key);
          }
        }
      }
      requests.clear();
    }
  }, skip: !kPrivateOnlyTransportRejectPin);
}
