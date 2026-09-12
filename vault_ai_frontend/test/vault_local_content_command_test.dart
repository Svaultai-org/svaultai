import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_local_content_command.dart';

void main() {
  test('parses login retrieval and deletion without misrouting to memory', () {
    final retrieve = parseVaultLocalContentCommand('Show me my GitHub login');
    expect(retrieve?.kind, VaultLocalContentKind.login);
    expect(retrieve?.action, VaultLocalContentAction.retrieve);
    expect(retrieve?.query, 'GitHub');

    final remove = parseVaultLocalContentCommand('Delete my Generated login');
    expect(remove?.kind, VaultLocalContentKind.login);
    expect(remove?.action, VaultLocalContentAction.delete);
    expect(remove?.query, 'Generated');
  });

  test('parses explicit and natural memory queries', () {
    final recall = parseVaultLocalContentCommand(
      'What is the Project Atlas launch date?',
    );
    expect(recall?.kind, VaultLocalContentKind.memory);
    expect(recall?.action, VaultLocalContentAction.retrieve);
    expect(recall?.explicitKind, isFalse);
    expect(recall?.query, 'Project Atlas launch date');

    final remove = parseVaultLocalContentCommand(
      'Forget the Project Atlas launch date memory',
    );
    expect(remove?.kind, VaultLocalContentKind.memory);
    expect(remove?.action, VaultLocalContentAction.delete);
    expect(remove?.query, 'Project Atlas launch date');

    final birthday = parseVaultLocalContentCommand(
      'Delete my mom birthday memory',
    );
    expect(birthday?.query, 'mom birthday');
  });

  test('parses named file deletion', () {
    final command =
        parseVaultLocalContentCommand('Delete my file Atlas brief.pdf');
    expect(command?.kind, VaultLocalContentKind.file);
    expect(command?.action, VaultLocalContentAction.delete);
    expect(command?.query, 'Atlas brief.pdf');
  });

  test('matches a natural question strongly against a memory title', () {
    final match = resolveVaultLocalContentMatch(
      query: 'the Project Atlas launch date',
      entries: const <VaultLocalContentEntry>[
        VaultLocalContentEntry(
          id: 'atlas',
          label: 'Project Atlas launch date',
        ),
        VaultLocalContentEntry(id: 'wifi', label: 'Home Wi-Fi'),
      ],
    );
    expect(match?.entry.id, 'atlas');
  });

  test('matches a generic memory title through its decrypted value', () {
    final match = resolveVaultLocalContentMatch(
      query: 'Project Orion launch date',
      entries: const <VaultLocalContentEntry>[
        VaultLocalContentEntry(
          id: 'orion',
          label: 'Personal note',
          aliases: <String>[
            'Project Orion launch date is April 9, 2032',
          ],
        ),
      ],
    );
    expect(match?.entry.id, 'orion');
  });

  test('does not guess between equally named encrypted records', () {
    final match = resolveVaultLocalContentMatch(
      query: 'GitHub',
      entries: const <VaultLocalContentEntry>[
        VaultLocalContentEntry(id: '1', label: 'GitHub'),
        VaultLocalContentEntry(id: '2', label: 'GitHub'),
      ],
    );
    expect(match, isNull);
  });

  test('recognizes confirmation and cancellation replies exactly', () {
    expect(isVaultLocalDeleteConfirmation('yes, delete it'), isTrue);
    expect(isVaultLocalDeleteConfirmation('delete GitHub'), isFalse);
    expect(isVaultLocalDeleteCancellation('keep it'), isTrue);
    expect(isVaultLocalDeleteCancellation('no thanks later'), isFalse);
  });
}
