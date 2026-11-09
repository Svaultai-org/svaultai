import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show kEnableZkPrivateChat, kEnableZkChatSavedItemView;
import 'package:vault_ai_frontend/services/zk_private_chat.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_flow.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_index.dart';

void main() {
  test('flagged ZK chat routes by MVK before any legacy key requirement', () {
    expect(
      resolveZkChatEntryRoute(
        privateChatEnabled: true,
        hasZkHandle: true,
        hasMvk: true,
        mvkMatchesVault: true,
      ),
      ZkChatEntryRoute.privateChat,
    );
    expect(
      resolveZkChatEntryRoute(
        privateChatEnabled: true,
        hasZkHandle: true,
        hasMvk: false,
        mvkMatchesVault: false,
      ),
      ZkChatEntryRoute.unavailable,
    );
    expect(
      resolveZkChatEntryRoute(
        privateChatEnabled: true,
        hasZkHandle: true,
        hasMvk: true,
        mvkMatchesVault: false,
      ),
      ZkChatEntryRoute.unavailable,
    );
    expect(
      resolveZkChatEntryRoute(
        privateChatEnabled: false,
        hasZkHandle: true,
        hasMvk: false,
        mvkMatchesVault: false,
      ),
      ZkChatEntryRoute.legacy,
    );
  });

  test('private chat UI dispatch stays off in an ordinary build', () {
    expect(kEnableZkPrivateChat, isFalse);
    expect(kEnableZkChatSavedItemView, isFalse);
  });

  test('private media search and follow-up never call general AI', () async {
    var indexLoads = 0;
    var generalCalls = 0;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async {
        indexLoads++;
        return const ZkPrivateChatIndex(
          savedItems: [],
          files: [
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'video-1',
              title: 'standing-at-the-beach.mp4',
              mediaKind: ZkLocalMediaKind.video,
            ),
          ],
          incomplete: false,
        );
      },
      sendGeneral: (_, __) async {
        generalCalls++;
        return 'general reply';
      },
    );
    final found = await flow.run('Find my video standing at the beach');
    expect(found.local.selection?.id, 'video-1');
    final followUp = await flow.run('play it');
    expect(followUp.local.selection?.id, 'video-1');
    expect(indexLoads, 2);
    expect(generalCalls, 0);
    flow.clear();
    final afterClear = await flow.run('play it');
    expect(afterClear.local.selection, isNull);
    expect(generalCalls, 0);
  });

  test('V2 text follow-up keeps decrypted text on the device', () async {
    var generalCalls = 0;
    const textFile = ZkLocalChatRecord(
      kind: ZkLocalChatKind.file,
      id: 'v2-journal',
      title: 'journal.txt',
      searchText: 'I went to the beach with family.',
      mediaKind: ZkLocalMediaKind.document,
    );
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async => const ZkPrivateChatIndex(
        savedItems: [],
        files: [textFile],
        incomplete: false,
      ),
      sendGeneral: (_, __) async {
        generalCalls++;
        return 'general reply';
      },
    );
    final found = await flow.run('Find my journal');
    expect(found.local.selection?.id, textFile.id);
    final read = await flow.run('what does it say?');
    expect(read.local.action, ZkLocalChatAction.readText);
    expect(read.local.selection?.searchText, textFile.searchText);
    expect(generalCalls, 0);
    flow.clear();
    final stale = await flow.run('read it');
    expect(stale.local.disposition, ZkLocalChatDisposition.notFound);
    expect(generalCalls, 0);
  });

  test('offered filename lookup stays local after a name miss', () async {
    var generalCalls = 0;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async => const ZkPrivateChatIndex(
        savedItems: [],
        files: [
          ZkLocalChatRecord(
            kind: ZkLocalChatKind.file,
            id: 'text-1',
            title: 'journal.txt',
            searchText: 'beach afternoon',
          ),
        ],
        incomplete: false,
      ),
      sendGeneral: (_, __) async {
        generalCalls++;
        return 'unexpected general reply';
      },
    );
    final found = await flow.run('open beach', forcePrivate: true);
    expect(found.local.selection?.id, 'text-1');
    final missing = await flow.run('open absent', forcePrivate: true);
    expect(missing.local.disposition, ZkLocalChatDisposition.notFound);
    expect(generalCalls, 0);
  });

  test(
    'contextual follow-up after private lookup cannot reach general AI',
    () async {
      var generalCalls = 0;
      final flow = ZkPrivateChatFlow(
        accessIsCurrent: () => true,
        loadIndex: () async => const ZkPrivateChatIndex(
          savedItems: [],
          files: [
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'photo-red',
              title: 'red coat photo.jpg',
              mediaKind: ZkLocalMediaKind.photo,
            ),
          ],
          incomplete: false,
        ),
        sendGeneral: (_, __) async {
          generalCalls++;
          return 'unexpected general reply';
        },
      );
      final found = await flow.run('Find my red coat photo');
      expect(found.local.selection?.id, 'photo-red');
      final followUp = await flow.run('What about that one?');
      expect(followUp.local.disposition, isNot(ZkLocalChatDisposition.general));
      expect(generalCalls, 0);
      final unrelated = await flow.run('What is encryption?');
      expect(unrelated.local.disposition, ZkLocalChatDisposition.general);
      expect(generalCalls, 1);
    },
  );

  test(
    'ambiguous second-result follow-up stays local and selects exact ID',
    () async {
      var generalCalls = 0;
      final flow = ZkPrivateChatFlow(
        accessIsCurrent: () => true,
        loadIndex: () async => const ZkPrivateChatIndex(
          savedItems: [],
          files: [
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'one',
              title: 'beach sunrise.jpg',
              mediaKind: ZkLocalMediaKind.photo,
            ),
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'two',
              title: 'beach sunset.jpg',
              mediaKind: ZkLocalMediaKind.photo,
            ),
          ],
          incomplete: false,
        ),
        sendGeneral: (_, __) async {
          generalCalls++;
          return 'should not be called';
        },
      );
      final initial = await flow.run('Find my beach photo');
      expect(initial.local.disposition, ZkLocalChatDisposition.ambiguous);
      final selected = await flow.run('show the second one');
      expect(selected.local.selection?.id, 'two');
      expect(generalCalls, 0);
      flow.clear();
      final stale = await flow.run('show the second one');
      expect(stale.local.disposition, ZkLocalChatDisposition.notFound);
      expect(generalCalls, 0);
    },
  );

  test(
    'related-file follow-up uses selected local file, never general AI',
    () async {
      var generalCalls = 0;
      final flow = ZkPrivateChatFlow(
        accessIsCurrent: () => true,
        loadIndex: () async => const ZkPrivateChatIndex(
          savedItems: [],
          files: [
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'front',
              title: 'passport front.jpg',
              searchText: 'PRIVATE SENTINEL',
              mediaKind: ZkLocalMediaKind.photo,
            ),
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'back',
              title: 'passport back.jpg',
              mediaKind: ZkLocalMediaKind.photo,
            ),
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'other',
              title: 'beach.jpg',
              mediaKind: ZkLocalMediaKind.photo,
            ),
          ],
          incomplete: false,
        ),
        sendGeneral: (_, __) async {
          generalCalls++;
          return 'should not be called';
        },
      );
      final selected = await flow.run('Find my passport front photo');
      expect(selected.local.selection?.id, 'front');
      final related = await flow.run('show related files');
      expect(related.local.disposition, ZkLocalChatDisposition.related);
      expect(related.local.selection?.id, 'front');
      expect(related.local.matches.map((e) => e.id), ['back']);
      final envelope = ZkLocalFileRelations.envelope(
        anchor: related.local.selection!,
        matches: related.local.matches,
        incomplete: false,
      );
      expect(envelope.toString(), isNot(contains('PRIVATE SENTINEL')));
      expect(envelope['is_complete'], true);
      expect(generalCalls, 0);
    },
  );

  test('general AI history excludes every private turn', () async {
    final received = <List<ZkGeneralChatTurn>>[];
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async => const ZkPrivateChatIndex(
        savedItems: [],
        files: [],
        incomplete: false,
      ),
      sendGeneral: (prompt, history) async {
        received.add(history);
        return 'Answer about $prompt';
      },
    );
    await flow.run('What is encryption?');
    await flow.run('Find my passport file');
    await flow.run('How does encryption work?');
    expect(received, hasLength(2));
    expect(received.first, isEmpty);
    expect(received.last.map((turn) => turn.content).toList(), [
      'What is encryption?',
      'Answer about What is encryption?',
    ]);
  });

  test('ambiguous private terms and vault name never enter general AI',
      () async {
    var indexLoads = 0;
    var generalCalls = 0;
    final flow = ZkPrivateChatFlow(
      vaultName: 'Brain',
      accessIsCurrent: () => true,
      loadIndex: () async {
        indexLoads++;
        return const ZkPrivateChatIndex(
          savedItems: [],
          files: [
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'red-shoes',
              title: 'red shoes.jpg',
              mediaKind: ZkLocalMediaKind.photo,
            ),
          ],
          incomplete: false,
        );
      },
      sendGeneral: (_, __) async {
        generalCalls++;
        return 'generic';
      },
    );

    final where = await flow.run('Where are the red shoes?');
    expect(where.local.selection?.id, 'red-shoes');
    expect(generalCalls, 0);
    final named = await flow.run('Explain Brain');
    expect(named.local.maySendToGeneralAi, isFalse);
    expect(generalCalls, 0);
    expect(indexLoads, 2);

    final generic = await flow.run('What is encryption?');
    expect(generic.generalReply, 'generic');
    expect(generalCalls, 1);
    expect(indexLoads, 2);
  });

  test('mutation stops before index and network requests', () async {
    var requests = 0;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async {
        requests++;
        return const ZkPrivateChatIndex(
          savedItems: [],
          files: [],
          incomplete: false,
        );
      },
      sendGeneral: (_, __) async {
        requests++;
        return 'should not be sent';
      },
    );
    final result = await flow.run('Delete my beach video');
    expect(result.local.disposition, ZkLocalChatDisposition.unsupportedAction);
    expect(requests, 0);
  });

  test('lock during a general response discards the reply', () async {
    var current = true;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => current,
      loadIndex: () async => const ZkPrivateChatIndex(
        savedItems: [],
        files: [],
        incomplete: false,
      ),
      sendGeneral: (_, __) async {
        current = false;
        return 'late reply';
      },
    );
    await expectLater(flow.run('What is encryption?'), throwsStateError);
  });
}
