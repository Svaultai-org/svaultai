import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/credential_v2.dart';
import 'package:vault_ai_frontend/services/credential_v2_repository.dart';

DecryptedCredentialV2Record credential(String id, String service) =>
    DecryptedCredentialV2Record(
      id,
      CredentialV2Plaintext(
        service: service,
        username: 'synthetic-user',
        password: 'synthetic-secret',
      ),
    );

void main() {
  final facebook = credential('credential-facebook-synthetic', 'Facebook');

  group('credential natural-language lookup normalization', () {
    final variants = <String, CredentialV2RequestedField>{
      'show me my facebook login': CredentialV2RequestedField.summary,
      'what is my facebook login': CredentialV2RequestedField.summary,
      "what's my facebook login": CredentialV2RequestedField.summary,
      'what are my facebook login details': CredentialV2RequestedField.summary,
      'give me my facebook login': CredentialV2RequestedField.summary,
      'get my facebook login': CredentialV2RequestedField.summary,
      'find my facebook login': CredentialV2RequestedField.summary,
      'my facebook login': CredentialV2RequestedField.summary,
      'facebook login': CredentialV2RequestedField.summary,
      'do i have a facebook login': CredentialV2RequestedField.summary,
      'what username did i save for facebook':
          CredentialV2RequestedField.username,
      'what is my facebook username': CredentialV2RequestedField.username,
      "what's the password for my facebook login":
          CredentialV2RequestedField.password,
      'what is my facebook password': CredentialV2RequestedField.password,
      'show my facebook credentials': CredentialV2RequestedField.summary,
      'can you show me my facebook account details':
          CredentialV2RequestedField.summary,
      'can you find my facebook credential': CredentialV2RequestedField.summary,
      'where is my facebook login': CredentialV2RequestedField.summary,
    };

    for (final entry in variants.entries) {
      test('resolves: ${entry.key}', () {
        final intent = parseCredentialV2LookupIntent(entry.key);

        expect(intent, isNotNull);
        expect(intent!.listAll, isFalse);
        expect(intent.service!.toLowerCase(), 'facebook');
        expect(intent.requestedField, entry.value);
        expect(shouldAttemptCredentialV2Lookup(entry.key), isTrue);
        expect(
          matchCredentialV2RecordsForService(intent.service!, [facebook])
              .map((record) => record.recordId),
          ['credential-facebook-synthetic'],
        );
      });
    }

    test('capitalization punctuation and item-type variants are invariant', () {
      for (final text in <String>[
        'WHAT IS MY FACEBOOK LOGIN?!',
        'What is my Facebook logins?',
        'What are my Facebook credentials?',
        'Tell me my Facebook account details.',
      ]) {
        final intent = parseCredentialV2LookupIntent(text);
        expect(intent?.service?.toLowerCase(), 'facebook', reason: text);
        expect(
          matchCredentialV2RecordsForService(intent!.service!, [facebook])
              .single
              .recordId,
          'credential-facebook-synthetic',
          reason: text,
        );
      }
    });

    test('a unique one-edit typo resolves without weakening opaque IDs', () {
      expect(
        matchCredentialV2RecordsForService('Facebok', [facebook])
            .single
            .recordId,
        'credential-facebook-synthetic',
      );
      expect(
        matchCredentialV2RecordsForService(
          'qa-nova-9315',
          [credential('credential-unrelated', 'Nova46880')],
        ),
        isEmpty,
      );
    });

    test('parent service labels remain ambiguous instead of picking one', () {
      final matches = matchCredentialV2RecordsForService('Facebook', [
        credential('credential-facebook-personal', 'Facebook Personal'),
        credential('credential-facebook-business', 'Facebook Business'),
      ]);

      expect(matches.map((record) => record.recordId), {
        'credential-facebook-personal',
        'credential-facebook-business',
      });
    });

    test('no matching service retains the no-match outcome', () {
      expect(
        matchCredentialV2RecordsForService('Facebook', [
          credential('credential-github', 'GitHub'),
        ]),
        isEmpty,
      );
    });

    test('password response requires an explicit reveal action', () {
      final reply = credentialV2LookupReply(
        'Facebook',
        CredentialV2RequestedField.password,
      );

      expect(reply, contains('Reveal password'));
      expect(reply, isNot(contains('synthetic-secret')));
    });
  });

  group('credential intent boundaries', () {
    test('non-credential intents remain outside credential lookup', () {
      for (final text in <String>[
        "what is my mother's name",
        'what is my passport number',
        'what is facebook',
        'show me facebook.pdf',
      ]) {
        expect(parseCredentialV2LookupIntent(text), isNull, reason: text);
        expect(shouldAttemptCredentialV2Lookup(text), isFalse, reason: text);
      }
    });

    test('create and save requests remain creation intents', () {
      for (final text in <String>[
        'create me a facebook login',
        'create me a facebook logins',
        'save my facebook login',
      ]) {
        expect(parseCredentialV2CreateIntent(text)?.service?.toLowerCase(),
            'facebook',
            reason: text);
        expect(parseCredentialV2LookupIntent(text), isNull, reason: text);
        expect(shouldAttemptCredentialV2Lookup(text), isFalse, reason: text);
      }
    });

    test('possessive give request is retrieval, not creation', () {
      const text = 'give me my facebook login';
      expect(parseCredentialV2CreateIntent(text), isNull);
      expect(parseCredentialV2LookupIntent(text)?.service, 'facebook');
    });

    test('saved credential inventory requests still list all', () {
      for (final text in <String>[
        'show me my saved logins',
        'what are my saved credentials',
      ]) {
        expect(parseCredentialV2LookupIntent(text)?.listAll, isTrue);
      }
    });
  });
}
