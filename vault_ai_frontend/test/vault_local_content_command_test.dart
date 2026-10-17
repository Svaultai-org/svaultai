import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/l10n/app_localizations_en.dart';
import 'package:vault_ai_frontend/services/vault_local_content_command.dart';

void main() {
  test('actual memory-card question preserves and resolves its exact title',
      () {
    const title = 'QA-TEST Memory One';
    final question = AppLocalizationsEn().memoryAskAbout(title);
    final command = parseVaultLocalContentCommand(question);

    expect(question, 'What do you remember about $title?');
    expect(command?.kind, VaultLocalContentKind.memory);
    expect(command?.action, VaultLocalContentAction.retrieve);
    expect(command?.query, title);
    final match = resolveVaultLocalContentMatch(
      query: command!.query,
      entries: const [
        VaultLocalContentEntry(id: 'selected', label: title),
        VaultLocalContentEntry(id: 'different', label: 'QA-TEST One'),
      ],
    );
    expect(match?.entry.id, 'selected');
  });

  test('memory-card title words cannot select another kind or deletion', () {
    for (final title in const [
      'Login recovery note',
      'Vacation photo',
      'Delete checklist',
      'Launch date?!',
    ]) {
      final command = parseVaultLocalContentCommand(
        AppLocalizationsEn().memoryAskAbout(title),
      );
      expect(command?.kind, VaultLocalContentKind.memory, reason: title);
      expect(command?.action, VaultLocalContentAction.retrieve, reason: title);
      expect(command?.query, title, reason: title);
    }
    expect(
      parseVaultLocalContentCommand('What do you remember about ?'),
      isNull,
    );
  });

  test('parses login retrieval and deletion without misrouting to memory', () {
    final retrieve = parseVaultLocalContentCommand('Show me my GitHub login');
    expect(retrieve?.kind, VaultLocalContentKind.login);
    expect(retrieve?.action, VaultLocalContentAction.retrieve);
    expect(retrieve?.query, 'GitHub');

    final remove = parseVaultLocalContentCommand('Delete my Generated login');
    expect(remove?.kind, VaultLocalContentKind.login);
    expect(remove?.action, VaultLocalContentAction.delete);
    expect(remove?.query, 'Generated');

    final nord = parseVaultLocalContentCommand('Show my nord vpn login');
    expect(nord?.kind, VaultLocalContentKind.login);
    expect(nord?.action, VaultLocalContentAction.retrieve);
    expect(nord?.query, 'nord vpn');

    final facebook = parseVaultLocalContentCommand('Show me facebook login');
    expect(facebook?.kind, VaultLocalContentKind.login);
    expect(facebook?.action, VaultLocalContentAction.retrieve);
    expect(facebook?.query, 'facebook');

    final wife = parseVaultLocalContentCommand(
      'Delete wife login from my vault',
    );
    expect(wife?.kind, VaultLocalContentKind.login);
    expect(wife?.action, VaultLocalContentAction.delete);
    expect(wife?.query, 'wife');
  });

  test('parses an explicit personal fact as an encrypted memory save', () {
    final command = parseVaultLocalMemorySaveCommand(
      'save my wife name to be rachael habtu',
    );
    expect(command, isNotNull);
    expect(command?.title, 'Wife name');
    expect(command?.value, 'rachael habtu');
    expect(command?.memoryType, 'family');
    expect(command?.relationship, 'wife');
    expect(command?.toMemoryData()['memory_type'], 'family');

    final friend = parseVaultLocalMemorySaveCommand(
      'save my friend name Rashida Jones',
    );
    expect(friend, isNotNull);
    expect(friend?.title, 'Friend name');
    expect(friend?.value, 'Rashida Jones');
    expect(friend?.memoryType, 'relationship');
    expect(friend?.relationship, 'friend');
  });

  test('never downgrades credentials or recovery data into a memory', () {
    for (final phrase in <String>[
      'save my wife login as rachael',
      'save my github password as hunter2',
      'remember my recovery code is abc123',
      'save my pin to be 123456',
    ]) {
      expect(
        parseVaultLocalMemorySaveCommand(phrase),
        isNull,
        reason: phrase,
      );
    }
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

  test('date questions recall a strong local memory without a special prompt',
      () {
    for (final opening in const [
      'What date is',
      'What day is',
      'What time is',
      'Please WHAT DATE IS',
    ]) {
      final command = parseVaultLocalContentCommand(
        '$opening the demo library card renewal?',
      );
      expect(command?.kind, VaultLocalContentKind.memory, reason: opening);
      expect(command?.action, VaultLocalContentAction.retrieve,
          reason: opening);
      expect(command?.explicitKind, isFalse, reason: opening);
      expect(command?.query, 'demo library card renewal', reason: opening);
      expect(
        resolveVaultLocalContentMatch(
          query: command!.query,
          entries: const [
            VaultLocalContentEntry(id: 'other', label: 'Garden visit'),
            VaultLocalContentEntry(
                id: 'library', label: 'Demo library renewal'),
          ],
        )?.entry.id,
        'library',
        reason: opening,
      );
    }
  });

  test('date questions do not invent missing or ambiguous saved memories', () {
    final command = parseVaultLocalContentCommand(
      'What date is the demo library card renewal?',
    )!;
    expect(
      resolveVaultLocalContentMatch(
        query: command.query,
        entries: const [
          VaultLocalContentEntry(id: 'other', label: 'Garden visit')
        ],
      ),
      isNull,
    );
    expect(
      resolveVaultLocalContentMatch(
        query: command.query,
        entries: const [
          VaultLocalContentEntry(id: 'first', label: 'Demo library renewal'),
          VaultLocalContentEntry(id: 'second', label: 'Demo library renewal'),
        ],
      ),
      isNull,
    );
    expect(parseVaultLocalContentCommand('What date format should I use?'),
        isNull);
  });

  test('parses named file deletion', () {
    final command =
        parseVaultLocalContentCommand('Delete my file Atlas brief.pdf');
    expect(command?.kind, VaultLocalContentKind.file);
    expect(command?.action, VaultLocalContentAction.delete);
    expect(command?.query, 'Atlas brief.pdf');
  });

  test('leaves contextual deletion to the selected-item handler', () {
    for (final phrase in const [
      'delete it',
      'Please remove it.',
      'erase that',
      'forget this',
      'delete this one from my vault',
      'delete the selected item',
      'remove that record please',
      'delete',
    ]) {
      expect(parseVaultLocalContentCommand(phrase), isNull, reason: phrase);
    }
  });

  test('retains explicit and named memory deletion and pending confirmations',
      () {
    for (final phrase in const [
      'Delete my Project Atlas memory',
      'Delete Project Atlas',
    ]) {
      final command = parseVaultLocalContentCommand(phrase);
      expect(command?.kind, VaultLocalContentKind.memory, reason: phrase);
      expect(command?.action, VaultLocalContentAction.delete, reason: phrase);
      expect(command?.query, 'Project Atlas', reason: phrase);
    }
    final explicit = parseVaultLocalContentCommand('Delete this memory');
    expect(explicit?.kind, VaultLocalContentKind.memory);
    expect(explicit?.explicitKind, isTrue);
    expect(isVaultLocalDeleteConfirmation('yes, delete it'), isTrue);
    expect(isVaultLocalDeleteConfirmation('delete'), isTrue);
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

  test('never returns an unrelated login for a no-match query', () {
    final match = resolveVaultLocalContentMatch(
      query: 'nord vpn',
      entries: const <VaultLocalContentEntry>[
        VaultLocalContentEntry(id: 'wife', label: 'wife'),
      ],
    );
    expect(match, isNull);
  });

  test('selects the correct legacy login when list rows have no ids', () {
    final index = resolveVaultLocalContentLabelIndex(
      query: 'facebook',
      labels: const <String>[
        'nord vpn',
        'instagram',
        'facebook',
      ],
    );
    expect(index, 2);

    final noMatch = resolveVaultLocalContentLabelIndex(
      query: 'linkedin',
      labels: const <String>['nord vpn', 'facebook'],
    );
    expect(noMatch, isNull);
  });

  test('missing specific login never falls back to a shorter title', () {
    final command = parseVaultLocalContentCommand(
      'Show my QA-TEST iPhone Final login',
    )!;
    expect(command.query, 'QA-TEST iPhone Final');
    for (final labels in const [
      ['QA-TEST iPhone'],
      ['QA-TEST iPhone', 'QA-TEST iPhone Backup'],
    ]) {
      expect(
        resolveVaultLocalContentLabelIndex(
          query: command.query,
          labels: labels,
        ),
        isNull,
      );
    }
  });

  test('specific exact login wins and stays absent after deletion', () {
    final labels = ['QA-TEST iPhone', 'QA-TEST iPhone Final'];
    final selected = resolveVaultLocalContentLabelIndex(
      query: 'QA-TEST iPhone Final',
      labels: labels,
    );
    expect(selected, 1);
    labels.removeAt(selected!);
    expect(labels, ['QA-TEST iPhone']);
    expect(
      resolveVaultLocalContentLabelIndex(
        query: 'QA-TEST iPhone Final',
        labels: labels,
      ),
      isNull,
    );
    expect(
      resolveVaultLocalContentLabelIndex(
        query: 'QA-TEST iPhone',
        labels: labels,
      ),
      0,
    );
  });

  test('distinct qualifier and number queries cannot use substring matches',
      () {
    for (final query in const [
      'QA-TEST iPhone Final',
      'QA-TEST iPhone 1',
      'QA-TEST iPhone Work',
    ]) {
      expect(
        resolveVaultLocalContentLabelIndex(
          query: query,
          labels: const [
            'QA-TEST iPhone',
            'QA-TEST iPhone Finalist',
            'QA-TEST iPhone 12',
            'QA-TEST iPhone Personal',
          ],
        ),
        isNull,
        reason: query,
      );
    }
  });

  test('login normalization preserves Nord VPN casing punctuation and spacing',
      () {
    for (final message in const [
      'Show my nord vpn login',
      'SHOW my "NORD-VPN" login!',
      'Show my nord_vpn login',
      'Show my NordVPN login',
      'Show my Nord  VPN login',
    ]) {
      final command = parseVaultLocalContentCommand(message)!;
      expect(
        resolveVaultLocalContentLabelIndex(
          query: command.query,
          labels: const ['wife', 'NordVPN', 'facebook'],
        ),
        1,
        reason: message,
      );
    }
  });

  test('equivalent normalized login titles stay ambiguous', () {
    for (final labels in const [
      ['NordVPN', 'Nord VPN'],
      ['QA-TEST iPhone Final', 'qa_test iphone final'],
    ]) {
      expect(
        resolveVaultLocalContentLabelIndex(
          query: labels.first,
          labels: labels,
        ),
        isNull,
      );
    }
  });

  test('unique full-token partial login queries remain supported', () {
    expect(
      resolveVaultLocalContentLabelIndex(
        query: 'GitHub',
        labels: const ['Personal GitHub', 'Facebook'],
      ),
      0,
    );
    expect(
      resolveVaultLocalContentLabelIndex(
        query: 'the Project Atlas',
        labels: const ['Project Atlas Work', 'Project Orion'],
      ),
      0,
    );
  });

  test('ambiguous partial login queries never pick a ranked winner', () {
    expect(
      resolveVaultLocalContentLabelIndex(
        query: 'GitHub',
        labels: const ['Personal GitHub', 'GitHub Work'],
      ),
      isNull,
    );
    expect(
      resolveVaultLocalContentLabelIndex(
        query: 'QA-TEST',
        labels: const ['QA-TEST iPhone', 'QA-TEST iPhone Final'],
      ),
      isNull,
    );
  });

  test('recognizes confirmation and cancellation replies exactly', () {
    expect(isVaultLocalDeleteConfirmation('yes, delete it'), isTrue);
    expect(isVaultLocalDeleteConfirmation('delete GitHub'), isFalse);
    expect(isVaultLocalDeleteCancellation('keep it'), isTrue);
    expect(isVaultLocalDeleteCancellation('no thanks later'), isFalse);
  });
}
