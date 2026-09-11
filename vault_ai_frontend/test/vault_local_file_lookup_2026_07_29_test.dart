import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_local_file_lookup.dart';

void main() {
  test('extracts clear file lookup commands only', () {
    expect(extractLocalFileLookupQuery('show me dodly'), 'dodly');
    expect(extractLocalFileLookupQuery('open my passport'), 'passport');
    expect(extractLocalFileLookupQuery('find road marking'), 'road marking');
    expect(extractLocalFileLookupQuery('when was my trip to USA'), isNull);
    expect(extractLocalFileLookupQuery('what files do I have'), isNull);
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

  test('ambiguous equal matches fall through to backend search', () {
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

    expect(match, isNull);
  });
}
