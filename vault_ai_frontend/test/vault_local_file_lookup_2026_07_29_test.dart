import 'package:flutter_test/flutter_test.dart';
import 'dart:io';
import 'package:vault_ai_frontend/services/vault_local_file_lookup.dart';

void main() {
  test('file inventory failures never expose raw gateway bodies', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, isNot(contains("_showSnack('Could not load files: \$e')")));
    expect(
      source,
      contains('Could not load files. Check your connection and try again.'),
    );
  });
  test('extracts clear file lookup commands only', () {
    expect(extractLocalFileLookupQuery('show me dodly'), 'dodly');
    expect(extractLocalFileLookupQuery('open my passport'), 'passport');
    expect(extractLocalFileLookupQuery('find road marking'), 'road marking');
    expect(extractLocalFileLookupQuery('when was my trip to USA'), isNull);
    expect(extractLocalFileLookupQuery('what files do I have'),
        localFileListAllQuery);
  });

  test('exact decrypted saved name wins over original filename', () {
    final match = resolveLocalVaultFileLookup(
      query: 'dodly',
      files: const [
        VaultLocalFileLookupEntry(
          id: 'a',
          fileName: 'JPEG_20260729_021122_842562634.jpg',
          savedName: 'dodly',
          mimeType: 'image/jpeg',
          assetType: 'image',
          sizeBytes: 20600,
        ),
      ],
    );

    expect(match, isNotNull);
    expect(match!.entry.id, 'a');
    expect(match.score, greaterThanOrEqualTo(120));
  });

  test('prefix and token matching are deterministic', () {
    final files = const [
      VaultLocalFileLookupEntry(
        id: 'road',
        fileName: 'Road_Marking_HSE_Plan_Template.docx',
        savedName: 'osun road marking',
        sizeBytes: 38000,
      ),
      VaultLocalFileLookupEntry(
        id: 'passport',
        fileName: 'passport.pdf',
        savedName: 'My Passport',
        sizeBytes: 12000,
      ),
    ];

    expect(
      resolveLocalVaultFileLookup(query: 'road marking', files: files)
          ?.entry
          .id,
      'road',
    );
    expect(
      resolveLocalVaultFileLookup(query: 'the HSE plan', files: files)
          ?.entry
          .id,
      'road',
    );
    expect(
      resolveLocalVaultFileLookup(query: 'my passport', files: files)?.entry.id,
      'passport',
    );
  });

  test(
      'duplicate exact names resolve deterministically without semantic fallthrough',
      () {
    final match = resolveLocalVaultFileLookup(
      query: 'passport',
      files: const [
        VaultLocalFileLookupEntry(
          id: 'a',
          fileName: 'passport.pdf',
          savedName: 'Passport',
          sizeBytes: 100,
        ),
        VaultLocalFileLookupEntry(
          id: 'b',
          fileName: 'passport-copy.pdf',
          savedName: 'Passport',
          sizeBytes: 100,
        ),
      ],
    );

    expect(match, isNotNull);
    expect(match!.entry.id, 'a');
    expect(
      shouldDeferLocalFileMissToSemanticSearch(
        query: 'passport',
        match: match,
      ),
      isFalse,
    );
  });

  test('any number of exact-name matches stays local and deterministic', () {
    final entries = List<VaultLocalFileLookupEntry>.generate(
      5,
      (index) => VaultLocalFileLookupEntry(
        id: 'juli-$index',
        fileName: 'capture-$index.jpg',
        savedName: 'juli',
        sizeBytes: 400000 + index,
      ),
    );
    final match = resolveLocalVaultFileLookup(query: 'juli', files: entries);
    expect(match, isNotNull);
    expect(match!.entry.id, 'juli-0');
    expect(
      shouldDeferLocalFileMissToSemanticSearch(query: 'juli', match: match),
      isFalse,
    );
  });

  test('content and person lookup miss defers to semantic vault search', () {
    final query = extractLocalFileLookupQuery(
      'find me DL of the name Louis Lodato',
    );
    expect(query, 'DL of the name Louis Lodato');
    final metadataOnlyMatch = resolveLocalVaultFileLookup(
      query: query!,
      files: const [
        VaultLocalFileLookupEntry(
          id: 'dl-image',
          fileName: 'Driver License-Lou.jpg',
          mimeType: 'image/jpeg',
          assetType: 'image',
          sizeBytes: 100,
        ),
      ],
    );
    expect(metadataOnlyMatch, isNull);
    expect(
      shouldDeferLocalFileMissToSemanticSearch(
        query: query,
        match: metadataOnlyMatch,
      ),
      isTrue,
    );
  });

  test('local metadata miss is non-terminal in both chat interceptors', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(
      source,
      contains('shouldDeferLocalFileMissToSemanticSearch('),
    );
    expect(
      source,
      contains('extractLocalFileLookupQuery(text) != null'),
    );
    expect(
      source,
      isNot(contains(
        'I could not identify one matching saved file. Add a more specific title or topic.',
      )),
    );
  });

  test('natural workplace document phrasing resolves synthetic file', () {
    final query = extractLocalFileLookupQuery('show my workplace document');
    expect(query, isNotNull);
    final match = resolveLocalVaultFileLookup(
      query: query!,
      files: const [
        VaultLocalFileLookupEntry(
          id: 'workplace',
          fileName: 'workplace_qa.txt',
          savedName: 'workplace_qa.txt',
          sizeBytes: 32,
        ),
      ],
    );
    expect(match?.entry.id, 'workplace',
        reason: 'file_natural_document_phrase_not_resolved_locally');
  });

  test('natural file wrapper matrix keeps topics and drops scaffolding', () {
    expect(extractLocalFileLookupQuery('find my workplace file'), 'workplace');
    expect(extractLocalFileLookupQuery('show me the file about my workplace'),
        'workplace');
    expect(
        extractLocalFileLookupQuery('show me for my workplace'), 'workplace');
    expect(extractLocalFileLookupQuery('find my travel file'), 'travel');
    expect(extractLocalFileLookupQuery('show my invoice'), 'invoice');
    expect(extractLocalFileLookupQuery('show all my documents'),
        localFileListAllQuery);
    expect(
        normalizeLocalFileLookupText('workplace_qa.txt'), 'workplace qa txt');
    expect(normalizeLocalFileLookupText('workplace_qa'), 'workplace');
  });
}
