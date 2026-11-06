import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_file_local_download.dart';

const _fileId = 'synthetic-file';

Future<String> _ciphertext(List<int> bytes, SecretKey key) async {
  final box = await AesGcm.with256bits().encrypt(
    bytes, secretKey: key, nonce: List<int>.filled(12, 3),
  );
  return base64Encode(<int>[...box.nonce, ...box.cipherText, ...box.mac.bytes]);
}

class _Harness {
  final String ciphertext;
  final int fileSize;
  final List<Map<String, dynamic>> sent = [];
  bool current = true;
  int proofs = 0;
  int sequence = 0;
  int remaining = 32 * 1024 * 1024;
  int? sourceFileSize;
  bool corruptRead = false;
  bool loseAccessAfterList = false;

  _Harness(this.ciphertext, this.fileSize);

  LegacyCiphertextExportClient client() => LegacyCiphertextExportClient(
    proofProvider: () async {
      proofs++;
      return 'p1.1700000000000.${'A' * 32}.${'B' * 43}';
    },
    post: (path, body) async {
      sent.add(<String, dynamic>{'path': path, ...body});
      expect(body.containsKey('pin'), isFalse);
      expect(body.containsKey('vault_name'), isFalse);
      if (path.endsWith('/start')) {
        return <String, dynamic>{
          'export_token': 'synthetic-token', 'next_sequence': 0,
          'pages_remaining': 10, 'bytes_remaining': remaining,
          'expires_at': DateTime.now().toUtc()
              .add(const Duration(minutes: 10)).toIso8601String(),
        };
      }
      expect(path, endsWith('/page'));
      expect(body['sequence'], sequence);
      sequence++;
      remaining -= 1000;
      final page = <String, dynamic>{
        'next_sequence': sequence, 'pages_remaining': 10 - sequence,
        'bytes_remaining': remaining,
      };
      if (body['mode'] == 'list_files') {
        if (loseAccessAfterList) current = false;
        return <String, dynamic>{
          ...page,
          'records': [<String, dynamic>{
            'file_id': _fileId, 'file_size': fileSize,
            'ciphertext_chars': ciphertext.length,
          }],
          'has_more': false,
        };
      }
      expect(body['mode'], 'read_file');
      final raw = base64Decode(ciphertext);
      if (corruptRead) raw[13] ^= 1;
      final read = corruptRead ? base64Encode(raw) : ciphertext;
      return <String, dynamic>{
        ...page,
        'file_id': _fileId, 'offset': 0,
        'ciphertext_chunk': read, 'total_chars': ciphertext.length,
        'next_offset': ciphertext.length, 'done': true,
        'source_snapshot': 'S' * 43,
        'source_metadata': {'file_size': sourceFileSize ?? fileSize},
      };
    },
  );
}

void main() {
  final legacyKey = SecretKey(List<int>.filled(32, 7));
  final mvk = SecretKey(List<int>.filled(32, 9));

  LegacyFileLocalDownload reader(_Harness harness) => LegacyFileLocalDownload(
    export: harness.client(),
    codec: LegacyCiphertextMigrationCodec(legacyKey: legacyKey, mvk: mvk),
    accessIsCurrent: () => harness.current,
  );

  test('older inline file downloads through proof export without PIN body', () async {
    final expected = Uint8List.fromList(List<int>.generate(128, (i) => i));
    final harness = _Harness(await _ciphertext(expected, legacyKey),
        expected.length);
    final result = await reader(harness).read(_fileId);
    expect(result, expected);
    expect(harness.proofs, 1);
    expect(harness.sent.map((request) => request['path']), [
      '/vault/legacy-ciphertext/export/start',
      '/vault/legacy-ciphertext/export/page',
      '/vault/legacy-ciphertext/export/page',
    ]);
  });

  test('source metadata stays paired with decrypted bytes', () async {
    final expected = Uint8List.fromList([2, 4, 6]);
    final harness = _Harness(await _ciphertext(expected, legacyKey), 3);
    final result = await reader(harness).readWithSource(_fileId);
    expect(result.bytes, expected);
    expect(result.sourceMetadata['file_size'], 3);
  });

  test('changed source size fails without yielding bytes', () async {
    final payload = List<int>.filled(32, 1);
    final harness = _Harness(await _ciphertext(payload, legacyKey), 32)
      ..sourceFileSize = 33;
    await expectLater(reader(harness).read(_fileId), throwsFormatException);
  });

  test('tampered ciphertext cannot be opened', () async {
    final payload = List<int>.filled(32, 2);
    final harness = _Harness(await _ciphertext(payload, legacyKey), 32)
      ..corruptRead = true;
    await expectLater(reader(harness).read(_fileId), throwsA(isA<Exception>()));
  });

  test('session loss after inventory stops before ciphertext read', () async {
    final payload = List<int>.filled(32, 2);
    final harness = _Harness(await _ciphertext(payload, legacyKey), 32)
      ..loseAccessAfterList = true;
    await expectLater(reader(harness).read(_fileId), throwsStateError);
    expect(harness.sent.where((request) => request['mode'] == 'read_file'),
        isEmpty);
  });
}
