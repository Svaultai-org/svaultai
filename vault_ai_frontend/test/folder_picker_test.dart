

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/folder_picker.dart';
import 'package:vault_ai_frontend/services/upload_queue.dart';


void main() {
  group('normalizePickedRelativePath', () {
    test('simple posix path passes through', () {
      expect(
        normalizePickedRelativePath('Bank/statement.pdf'),
        'Bank/statement.pdf',
      );
    });

    test('three-level nested path preserved', () {
      
      expect(
        normalizePickedRelativePath('My Life Backup/Photos/family.jpg'),
        'My Life Backup/Photos/family.jpg',
      );
    });

    test('windows backslashes normalised to forward slashes', () {
      expect(
        normalizePickedRelativePath('Bank\\statement.pdf'),
        'Bank/statement.pdf',
      );
      expect(
        normalizePickedRelativePath('a\\b\\c\\file.txt'),
        'a/b/c/file.txt',
      );
    });

    test('mixed separators normalised', () {
      expect(
        normalizePickedRelativePath('Bank\\sub/statement.pdf'),
        'Bank/sub/statement.pdf',
      );
    });

    test('doubled slashes collapsed', () {
      expect(
        normalizePickedRelativePath('Bank//statement.pdf'),
        'Bank/statement.pdf',
      );
      expect(
        normalizePickedRelativePath('a///b//c/file.txt'),
        'a/b/c/file.txt',
      );
    });

    test('trailing slash stripped', () {
      expect(
        normalizePickedRelativePath('Bank/statement.pdf/'),
        'Bank/statement.pdf',
      );
    });

    test('leading slash stripped (treat input as relative)', () {
      
      
      expect(
        normalizePickedRelativePath('/Bank/statement.pdf'),
        'Bank/statement.pdf',
      );
    });

    test('whitespace trimmed', () {
      expect(
        normalizePickedRelativePath('   Bank/statement.pdf   '),
        'Bank/statement.pdf',
      );
    });

    test('empty input stays empty', () {
      expect(normalizePickedRelativePath(''), '');
      expect(normalizePickedRelativePath('   '), '');
    });

    test('unicode segments preserved', () {
      expect(
        normalizePickedRelativePath('仕事/書類/契約.pdf'),
        '仕事/書類/契約.pdf',
      );
    });

    test('script and archive filenames pass through unchanged', () {
      
      
      const samples = [
        'project/app.py',
        'project/.env.example',
        'web/index.html',
        'scripts/setup.sh',
        'scripts/Deploy.ps1',
        'Backups/data-2024.zip',
        'Backups/archive.tar.gz',
      ];
      for (final s in samples) {
        expect(normalizePickedRelativePath(s), s,
            reason: 'path $s must round-trip unchanged');
      }
    });
  });

  group('pickRootSegment', () {
    test('first segment of nested path', () {
      expect(
        pickRootSegment('My Life Backup/Photos/family.jpg'),
        'My Life Backup',
      );
    });

    test('flat file returns whole string', () {
      expect(pickRootSegment('file.txt'), 'file.txt');
    });

    test('empty input returns empty', () {
      expect(pickRootSegment(''), '');
    });

    test('two-segment path returns first', () {
      expect(pickRootSegment('Bank/statement.pdf'), 'Bank');
    });
  });

  group('UploadJob.relativePath round-trip', () {
    test('relativePath is preserved on the UploadJob', () {
      final job = UploadJob(
        id: 'a',
        name: 'family.jpg',
        kind: 'file',
        size: 100,
        mimeType: 'image/jpeg',
        relativePath: 'My Life Backup/Photos/family.jpg',
        readBytes: () async => Uint8List(100),
      );
      expect(
        job.relativePath,
        'My Life Backup/Photos/family.jpg',
        reason: 'folder context must survive the queue',
      );
    });

    test('relativePath is null when no folder context', () {
      final job = UploadJob(
        id: 'a',
        name: 'file.pdf',
        kind: 'file',
        size: 100,
        readBytes: () async => Uint8List(100),
      );
      expect(job.relativePath, isNull);
    });
  });

  group('FolderPickerService factory selects platform impl', () {
    test('createFolderPickerService returns a non-null instance', () {
      final picker = createFolderPickerService();
      expect(picker, isNotNull);
      
      
      expect(picker.isSupported, isA<bool>());
      expect(picker.unsupportedReason, isA<String>());
    });

    test('unsupported reason is non-empty when isSupported is false',
        () {
      final picker = createFolderPickerService();
      if (!picker.isSupported) {
        expect(
          picker.unsupportedReason,
          isNotEmpty,
          reason: 'platforms that disable the picker must tell users why',
        );
      }
    });
  });

  group('Source guard: main.dart wiring', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue,
          reason: 'lib/main.dart must exist');
      return file.readAsStringSync();
    }

    test('_Attachment carries relativePath through copy()', () {
      final src = readMain();
      
      expect(
        src,
        contains('final String? relativePath;'),
        reason: '_Attachment must declare relativePath',
      );
      
      
      expect(
        src,
        contains('relativePath: relativePath,'),
        reason: '_Attachment.copy() must thread relativePath',
      );
    });

    test('folder upload option mounted inside the + attachment menu',
        () {
      final src = readMain();
      
      
      expect(
        src,
        contains('Icons.folder_open'),
        reason: 'folder upload icon must still exist in the menu',
      );
      expect(
        src,
        contains("case 'folder':"),
        reason: 'the + menu must route the folder option to its handler',
      );
      expect(
        src,
        contains('await _pickFolder();'),
        reason: 'the + menu folder option must call _pickFolder',
      );
    });

    test('_pickFolder method exists and routes through _folderPicker',
        () {
      final src = readMain();
      expect(
        src,
        contains('Future<void> _pickFolder() async'),
        reason: '_pickFolder must exist',
      );
      expect(
        src,
        contains('_folderPicker.isSupported'),
        reason: '_pickFolder must check isSupported before opening',
      );
      expect(
        src,
        contains('_folderPicker.pickFolder()'),
        reason: '_pickFolder must call the service',
      );
    });

    test('UploadJob is constructed with relativePath in '
        '_uploadAttachments', () {
      final src = readMain();
      
      expect(
        src,
        contains('relativePath: a.relativePath,'),
        reason: 'jobs built from _Attachments must thread relativePath',
      );
    });
  });

  group('Source guard: api_client wiring', () {
    String readApi() {
      final file = File('lib/api_client.dart');
      expect(file.existsSync(), isTrue,
          reason: 'lib/api_client.dart must exist');
      return file.readAsStringSync();
    }

    test('uploadVaultFile sends relative_path form field', () {
      final src = readApi();
      expect(
        src,
        contains("request.fields['relative_path'] = relativePath"),
        reason: 'legacy upload must forward relative_path to backend',
      );
    });

    test('initChunkedUpload includes relative_path in JSON body', () {
      final src = readApi();
      expect(
        src,
        contains("'relative_path': relativePath"),
        reason: 'chunked init must forward relative_path to backend',
      );
    });

    test('both upload methods accept optional relativePath parameter',
        () {
      final src = readApi();
      
      final count = 'String? relativePath'.allMatches(src).length;
      expect(
        count,
        greaterThanOrEqualTo(2),
        reason: 'uploadVaultFile + initChunkedUpload must both '
                'declare relativePath',
      );
    });

    test('relative_path is omitted from the wire when null', () {
      final src = readApi();
      
      
      expect(
        src,
        contains(
            "if (relativePath != null && relativePath.isNotEmpty)"),
        reason: 'null relativePath must NOT be sent (omit-when-null)',
      );
    });
  });

  group('Lazy reads invariant survives folder picks (hang fix)', () {
    test('PickedFolderFile.readBytes is NOT invoked at construction',
        () {
      
      
      var reads = 0;
      final file = PickedFolderFile(
        name: 'a.bin',
        relativePath: 'root/a.bin',
        size: 4,
        readBytes: () async {
          reads += 1;
          return Uint8List(4);
        },
      );
      expect(reads, 0,
          reason: 'building a PickedFolderFile must not pre-read bytes');
      expect(file.relativePath, 'root/a.bin');
    });
  });
}
