import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/chunked_aead.dart';
import 'package:vault_ai_frontend/services/ephemeral_legacy_file_action.dart';
import 'package:vault_ai_frontend/services/legacy_chunked_local_download.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_file_read_session.dart';
import 'package:vault_ai_frontend/services/legacy_stage_pin_lease.dart';

const _pin = '246810'; // Synthetic. Never use a real vault credential here.
final _proof = 'p1.1700000000000.${'A' * 32}.${'B' * 43}';

EphemeralLegacyFileAction _action({
  required SecretKey key,
  required bool Function() current,
  required void Function() prompted,
  required void Function() verified,
  required void Function() derived,
}) => EphemeralLegacyFileAction(
  promptPin: () async { prompted(); return _pin; },
  verifyPin: (pin) async {
    expect(pin, _pin);
    verified();
    return _proof;
  },
  deriveKey: (pin) async {
    expect(pin, _pin);
    derived();
    return key;
  },
  accessIsCurrent: current,
);

void main() {
  test('inline file opens locally with one proof and no PIN request body',
      () async {
    final key = SecretKey(List<int>.filled(32, 7));
    final expected = Uint8List.fromList(List<int>.generate(72, (i) => i));
    final box = await AesGcm.with256bits().encrypt(
      expected, secretKey: key, nonce: List<int>.filled(12, 3),
    );
    final ciphertext = base64Encode(
      <int>[...box.nonce, ...box.cipherText, ...box.mac.bytes],
    );
    var prompts = 0;
    var verifies = 0;
    var derives = 0;
    var sequence = 0;
    final sent = <Map<String, dynamic>>[];
    final action = _action(
      key: key, current: () => true,
      prompted: () => prompts++, verified: () => verifies++,
      derived: () => derives++,
    );
    final localKey = await action.open();
    final export = LegacyCiphertextExportClient(
      proofProvider: action.proof,
      post: (path, body) async {
        sent.add(<String, dynamic>{'path': path, ...body});
        expect(body.containsKey('pin'), isFalse);
        expect(body.containsKey('vault_name'), isFalse);
        expect(jsonEncode(body).contains(_pin), isFalse);
        if (path.endsWith('/start')) {
          expect(body['zk_proof_token'], _proof);
          return <String, dynamic>{
            'export_token': 'synthetic-grant', 'next_sequence': 0,
            'pages_remaining': 10, 'bytes_remaining': 32 * 1024 * 1024,
            'expires_at': DateTime.now().toUtc()
                .add(const Duration(minutes: 5)).toIso8601String(),
          };
        }
        expect(path, endsWith('/page'));
        expect(body['sequence'], sequence++);
        final cursor = <String, dynamic>{
          'next_sequence': sequence, 'pages_remaining': 10 - sequence,
          'bytes_remaining': 32 * 1024 * 1024 - sequence * 1024,
        };
        if (body['mode'] == 'list_files') {
          return <String, dynamic>{
            ...cursor,
            'records': [<String, dynamic>{
              'file_id': 'synthetic-file', 'file_size': expected.length,
              'ciphertext_chars': ciphertext.length,
            }],
            'has_more': false,
          };
        }
        expect(body['mode'], 'read_file');
        return <String, dynamic>{
          ...cursor,
          'file_id': 'synthetic-file', 'offset': 0,
          'ciphertext_chunk': ciphertext, 'total_chars': ciphertext.length,
          'next_offset': ciphertext.length, 'done': true,
          'source_snapshot': 'S' * 43,
          'source_metadata': <String, dynamic>{'file_size': expected.length},
        };
      },
    );
    final reader = LegacyFileReadSession(
      export: export,
      codec: LegacyCiphertextMigrationCodec(
        legacyKey: localKey, mvk: SecretKey(List<int>.filled(32, 9)),
      ),
      isCurrent: () => action.isOpen,
    );
    try {
      final opened = await reader.readFile('synthetic-file');
      expect(opened.bytes, expected);
    } finally {
      reader.close();
      action.close();
    }
    expect(prompts, 1);
    expect(verifies, 1);
    expect(derives, 1);
    expect(sent.length, 3);
    expect(action.isOpen, isFalse);
    await expectLater(action.proof(), throwsStateError);
  });

  test('chunked file decrypts locally and its extracted key is cleared',
      () async {
    final key = SecretKey(List<int>.filled(32, 41));
    final expected = Uint8List.fromList([1, 2, 3, 4, 5, 6]);
    final frames = <Uint8List>[
      await encryptChunk(plaintext: expected.sublist(0, 4),
          key: await key.extractBytes(), chunkIndex: 0),
      await encryptChunk(plaintext: expected.sublist(4),
          key: await key.extractBytes(), chunkIndex: 1),
    ];
    var prompts = 0;
    var verifies = 0;
    var derives = 0;
    final action = _action(
      key: key, current: () => true,
      prompted: () => prompts++, verified: () => verifies++,
      derived: () => derives++,
    );
    final localKey = await action.open();
    final manifestBody = <String, dynamic>{
      'file_id': 'synthetic-file', 'zk_proof_token': await action.proof(),
    };
    expect(manifestBody.containsKey('pin'), isFalse);
    expect(jsonEncode(manifestBody).contains(_pin), isFalse);
    final keyBytes = Uint8List.fromList(await localKey.extractBytes());
    try {
      final bytes = await LegacyChunkedLocalDownload(
        readEncryptedFrame: (index) async => frames[index],
        legacyKey: keyBytes,
        accessIsCurrent: () => action.isOpen,
      ).read(fileSize: expected.length, chunkSize: 4, chunkCount: 2);
      expect(bytes, expected);
    } finally {
      keyBytes.fillRange(0, keyBytes.length, 0);
      action.close();
    }
    expect(keyBytes, everyElement(0));
    expect(action.isOpen, isFalse);
    expect([prompts, verifies, derives], [1, 1, 1]);
  });

  test('cancel and session loss release the key and do not yield a proof',
      () async {
    final cancelled = EphemeralLegacyFileAction(
      promptPin: () async => null,
      verifyPin: (_) async => _proof,
      deriveKey: (_) async => SecretKey(List<int>.filled(32, 7)),
      accessIsCurrent: () => true,
    );
    await expectLater(cancelled.open(),
        throwsA(isA<LegacyFileActionCancelled>()));
    expect(cancelled.isOpen, isFalse);

    var current = true;
    final lost = EphemeralLegacyFileAction(
      promptPin: () async => _pin,
      verifyPin: (_) async => _proof,
      deriveKey: (_) async {
        current = false;
        return SecretKey(List<int>.filled(32, 7));
      },
      accessIsCurrent: () => current,
    );
    await expectLater(lost.open(), throwsStateError);
    expect(lost.isOpen, isFalse);
    await expectLater(lost.proof(), throwsStateError);
  });

  test('owner can cancel an expired-lease renewal without a second proof',
      () async {
    var now = DateTime.utc(2026, 11, 7);
    var prompts = 0;
    var proofs = 0;
    final renewal = RenewableLegacyStagePinLease(
      promptPin: () async => prompts++ == 0 ? _pin : null,
      lifetime: const Duration(minutes: 1),
      now: () => now,
    );
    final action = EphemeralLegacyFileAction(
      promptPin: renewal.requireOrPrompt,
      verifyPin: (pin) async {
        proofs++;
        renewal.requireActive();
        return _proof;
      },
      deriveKey: (_) async => SecretKey(List<int>.filled(32, 7)),
      accessIsCurrent: () => true,
    );
    try {
      await action.open();
      expect(await action.proof(), _proof);
      now = now.add(const Duration(minutes: 1));
      await expectLater(action.proof(),
          throwsA(isA<LegacyFileActionCancelled>()));
      expect(prompts, 2);
      expect(proofs, 1);
    } finally {
      action.close();
      renewal.clear();
    }
  });

  test('session change during owner renewal cannot produce a new proof',
      () async {
    var now = DateTime.utc(2026, 11, 7);
    var current = true;
    var prompts = 0;
    var proofs = 0;
    final renewalEntry = Completer<String?>();
    final renewal = RenewableLegacyStagePinLease(
      promptPin: () {
        prompts++;
        return prompts == 1 ? Future<String?>.value(_pin)
            : renewalEntry.future;
      },
      lifetime: const Duration(minutes: 1),
      now: () => now,
    );
    final action = EphemeralLegacyFileAction(
      promptPin: renewal.requireOrPrompt,
      verifyPin: (pin) async {
        proofs++;
        renewal.requireActive();
        return _proof;
      },
      deriveKey: (_) async => SecretKey(List<int>.filled(32, 7)),
      accessIsCurrent: () => current,
    );
    try {
      await action.open();
      expect(await action.proof(), _proof);
      now = now.add(const Duration(minutes: 1));
      final pending = action.proof();
      current = false;
      renewalEntry.complete(_pin);
      await expectLater(pending, throwsStateError);
      expect(proofs, 1);
    } finally {
      action.close();
      renewal.clear();
    }
  });
}
