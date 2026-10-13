import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_local_content_command.dart';

void main() {
  test('reported structured memory command preserves title and content', () {
    const phrase =
        'Save a new memory with title QA-TEST-B1-memory and content: QA-TEST B1 content alpha';
    final command = parseVaultLocalMemorySaveCommand(phrase);
    expect(command, isNotNull);
    expect(command!.title, 'QA-TEST-B1-memory');
    expect(command.value, 'QA-TEST B1 content alpha');
    expect(command.toMemoryData()['memory_key'], 'QA-TEST-B1-memory');
    expect(command.toMemoryData()['body'], 'QA-TEST B1 content alpha');
    expect(command.toMemoryData().containsKey('password'), isFalse);
  });

  test('explicit memory kind beats words in its title and content', () {
    for (final phrase in [
      'Create a memory titled Login checklist with content: Review the account.',
      'Please save memory with title 東京 and content: メモ 🔒',
    ]) {
      final command = parseVaultLocalMemorySaveCommand(phrase);
      expect(command, isNotNull, reason: phrase);
      expect(command!.memoryType, 'note');
      expect(command.relationship, 'self');
    }
  });

  test(
      'content punctuation and Unicode are preserved, not inferred as commands',
      () {
    const value =
        'Keep this: delete the OLD note; login checklist 🔒\nNext line.';
    final command = parseVaultLocalMemorySaveCommand(
      'Save a new memory with title Note!? and content: $value',
    );
    expect(command!.title, 'Note!?');
    expect(command.value, value);
  });

  test('incomplete named memory still owns the request for visible validation',
      () {
    final command = parseVaultLocalMemorySaveCommand(
      'Save a memory with title Example and content:',
    );
    expect(command, isNotNull);
    expect(command!.value, isEmpty);
    expect(command.validationError, contains('Nothing was saved.'));
    for (final phrase in [
      'Save a memory with title Example',
      'Create a memory titled Example',
      'Save memory with title Example',
    ]) {
      expect(parseVaultLocalMemorySaveCommand(phrase)!.validationError,
          contains('Add a memory title and content'));
    }
  });

  test('named bounds reject visibly without truncating original fields', () {
    final allowed = parseVaultLocalMemorySaveCommand(
      'Save a memory titled ${'T' * 120} with content: ${'C' * 500}',
    )!;
    expect(allowed.validationError, isNull);
    expect(allowed.value, 'C' * 500);
    for (final pair in [
      ['T' * 121, 'C'],
      ['T', 'C' * 501],
      ['T', 'C' * 2200],
    ]) {
      final command = parseVaultLocalMemorySaveCommand(
        'Save a memory titled ${pair[0]} with content: ${pair[1]}',
      )!;
      expect(command.validationError, contains('Nothing was saved.'));
      expect(command.title, pair[0]);
      expect(command.value, pair[1]);
    }
    final unicode = parseVaultLocalMemorySaveCommand(
      'Save a memory titled ${'🔒' * 120} with content: ${'🔒' * 500}',
    )!;
    expect(unicode.validationError, isNull);
  });

  test('login, file, ordinary prose and quoted commands do not become memory',
      () {
    for (final phrase in [
      'Create a login with title Example and content: username example',
      'Create a file named Example with content: hello',
      'What does save a new memory with title Example and content: hello mean?',
      'Previous message: Save a new memory with title Example and content: hello',
    ]) {
      expect(parseVaultLocalMemorySaveCommand(phrase), isNull, reason: phrase);
    }
  });
}
