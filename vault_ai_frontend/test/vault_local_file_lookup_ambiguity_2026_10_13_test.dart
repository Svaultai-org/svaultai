import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_local_file_lookup.dart';

VaultLocalFileLookupEntry _file(
  String id, {
  String fileName = 'fixture.txt',
  String? savedName,
}) =>
    VaultLocalFileLookupEntry(
      id: id,
      fileName: fileName,
      savedName: savedName,
      sizeBytes: 352,
    );

void main() {
  test('duplicate saved names are ambiguous, not missing', () {
    final files = [
      _file('b', fileName: 'second.txt', savedName: 'QA duplicate'),
      _file('a', fileName: 'first.txt', savedName: 'QA duplicate'),
    ];
    final result =
        resolveLocalVaultFileLookupResult(query: 'QA duplicate', files: files);

    expect(result.status, VaultLocalFileLookupStatus.ambiguous);
    expect(result.isAmbiguous, isTrue);
    expect(result.match, isNull);
    expect(result.candidates.map((match) => match.entry.id), ['a', 'b']);
    expect(result.candidates.map((match) => match.score), [120, 120]);
    expect(
      resolveLocalVaultFileLookup(query: 'QA duplicate', files: files),
      isNull,
    );
  });

  test('duplicate original filenames with distinct IDs are ambiguous', () {
    final result = resolveLocalVaultFileLookupResult(
      query: 'QA-fixture.txt',
      files: [
        _file('a', fileName: 'QA-fixture.txt'),
        _file('b', fileName: 'QA-fixture.txt'),
      ],
    );

    expect(result.status, VaultLocalFileLookupStatus.ambiguous);
    expect(result.match, isNull);
    expect(result.candidates, hasLength(2));
  });

  test('equal partial scores never choose an arbitrary distinct file', () {
    final result = resolveLocalVaultFileLookupResult(
      query: 'QA document',
      files: [
        _file('b', savedName: 'QA document beta'),
        _file('a', savedName: 'QA document alpha'),
      ],
    );

    expect(result.status, VaultLocalFileLookupStatus.ambiguous);
    expect(result.match, isNull);
    expect(result.candidates.map((match) => match.entry.id), ['a', 'b']);
    expect(result.candidates.map((match) => match.score), [95, 95]);
  });

  test('the same stable ID repeated is one unique match', () {
    final file = _file('a', savedName: 'QA duplicate');
    final result = resolveLocalVaultFileLookupResult(
      query: 'QA duplicate',
      files: [file, file],
    );

    expect(result.status, VaultLocalFileLookupStatus.matched);
    expect(result.isAmbiguous, isFalse);
    expect(result.match?.entry.id, 'a');
    expect(result.candidates, hasLength(1));
  });

  test('repeated first ID cannot hide a later distinct tied ID', () {
    final file = _file('a', savedName: 'QA duplicate');
    final files = [file, file, _file('b', savedName: 'QA duplicate')];
    final result =
        resolveLocalVaultFileLookupResult(query: 'QA duplicate', files: files);

    expect(result.status, VaultLocalFileLookupStatus.ambiguous);
    expect(result.candidates.map((match) => match.entry.id), ['a', 'b']);
    expect(
      resolveLocalVaultFileLookup(query: 'QA duplicate', files: files),
      isNull,
    );
  });

  test('a unique exact match wins over multiple weaker matches', () {
    final files = [
      _file('weaker-a', savedName: 'QA record alpha'),
      _file('exact', savedName: 'QA record'),
      _file('weaker-b', savedName: 'QA record beta'),
    ];
    final result =
        resolveLocalVaultFileLookupResult(query: 'QA record', files: files);

    expect(result.status, VaultLocalFileLookupStatus.matched);
    expect(result.match?.entry.id, 'exact');
    expect(result.match?.score, 120);
    expect(result.candidates.map((match) => match.entry.id), ['exact']);
    expect(
      resolveLocalVaultFileLookup(query: 'QA record', files: files)?.entry.id,
      'exact',
    );
  });

  test('the strongest duplicate ID entry wins over a weaker copy', () {
    final result = resolveLocalVaultFileLookupResult(
      query: 'QA record',
      files: [
        _file('same-id', savedName: 'QA record alpha'),
        _file('same-id', savedName: 'QA record'),
        _file('weaker', savedName: 'QA record beta'),
      ],
    );

    expect(result.status, VaultLocalFileLookupStatus.matched);
    expect(result.match?.entry.id, 'same-id');
    expect(result.match?.entry.savedName, 'QA record');
    expect(result.match?.score, 120);
    expect(result.candidates, hasLength(1));
  });

  test('weaker duplicate copies do not hide a top-score distinct tie', () {
    final result = resolveLocalVaultFileLookupResult(
      query: 'QA record',
      files: [
        _file('a', savedName: 'QA record alpha'),
        _file('a', savedName: 'QA record'),
        _file('b', savedName: 'QA record'),
      ],
    );

    expect(result.status, VaultLocalFileLookupStatus.ambiguous);
    expect(result.candidates.map((match) => match.entry.id), ['a', 'b']);
    expect(result.candidates.map((match) => match.score), [120, 120]);
  });

  test('candidate order is deterministic for reversed input', () {
    final files = [
      _file('b', savedName: 'QA duplicate'),
      _file('a', savedName: 'QA duplicate'),
    ];
    final forward =
        resolveLocalVaultFileLookupResult(query: 'QA duplicate', files: files);
    final reverse = resolveLocalVaultFileLookupResult(
      query: 'QA duplicate',
      files: files.reversed,
    );

    expect(
      forward.candidates.map((match) => match.entry.id),
      reverse.candidates.map((match) => match.entry.id),
    );
    expect(forward.candidates.map((match) => match.entry.id), ['a', 'b']);
  });

  test('unknown name produces no-match rather than ambiguity', () {
    final files = [_file('a', savedName: 'QA known')];
    final result = resolveLocalVaultFileLookupResult(
      query: 'completely unknown document',
      files: files,
    );

    expect(result.status, VaultLocalFileLookupStatus.noMatch);
    expect(result.isAmbiguous, isFalse);
    expect(result.match, isNull);
    expect(result.candidates, isEmpty);
    expect(
      resolveLocalVaultFileLookup(
        query: 'completely unknown document',
        files: files,
      ),
      isNull,
    );
  });

  for (final query in ['', '   ', '!!!', '"`\'']) {
    test('empty normalized query "$query" is no-match', () {
      final result = resolveLocalVaultFileLookupResult(
        query: query,
        files: [_file('a', savedName: 'QA known')],
      );

      expect(result.status, VaultLocalFileLookupStatus.noMatch);
      expect(result.match, isNull);
      expect(result.candidates, isEmpty);
    });
  }

  test('empty inventory is no-match', () {
    final result = resolveLocalVaultFileLookupResult(
      query: 'QA fixture',
      files: const [],
    );

    expect(result.status, VaultLocalFileLookupStatus.noMatch);
    expect(result.match, isNull);
    expect(result.candidates, isEmpty);
  });

  test('result candidates cannot be modified by a caller', () {
    final result = resolveLocalVaultFileLookupResult(
      query: 'QA duplicate',
      files: [
        _file('a', savedName: 'QA duplicate'),
        _file('b', savedName: 'QA duplicate'),
      ],
    );

    expect(() => result.candidates.clear(), throwsUnsupportedError);
    expect(result.status, VaultLocalFileLookupStatus.ambiguous);
    expect(result.candidates, hasLength(2));
  });

  test('clear retrieval query extraction is unchanged', () {
    expect(
      extractLocalFileLookupQuery('Show me the file QA-fixture.txt.'),
      'QA-fixture.txt',
    );
    expect(
      extractLocalFileLookupQuery('open my "QA duplicate"'),
      '"QA duplicate"',
    );
    expect(extractLocalFileLookupQuery('download my QA record'), 'QA record');
    expect(extractLocalFileLookupQuery('view document QA record'), 'QA record');
    expect(extractLocalFileLookupQuery('show my file'), isNull);
    expect(extractLocalFileLookupQuery('what files do I have?'), isNull);
    expect(extractLocalFileLookupQuery('rename QA record to Updated'), isNull);
    expect(extractLocalFileLookupQuery('delete QA record'), isNull);
  });
}
