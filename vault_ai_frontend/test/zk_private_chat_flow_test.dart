import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart' show kEnableZkPrivateChat;
import 'package:vault_ai_frontend/services/zk_private_chat.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_flow.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_index.dart';

void main() {
  test('flagged ZK chat routes by MVK before any legacy key requirement', () {
    expect(resolveZkChatEntryRoute(
      privateChatEnabled: true,
      hasZkHandle: true,
      hasMvk: true,
      mvkMatchesVault: true,
    ), ZkChatEntryRoute.privateChat);
    expect(resolveZkChatEntryRoute(
      privateChatEnabled: true,
      hasZkHandle: true,
      hasMvk: false,
      mvkMatchesVault: false,
    ), ZkChatEntryRoute.unavailable);
    expect(resolveZkChatEntryRoute(
      privateChatEnabled: true,
      hasZkHandle: true,
      hasMvk: true,
      mvkMatchesVault: false,
    ), ZkChatEntryRoute.unavailable);
    expect(resolveZkChatEntryRoute(
      privateChatEnabled: false,
      hasZkHandle: true,
      hasMvk: false,
      mvkMatchesVault: false,
    ), ZkChatEntryRoute.legacy);
  });

  test('private chat UI dispatch stays off in an ordinary build', () {
    expect(kEnableZkPrivateChat, isFalse);
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

  test('offered filename lookup stays local after a name miss', () async {
    var generalCalls = 0;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async => const ZkPrivateChatIndex(
        savedItems: [],
        files: [ZkLocalChatRecord(
          kind: ZkLocalChatKind.file,
          id: 'text-1',
          title: 'journal.txt',
          searchText: 'beach afternoon',
        )],
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

  test('contextual follow-up after private lookup cannot reach general AI',
      () async {
    var generalCalls = 0;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async => const ZkPrivateChatIndex(
        savedItems: [],
        files: [ZkLocalChatRecord(
          kind: ZkLocalChatKind.file,
          id: 'photo-red',
          title: 'red coat photo.jpg',
          mediaKind: ZkLocalMediaKind.photo,
        )],
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
  });

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
    expect(received.last.map((turn) => turn.content).toList(),
        ['What is encryption?', 'Answer about What is encryption?']);
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
