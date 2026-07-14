import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart' show
    inferAssetTypeForUpload,
    inferDetectedTypeAndServiceForUpload;

String _readMain() => File('lib/main.dart').readAsStringSync();

void main() {
  group('inferAssetTypeForUpload — filename+contentType mirror of '
        'the backend heuristic', () {
    test('images by MIME type', () {
      expect(
        inferAssetTypeForUpload(fileName: 'x', contentType: 'image/png'),
        'image',
      );
    });

    test('videos by MIME type', () {
      expect(
        inferAssetTypeForUpload(
            fileName: 'x', contentType: 'video/mp4'),
        'video',
      );
    });

    test('audio by MIME type', () {
      expect(
        inferAssetTypeForUpload(
            fileName: 'x', contentType: 'audio/mpeg'),
        'audio',
      );
    });

    test('pdf by extension', () {
      expect(
        inferAssetTypeForUpload(
            fileName: 'report.pdf', contentType: null),
        'pdf',
      );
    });

    test('docx and xlsx by extension', () {
      expect(
        inferAssetTypeForUpload(
            fileName: 'x.docx', contentType: null),
        'docx',
      );
      expect(
        inferAssetTypeForUpload(
            fileName: 'x.xlsx', contentType: null),
        'spreadsheet',
      );
    });

    test('identity photos escalate to id_image', () {
      expect(
        inferAssetTypeForUpload(
            fileName: 'my passport.jpg',
            contentType: 'image/jpeg'),
        'id_image',
      );
      expect(
        inferAssetTypeForUpload(
            fileName: 'drivers license.png',
            contentType: 'image/png'),
        'id_image',
      );
    });

    test('unknown → "file"', () {
      expect(
        inferAssetTypeForUpload(
            fileName: 'blob.bin', contentType: null),
        'file',
      );
    });
  });

  group('inferDetectedTypeAndServiceForUpload', () {
    test('passport / driver license / id card detected by filename', () {
      expect(
        inferDetectedTypeAndServiceForUpload(
            fileName: 'passport-2024.jpg').detectedType,
        'passport',
      );
      expect(
        inferDetectedTypeAndServiceForUpload(
            fileName: 'drivers license front.png').detectedType,
        'driver_license',
      );
      expect(
        inferDetectedTypeAndServiceForUpload(
            fileName: 'national id.pdf').detectedType,
        'id_card',
      );
    });

    test('bank / brokerage / crypto services detected by filename', () {
      expect(
        inferDetectedTypeAndServiceForUpload(
            fileName: 'chase statement.pdf').detectedService,
        'chase',
      );
      expect(
        inferDetectedTypeAndServiceForUpload(
            fileName: 'coinbase-tax-2024.pdf').detectedService,
        'coinbase',
      );
      expect(
        inferDetectedTypeAndServiceForUpload(
            fileName: 'wellsfargo-2024.pdf').detectedService,
        'wells_fargo',
      );
    });

    test('unknown filename → both null (conservative)', () {
      final r = inferDetectedTypeAndServiceForUpload(
          fileName: 'notes.txt');
      expect(r.detectedType, isNull);
      expect(r.detectedService, isNull);
    });
  });

  group('_runUploadAction wires the ZK metadata finalize call', () {
    test('main.dart calls '
        'tryZkFinalizeInferredUploadMetadataBestEffort '
        'immediately after a successful upload returns a file_id',
        () {
      final src = _readMain();
      // Locate the file_id extraction point and confirm the
      // finalize call appears BEFORE the returned UploadResult.
      final fileIdIdx =
          src.indexOf("final fileId = result['file_id']?.toString();");
      expect(fileIdIdx, greaterThan(-1),
          reason: 'the upload action must extract file_id somewhere');
      final returnIdx =
          src.indexOf('return UploadResult(', fileIdIdx);
      expect(returnIdx, greaterThan(fileIdIdx),
          reason: 'the return must sit after the file_id extraction');
      final between = src.substring(fileIdIdx, returnIdx);
      expect(
        between,
        contains('tryZkFinalizeInferredUploadMetadataBestEffort('),
        reason: 'the ZK metadata finalize call must fire between '
                'the file_id extraction and the UploadResult return',
      );
      expect(
        between,
        contains('unawaited('),
        reason: 'the finalize call must be fire-and-forget so the '
                'user-facing upload latency is unaffected',
      );
    });

    test('the finalize helper is fail-closed on privacy — the impl '
        'must silently drop exceptions', () {
      final src = _readMain();
      final idx = src.indexOf(
        'Future<void> tryZkFinalizeInferredUploadMetadataBestEffort(',
      );
      expect(idx, greaterThan(-1));
      final lfEnd = src.indexOf('\n}\n', idx);
      final crlfEnd = src.indexOf('\r\n}\r\n', idx);
      final int bodyEnd;
      if (lfEnd == -1) {
        bodyEnd = crlfEnd;
      } else if (crlfEnd == -1) {
        bodyEnd = lfEnd;
      } else {
        bodyEnd = lfEnd < crlfEnd ? lfEnd : crlfEnd;
      }
      final body = src.substring(idx, bodyEnd);
      expect(body, contains('catch (_)'),
          reason: 'the finalize helper must catch and drop any '
                  'error — the file has already been persisted; '
                  'metadata is best-effort');
      expect(body, contains('ZkActiveMvk.current() == null'),
          reason: 'the helper must no-op on non-ZK vaults so the '
                  'legacy backend heuristic path is unchanged');
    });
  });
}
