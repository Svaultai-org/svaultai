import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show
        isClientSecureItemDeleteConfirmationPhrase,
        isClientSecureItemDeleteCancellationPhrase;
import 'package:vault_ai_frontend/services/vault_local_content_command.dart';

void main() {
  group('selected-item delete confirmation replies', () {
    for (final reply in [
      'yes',
      'yep',
      'Yes, delete it.',
      'yes delete it',
      'Yep, delete it!!!',
      ' YES , please delete it. ',
      'confirm delete',
      'delete it',
      'go ahead and delete it',
      'do it',
    ]) {
      test('accepts bounded confirmation: $reply', () {
        expect(isClientSecureItemDeleteConfirmationPhrase(reply), isTrue);
        expect(isVaultLocalDeleteConfirmation(reply), isTrue);
        expect(isClientSecureItemDeleteCancellationPhrase(reply), isFalse);
      });
    }
    for (final reply in [
      'no',
      'Cancel.',
      'No, keep it.',
      'nope!!!',
      "don't delete it",
      'don’t delete it.',
      'stop',
    ]) {
      test('cancels without confirmation: $reply', () {
        expect(isClientSecureItemDeleteCancellationPhrase(reply), isTrue);
        expect(isVaultLocalDeleteCancellation(reply), isTrue);
        expect(isClientSecureItemDeleteConfirmationPhrase(reply), isFalse);
      });
    }
    for (final reply in [
      'yes, delete another login',
      'yes, do not delete it',
      'yes and create a new login',
      'delete Library login',
      'yesterday',
      'I said yes before',
      'not yes',
    ]) {
      test('does not broaden consent: $reply', () {
        expect(isClientSecureItemDeleteConfirmationPhrase(reply), isFalse);
        expect(isVaultLocalDeleteConfirmation(reply), isFalse);
      });
    }
    for (final reply in [
      'Yes, delete it.',
      'yep, delete it!',
      "don't delete it"
    ]) {
      test('context reply is never a new Memory command: $reply', () {
        expect(parseVaultLocalContentCommand(reply), isNull);
      });
    }
  });
}
