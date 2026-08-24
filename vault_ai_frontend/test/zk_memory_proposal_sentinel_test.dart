import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/chat_protocol_contracts.dart'
    show
        extractAndStripMemoryProposal,
        kMemoryProposalOpen,
        kMemoryProposalClose;

String _readMain() {
  final f = File('lib/main.dart');
  expect(f.existsSync(), isTrue);
  return f.readAsStringSync();
}

void main() {
  group('ZK memory-proposal sentinel — string-strip semantics', () {
    test('no sentinel → buffer passes through unchanged', () {
      final r = extractAndStripMemoryProposal(
        buffer: 'Hello, this is a normal assistant reply.',
        alreadyFinalized: false,
      );
      expect(r.strippedBuffer, 'Hello, this is a normal assistant reply.');
      expect(r.jsonPayload, isNull);
    });

    test(
        'opening marker only (mid-chunk) → everything from the '
        'marker onward is hidden until the closing marker arrives', () {
      final buf = 'Prefix.$kMemoryProposalOpen{"memory_type":"identity"';
      final r = extractAndStripMemoryProposal(
        buffer: buf,
        alreadyFinalized: false,
      );
      expect(r.strippedBuffer, 'Prefix.');
      expect(r.jsonPayload, isNull);
    });

    test(
        'full sentinel → payload extracted, sentinel + blank line '
        'stripped from the visible buffer', () {
      final json = '{"memory_type":"identity","memory_key":"name",'
          '"memory_value":"Ada","memory_event_date":null}';
      final buf = '$kMemoryProposalOpen$json$kMemoryProposalClose\n\n'
          'Got it.\n\nIdentity: Ada';
      final r = extractAndStripMemoryProposal(
        buffer: buf,
        alreadyFinalized: false,
      );
      expect(r.jsonPayload, json);
      expect(r.strippedBuffer, 'Got it.\n\nIdentity: Ada');
    });

    test(
        'alreadyFinalized=true → jsonPayload is null but buffer is '
        'still stripped so re-observations across chunks do not '
        'leak the sentinel', () {
      final buf = '$kMemoryProposalOpen{"memory_type":"identity"}'
          '$kMemoryProposalClose\n\nGot it.';
      final r = extractAndStripMemoryProposal(
        buffer: buf,
        alreadyFinalized: true,
      );
      expect(r.jsonPayload, isNull,
          reason: 'Must NOT resurface the JSON payload when the '
              'caller has already fired the finalize call — '
              'that would double-POST');
      expect(r.strippedBuffer, 'Got it.',
          reason: 'Even when finalize has already fired, the '
              'sentinel must still be stripped from user view');
    });

    test(
        'sentinel that arrives without a trailing blank line is '
        'still stripped cleanly', () {
      final buf = '${kMemoryProposalOpen}{"memory_type":"identity"}'
          '${kMemoryProposalClose}Got it.';
      final r = extractAndStripMemoryProposal(
        buffer: buf,
        alreadyFinalized: false,
      );
      expect(r.jsonPayload, '{"memory_type":"identity"}');
      expect(r.strippedBuffer, 'Got it.');
    });
  });

  group('ZK memory-proposal sentinel — SSE handler is wired', () {
    test(
        'EVERY chat SSE loop calls extractAndStripMemoryProposal '
        'BEFORE downstream parse/render', () {
      final src = _readMain();
      // Enumerate every SSE decrypt point in main.dart and prove
      // each one calls the sentinel-strip helper before the
      // structured-message parse. Any un-guarded loop is a leak.
      int cursor = 0;
      int loops = 0;
      while (true) {
        final decryptIdx = src.indexOf('buffer += decryptedChunk;', cursor);
        if (decryptIdx < 0) break;
        loops += 1;
        final parseIdx = src.indexOf(
          '_tryParseAssistantStructuredMessage(buffer)',
          decryptIdx,
        );
        expect(parseIdx, greaterThan(decryptIdx),
            reason: 'structured-message parse must be downstream '
                'of the decrypt step');
        final middle = src.substring(decryptIdx, parseIdx);
        expect(
          middle,
          contains('extractAndStripMemoryProposal('),
          reason: 'SSE loop at offset $decryptIdx must call '
              'extractAndStripMemoryProposal BEFORE '
              '_tryParseAssistantStructuredMessage — otherwise '
              'the sentinel could reach the structured parser '
              'or the UI',
        );
        expect(
          middle,
          contains('_finalizeMemoryProposalBestEffort('),
          reason: 'SSE loop at offset $decryptIdx must fire the '
              'client finalize call when the strip helper '
              'returns a JSON payload',
        );
        expect(
          middle,
          contains('memoryProposalFinalized'),
          reason: 'A per-send finalize-once guard must exist so '
              'the finalize call is not double-fired across '
              'chunks (SSE loop at offset $decryptIdx)',
        );
        cursor = parseIdx + 1;
      }
      expect(loops, greaterThanOrEqualTo(2),
          reason: 'main.dart has multiple SSE loops (_send + '
              '_sendQuickPrompt); at least two are expected');
    });

    test(
        'main.dart uses MemoryV2Repository to POST '
        'ciphertext (never plaintext) to the AI-memory endpoint', () {
      final src = _readMain();
      expect(
        src,
        contains('final result = await repository.create('),
        reason: 'main.dart must dispatch through the authoritative '
            'MemoryV2Repository ciphertext write path',
      );
      expect(
        src,
        isNot(contains('unawaited(_finalizeMemoryProposalBestEffort(')),
      );
    });

    test(
        'finalize best-effort helper swallows exceptions so no '
        'plaintext leaks into an error banner', () {
      final src = _readMain();
      final idx = src.indexOf('_finalizeMemoryProposalBestEffort({');
      expect(idx, greaterThan(-1),
          reason: 'The finalize helper must be declared in main.dart');
      final bodyEnd = src.indexOf('  void _askBrainAboutFile(', idx);
      expect(bodyEnd, greaterThan(idx));
      final body = src.substring(idx, bodyEnd);
      expect(
        body,
        contains('catch (_)'),
        reason: 'the finalize helper must catch and drop any error '
            '(privacy-safe silent fallback — no error banner)',
      );
    });
  });
}
