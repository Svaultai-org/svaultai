import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/credential_v2.dart';
import 'package:vault_ai_frontend/services/credential_v2_repository.dart';

DecryptedCredentialV2Record _credential(String service) =>
    DecryptedCredentialV2Record(
      'record-$service',
      CredentialV2Plaintext(
        service: service,
        username: 'synthetic-user',
        password: 'synthetic-secret',
      ),
    );

void main() {
  test('contextual memory fact extraction is topic-agnostic', () {
    const cases = <String, List<String>>{
      'my mother name is Lodato': ['mother name', 'Lodato'],
      'my favorite color is ultraviolet': ['favorite color', 'ultraviolet'],
      'my project nickname is Blue Comet': ['project nickname', 'Blue Comet'],
      'my launch date is 2041-09-18': ['launch date', '2041-09-18'],
      'my recovery code is AX-19-Z': ['recovery code', 'AX-19-Z'],
      'my sister city is Accra': ['sister city', 'Accra'],
      'my coffee preference is oat flat white': [
        'coffee preference',
        'oat flat white'
      ],
      'my meeting room is Cedar': ['meeting room', 'Cedar'],
      'my dog name is Pixel': ['dog name', 'Pixel'],
      'my anniversary is April 7': ['anniversary', 'April 7'],
      'my tax note is keep the paper copy': ['tax note', 'keep the paper copy'],
      'my demo password hint is violet bird': [
        'demo password hint',
        'violet bird'
      ],
      'my book preference is science fiction': [
        'book preference',
        'science fiction'
      ],
      'my travel code is Q7-MAP': ['travel code', 'Q7-MAP'],
      'my team nickname is Lantern': ['team nickname', 'Lantern'],
      'my father birthday is June 3': ['father birthday', 'June 3'],
      'my aunt phone label is Red Phone': ['aunt phone label', 'Red Phone'],
      'my garden note is water on Tuesday': ['garden note', 'water on Tuesday'],
      'my client alias is Northstar': ['client alias', 'Northstar'],
      'my free form note is bring the blue folder': [
        'free form note',
        'bring the blue folder'
      ],
    };
    for (final entry in cases.entries) {
      final fact = parseLocalMemoryFact(entry.key);
      expect(fact?.subject, entry.value[0], reason: entry.key);
      expect(fact?.value, entry.value[1], reason: entry.key);
    }
    expect(parseLocalMemoryContextSaveSubject('remember that'), '');
    expect(parseLocalMemoryContextSaveSubject('remember my mother name'),
        'mother name');
  });
  test('mother name memory paraphrases resolve from generalized topic terms',
      () {
    const rows = <Map<String, dynamic>>[
      {
        'id': 'memory-random',
        'title': "Mother's name",
        'memory_type': 'personal',
        'value': 'Lodato',
        'tags': <String>['family', 'mother', 'name'],
      },
    ];
    for (final wording in <String>[
      "what is my mother's name",
      "what did I tell you my mother's name was",
      "do you remember my mother's name",
      'what name did I save for my mother',
    ]) {
      final intent = parseLocalMemoryLookupIntent(wording);
      expect(intent, isNotNull, reason: wording);
      final result = matchLocalMemoryRecords(intent!, rows);
      expect(result.records.single['value'], 'Lodato', reason: wording);
    }
  });
  test('generic saved-for paraphrase stays on local memory routing', () {
    final intent =
        parseLocalMemoryLookupIntent('what phrase did I save for reactivation');
    expect(intent, isNotNull);
    expect(intent!.subject, 'reactivation phrase');
  });
  test('natural private wording extracts an inventory topic', () {
    const cases = <String, String>{
      'show my QA Social Example': 'QA Social Example',
      'show me QA Social Example': 'QA Social Example',
      'what is my QA Social Example': 'QA Social Example',
      "what's my QA Social Example": 'QA Social Example',
      'get my QA Social Example': 'QA Social Example',
      'QA Social Example': 'QA Social Example',
      'what was my meeting code': 'meeting code',
      'what is the CobaltHarbor7421 codeword': 'CobaltHarbor7421 codeword',
      'show my invoice': 'invoice',
    };
    for (final entry in cases.entries) {
      expect(extractInventoryPrivateLookupTopic(entry.key), entry.value);
    }
  });

  test('explicit crypto questions bypass private inventory arbitration', () {
    expect(extractInventoryPrivateLookupTopic('What is my ETH balance?'), isNull);
    expect(
      extractInventoryPrivateLookupTopic('Show my USDT receive address'),
      isNull,
    );
    expect(
      extractInventoryPrivateLookupTopic(
        'Help me choose a job with better work-life balance',
      ),
      isNull,
    );
    expect(parseLocalMemoryLookupIntent('What is my ETH balance?'), isNull);
  });

  test('memory delete is handled before recall arbitration', () {
    final source = File('lib/main.dart').readAsStringSync();
    final deleteRoute = source.indexOf('final memoryDeleteMatch = RegExp(');
    final arbitrationCall = source.indexOf(
      'if (await _tryLocalPrivateDomainArbitration(text, app))',
    );
    expect(deleteRoute, greaterThanOrEqualTo(0));
    expect(arbitrationCall, greaterThan(deleteRoute));
    expect(source, contains("Deleted the saved \$memorySubject memory."));
  });

  test('paraphrased codeword recall is treated as a memory lookup', () {
    final intent =
        parseLocalMemoryLookupIntent('what is the CobaltHarbor7421 codeword');
    expect(intent, isNotNull);
    expect(intent!.subject, 'CobaltHarbor7421 codeword');
    final matches = matchLocalMemoryRecords(intent, [
      {
        'title': 'CobaltHarbor7421',
        'memory_type': 'note',
        'tags': <String>[],
        'value': 'SilverLark7421',
      },
    ]);
    expect(matches.records, hasLength(1));
  });

  test('bare greeting remains eligible for general chat without inventory', () {
    expect(extractInventoryPrivateLookupTopic('hey'), 'hey');
    expect(matchCredentialV2RecordsForText('hey', const []), isEmpty);

    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('final credentialRepository =');
    final end = source.indexOf('Future<void> loadLegacyCredentials()', start);
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final credentialRead = source.substring(start, end);
    expect(credentialRead, contains('try {'));
    expect(credentialRead, contains('credentialRepository.listDecrypted()'));
    expect(credentialRead, contains('catch (_)'));
    expect(credentialRead,
        contains('credentials = const <DecryptedCredentialV2Record>[]'));
  });

  test('saved metadata supplies vocabulary without service hardcoding', () {
    final records = [
      _credential('QA Social Example'),
      _credential('Nebula Orchard'),
      _credential('Copper Finch'),
    ];
    for (final prompt in <String>[
      'show my QA Social Example',
      'show me nebula orchard',
      "what's my copper finch",
    ]) {
      final topic = extractInventoryPrivateLookupTopic(prompt)!;
      expect(matchCredentialV2RecordsForText(topic, records), hasLength(1));
    }
  });

  test('generalized prefix matching works in either direction', () {
    final records = [_credential('QA Social Example')];
    expect(
        matchCredentialV2RecordsForText('social exam', records), hasLength(1));
    expect(matchCredentialV2RecordsForText('QA Social Examples', records),
        hasLength(1));
  });

  test('exact label wins over siblings with shared generic tokens', () {
    final records = [
      _credential('qa-random-64192'),
      _credential('qa-random-78231'),
      _credential('qa-random-93517'),
    ];
    final matches = matchCredentialV2RecordsForText(
      'show my qa-random-93517 login',
      records,
    );
    expect(matches, hasLength(1));
    expect(matches.single.plaintext.service, 'qa-random-93517');
  });

  test('arbitration uses encrypted exact lookup before full inventory scan',
      () {
    final source = File('lib/main.dart').readAsStringSync();
    final exactLookup = source.indexOf("field: 'service'");
    final fullCredentialLoad = source.indexOf(
      'final credentialLoads = Future.wait<void>',
    );
    expect(exactLookup, greaterThanOrEqualTo(0));
    expect(fullCredentialLoad, greaterThan(exactLookup));
    expect(source, contains('final otherInventoryLoads = Future.wait<void>'));
  });

  test('file hydration coalesces concurrent loads after relogin', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('Future<void>? _vaultFilesLoadFuture'));
    expect(source, contains('final active = _vaultFilesLoadFuture'));
    final arbitrationLoad = source.substring(
      source.indexOf('Future<void> loadFiles() async'),
      source.indexOf('final credentialLoads = Future.wait<void>'),
    );
    expect(arbitrationLoad, contains('if (vaultFiles.isEmpty)'));
    expect(arbitrationLoad,
        isNot(contains('vaultFiles.isEmpty && !loadingFiles')));
  });

  test('ambiguous credential chat lookup stays inline', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf(
      'Future<bool> _tryLocalCredentialV2LookupReply',
    );
    final end = source.indexOf(
      'Future<bool> _tryLocalCredentialV2CreateReply',
      start,
    );
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final lookupHandler = source.substring(start, end);
    expect(lookupHandler, isNot(contains('showDialog<void>')));
    expect(lookupHandler, contains('Ask for the exact service name'));

    final arbitrationStart = source.indexOf(
      'Future<bool> _tryLocalPrivateDomainArbitration',
    );
    final arbitrationEnd = source.indexOf(
      'Future<bool> _tryLocalVaultFileLookupReply',
      arbitrationStart,
    );
    final arbitration = source.substring(arbitrationStart, arbitrationEnd);
    expect(arbitration, isNot(contains('_tryLocalCredentialV2LookupReply(')));
  });

  test('generic QA token cannot hijack a specific cross-domain lookup', () {
    final matches = matchLocalMemoryRecords(
      const LocalMemoryLookupIntent(subject: 'qa orchid 48219 edited'),
      [
        {
          'title': 'Harmless QA code comet',
          'memory_type': 'note',
          'tags': <String>[],
          'value': 'unrelated',
        },
      ],
    );
    expect(matches.records, isEmpty);
  });
}
