import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/memory_title_identity.dart';
import 'package:vault_ai_frontend/services/vault_local_content_command.dart';

void main() {
  for (final phrase in [
    "save my mother's maiden name",
    "save my mother's maiden name is",
    'save my mother’s maiden name.',
    'please save my mom maiden name:',
    "remember my mother's maiden name",
  ]) {
    test('missing maiden value owns request without a save: $phrase', () {
      final command = parseVaultLocalMemorySaveCommand(phrase);
      expect(command, isNotNull);
      expect(command!.value, isEmpty);
      expect(command.validationError, contains('maiden name?'));
      expect(command.validationError, contains('Nothing was saved.'));
      expect(command.attribute, 'maiden_name');
      expect(command.toMemoryData().containsKey('password'), isFalse);
    });
  }

  for (final phrase in [
    "save my mother's maiden name SyntheticOnly",
    "save my mother's maiden name is SyntheticOnly",
    'save my mother’s maiden name SyntheticOnly',
    "save my mother's maiden name: SyntheticOnly",
    "save my mother's maiden name as SyntheticOnly",
    "save my mother's maiden name to be SyntheticOnly",
  ]) {
    test('supplied maiden value uses family memory only: $phrase', () {
      final command = parseVaultLocalMemorySaveCommand(phrase)!;
      expect(command.title, "Mother's maiden name");
      expect(command.value, 'SyntheticOnly');
      expect(command.validationError, isNull);
      expect(command.memoryType, 'family');
      expect(command.relationship, 'mother');
      expect(command.toMemoryData()['attribute'], 'maiden_name');
      expect(command.toMemoryData()['subject'], 'mother');
      expect(command.toMemoryData().containsKey('password'), isFalse);
      expect(command.toMemoryData().containsKey('username'), isFalse);
    });
  }

  for (final opening in ["what's", 'whats', 'what’s', 'what is']) {
    test('maiden recall $opening resolves the exact saved memory', () {
      final command =
          parseVaultLocalContentCommand("$opening my mother's maiden name")!;
      expect(command.kind, VaultLocalContentKind.memory);
      expect(command.action, VaultLocalContentAction.retrieve);
      expect(command.explicitKind, isTrue);
      expect(command.query, "Mother's maiden name");
      final match = resolveMemoryLocalContentMatch(
        query: command.query,
        entries: const [
          VaultLocalContentEntry(
              id: 'exact-memory', label: "Mother's maiden name"),
          VaultLocalContentEntry(id: 'other-memory', label: 'Mother birthday'),
        ],
      );
      expect(match?.entry.id, 'exact-memory');
    });
  }

  test('same-title memory duplicates still require exact-item selection', () {
    final command =
        parseVaultLocalContentCommand("whats my mother's maiden name")!;
    const rows = [
      VaultLocalContentEntry(id: 'first', label: "Mother's maiden name"),
      VaultLocalContentEntry(id: 'second', label: "Mother's maiden name"),
    ];
    expect(resolveMemoryLocalContentMatch(query: command.query, entries: rows),
        isNull);
    expect(memoryQueryIsAmbiguous(query: command.query, entries: rows), isTrue);
  });

  for (final phrase in [
    "save my mother's login username=qa password=synthetic",
    "save my mother's password is synthetic",
    "save my mother's maiden name as a login",
    "save my mother's maiden name login username=qa password=synthetic",
    "save my mother's maiden name password: synthetic",
    'generate a login for my mother',
    'save my github password as synthetic',
  ]) {
    test('explicit credential flow is not owned by maiden memory: $phrase', () {
      expect(parseVaultLocalMemorySaveCommand(phrase), isNull);
    });
  }

  test('long maiden value warns instead of silently truncating', () {
    final value = 'S' * 501;
    final command = parseVaultLocalMemorySaveCommand(
        "save my mother's maiden name $value")!;
    expect(command.value, value);
    expect(command.validationError, contains('Nothing was saved.'));
  });

  test('surname is-prefix is not mistaken for a connector', () {
    final command = parseVaultLocalMemorySaveCommand(
        "save my mother's maiden name Isabella")!;
    expect(command.value, 'Isabella');
    expect(command.validationError, isNull);
  });

  test('maiden handling does not widen contextual deletion or generic whats',
      () {
    expect(parseVaultLocalContentCommand('delete it'), isNull);
    expect(parseVaultLocalContentCommand('whats my github password'), isNull);
    final login = parseVaultLocalContentCommand("what's my github password")!;
    expect(login.kind, VaultLocalContentKind.login);
  });
}
