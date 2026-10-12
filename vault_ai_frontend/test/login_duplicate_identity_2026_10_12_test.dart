import 'dart:convert';
import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

const client = VaultAIClient(baseUrl: 'http://127.0.0.1:9');

class Fixture {
  final mvk = SecretKey(List<int>.filled(32, 7));
  final rows = <Map<String, dynamic>>[];
  final legacy = <Map<String, dynamic>>[];
  final writes = <http.Request>[];
  int finalizeFailures = 0;
  bool lockDuringInventoryRead = false;
  bool rejectCiphertextWrite = false;
  String? legacyConflictCode;

  Future<void> row(int id, {String title = 'Duplicate', String? draft}) async {
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String value) async => b64urlEncode(
        await aesGcmWrap(key, utf8.encode(value)));
    rows.add({
      'item_id': id,
      'item_type_ciphertext': await wrap('login'),
      'service_ciphertext': await wrap(title),
      'payload_ciphertext': await wrap(jsonEncode({
        'fields': {'password': 'synthetic-$id'},
        if (draft != null) 'draft_id': draft,
      })),
    });
  }

  Future<http.Response> respond(http.Request request) async {
    if (request.url.host != '127.0.0.1' || request.url.port != 9) {
      throw StateError('Foreign destination blocked');
    }
    final path = request.url.path;
    if (request.method == 'GET' && path == '/vault/ciphertext/vault-items') {
      return http.Response(jsonEncode(rows), 200);
    }
    if (path == '/list-secure-items') {
      if (lockDuringInventoryRead) ZkActiveMvk.clear();
      return http.Response(jsonEncode({'items': legacy}), 200);
    }
    writes.add(request);
    if (request.method == 'POST' && path == '/vault/ciphertext/vault-items') {
      if (rejectCiphertextWrite) {
        return http.Response('{"detail":{"code":"update_app_required"}}', 409);
      }
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final id = body['item_id'] ?? 90;
      rows.removeWhere((row) => row['item_id'] == id);
      rows.add({...body, 'item_id': id});
      return http.Response(jsonEncode({'item_id': id, 'created': body['item_id'] == null}), 200);
    }
    if (path == '/vault/ciphertext/vault-items/generated-drafts/finalize') {
      if (finalizeFailures > 0) {
        finalizeFailures--;
        return http.Response('{}', 503);
      }
      return http.Response('{"finalized":true}', 200);
    }
    if (request.method == 'DELETE' && path.startsWith('/vault/ciphertext/vault-items/')) {
      return http.Response('{"deleted":true}', 200);
    }
    if (path == '/get-secure-item' || path == '/update-secure-item' || path == '/delete-secure-item') {
      if (path == '/update-secure-item' && legacyConflictCode != null) {
        return http.Response(jsonEncode({'detail': {'code': legacyConflictCode}}), 409);
      }
      return http.Response('{"id":21,"fields":{"password":"legacy"},"deleted":true}', 200);
    }
    throw StateError('Unexpected synthetic operation: $path');
  }

  Future<T> run<T>(Future<T> Function() action) =>
      http.runWithClient(action, () => MockClient(respond));

  void unlock() => ZkActiveMvk.set(mvk: mvk, vaultId: 'synthetic', vaultHandle: 'synthetic');
}

Future<Map<String, dynamic>> read({String? id}) => client.getVaultSecureItem(
    vaultName: '', service: 'Duplicate', itemType: 'login', pin: 'synthetic', authToken: 'synthetic', itemId: id);
Future<Map<String, dynamic>> edit({String? id, bool create = false, String title = 'Duplicate'}) => client.updateVaultSecureItem(
    vaultName: '', oldService: title, itemType: 'login', pin: 'synthetic', authToken: 'synthetic', itemId: id, createOnly: create,
    fields: {'password': 'changed-synthetic'});
Future<Map<String, dynamic>> remove({String? id}) => client.deleteVaultSecureItem(
    vaultName: '', service: 'Duplicate', itemType: 'login', pin: 'synthetic', authToken: 'synthetic', itemId: id);
Future<Map<String, dynamic>> draft(String id) => client.saveGeneratedLoginDraftCiphertext(
    authToken: 'synthetic', pin: 'synthetic', draftId: id, service: 'Duplicate', fields: {'password': 'new-synthetic'});

void main() {
  tearDown(ZkActiveMvk.clear);

  test('inventory keeps distinct ciphertext and legacy IDs with identical titles', () async {
    final f = Fixture()..unlock();
    await f.row(11);
    await f.row(12);
    f.legacy.addAll([
      {'id': 21, 'service': 'Duplicate', 'item_type': 'login'},
      {'id': 22, 'service': 'Duplicate', 'item_type': 'login'},
    ]);
    final result = await f.run(() => client.listVaultSecureItems(vaultName: '', pin: 'synthetic', authToken: 'synthetic'));
    expect((result['items'] as List).map((row) => row['id']), [11, 12, 21, 22]);
  });

  test('merge deduplicates only the same persisted ID, never a shared title', () async {
    final f = Fixture()..unlock();
    await f.row(11);
    f.legacy.addAll([
      {'id': 11, 'service': 'Duplicate', 'item_type': 'login'},
      {'id': 12, 'service': 'Duplicate', 'item_type': 'login'},
    ]);
    final result = await f.run(() => client.listVaultSecureItems(vaultName: '', pin: 'synthetic', authToken: 'synthetic'));
    expect((result['items'] as List).map((row) => row['id']), [11, 12]);
  });

  test('CREATE warns before any write; original duplicate records stay untouched', () async {
    final f = Fixture()..unlock();
    await f.row(11);
    await f.row(12);
    final before = jsonEncode(f.rows);
    await expectLater(f.run(() => edit(create: true)), throwsA(isA<SavedItemConflictException>()));
    expect(f.writes, isEmpty);
    expect(jsonEncode(f.rows), before);
  });

  test('new CREATE has no existing item ID and cannot overwrite', () async {
    final f = Fixture()..unlock();
    await f.row(11);
    await f.run(() => edit(create: true, title: 'Different'));
    final body = jsonDecode(f.writes.single.body) as Map;
    expect(body.containsKey('item_id'), isFalse);
    expect(body['mutation_intent'], 'create');
    expect(body.containsKey('service'), isFalse);
    expect(f.rows.map((row) => row['item_id']), [11, 90]);
  });

  test('CREATE detects case and whitespace equivalent titles', () async {
    final f = Fixture()..unlock();
    await f.row(11, title: 'Same   Title');
    await expectLater(f.run(() => edit(create: true, title: ' same title ')),
        throwsA(isA<SavedItemConflictException>()));
    expect(f.writes, isEmpty);
  });

  test('legacy duplicate CREATE warns before any new ciphertext write', () async {
    final f = Fixture()..unlock();
    f.legacy.add({'id': 21, 'service': 'Duplicate', 'item_type': 'login'});
    await expectLater(f.run(() => edit(create: true)),
        throwsA(isA<SavedItemConflictException>()));
    expect(f.writes, isEmpty);
  });

  test('lock during create preflight prevents queued private write', () async {
    final f = Fixture()..unlock();
    f.lockDuringInventoryRead = true;
    await expectLater(f.run(() => edit(create: true, title: 'Different')),
        throwsStateError);
    expect(f.writes, isEmpty);
  });

  for (final action in {'read': () => read(), 'edit': () => edit(), 'delete': () => remove()}.entries) {
    test('ambiguous title-only ${action.key} refuses without a mutation', () async {
      final f = Fixture()..unlock();
      await f.row(11);
      await f.row(12);
      await expectLater(f.run(action.value), throwsA(isA<SavedItemConflictException>()));
      expect(f.writes, isEmpty);
    });
  }

  test('ID-selected View, Edit and Delete use the exact ciphertext row', () async {
    final f = Fixture()..unlock();
    await f.row(11);
    await f.row(12);
    await f.run(() async {
      expect((await read(id: '12'))['fields']['password'], 'synthetic-12');
      await edit(id: '12');
      await remove(id: '12');
    });
    expect(jsonDecode(f.writes.first.body)['item_id'], 12);
    expect(jsonDecode(f.writes.first.body)['mutation_intent'], 'edit');
    expect(f.writes.last.url.path, '/vault/ciphertext/vault-items/12');
    expect(f.rows.first['item_id'], 11);
  });

  test('ID-selected legacy operations never create a shadow ciphertext item', () async {
    final f = Fixture()..unlock();
    f.legacy.addAll([
      {'id': 21, 'service': 'Duplicate', 'item_type': 'login'},
      {'id': 22, 'service': 'Duplicate', 'item_type': 'login'},
    ]);
    await f.run(() async {
      await read(id: '21');
      await edit(id: '21');
      await remove(id: '21');
    });
    expect(f.writes.map((r) => r.url.path), ['/get-secure-item', '/update-secure-item', '/delete-secure-item']);
    expect(f.writes.every((r) => jsonDecode(r.body)['item_id'] == '21'), isTrue);
  });

  test('unknown explicit ID cannot fall back to a title match', () async {
    final f = Fixture()..unlock();
    await f.row(11);
    await expectLater(f.run(() => edit(id: '99')), throwsStateError);
    expect(f.writes, isEmpty);
  });

  test('different generated draft with same title warns, never overwrites', () async {
    final f = Fixture()..unlock();
    await f.row(11, draft: 'original');
    await expectLater(f.run(() => draft('different')), throwsA(isA<SavedItemConflictException>()));
    expect(f.writes, isEmpty);
  });

  test('same draft retry after lost finalize reuses ID without a second write', () async {
    final f = Fixture()..unlock();
    f.finalizeFailures = 1;
    await expectLater(f.run(() => draft('same')), throwsException);
    await f.run(() => draft('same'));
    expect(f.writes.where((r) => r.url.path == '/vault/ciphertext/vault-items').length, 1);
    expect(f.writes.where((r) => r.url.path.endsWith('/finalize')).length, 2);
    expect(jsonDecode(f.writes.last.body), {'item_id': 90, 'draft_id': 'same'});
  });

  test('retry after explicit edit/rename preserves edited fields and encrypted draft identity', () async {
    final f = Fixture()..unlock();
    await f.run(() async {
      await draft('same');
      await client.updateVaultSecureItem(
        vaultName: '', oldService: 'Duplicate', newService: 'Renamed',
        itemType: 'login', pin: 'synthetic', authToken: 'synthetic',
        itemId: '90', fields: {'password': 'edited-synthetic'},
      );
      final writesBeforeRetry = f.writes.where((r) =>
          r.url.path == '/vault/ciphertext/vault-items').length;
      final result = await draft('same');
      expect(result['service'], 'Renamed');
      expect(f.writes.where((r) =>
          r.url.path == '/vault/ciphertext/vault-items').length, writesBeforeRetry);
      final inventory = await client.listVaultSecureItems(
          vaultName: '', pin: 'synthetic', authToken: 'synthetic');
      final rows = inventory['items'] as List;
      expect(rows.length, 1);
      expect(rows.single['draft_id'], 'same');
      expect(rows.single['service'], 'Renamed');
      expect(rows.single['fields']['password'], 'edited-synthetic');
    });
  });

  test('pre-fix generated title without draft identity is not treated as retry', () async {
    final f = Fixture()..unlock();
    await f.row(11);
    await expectLater(f.run(() => draft('same')), throwsA(isA<SavedItemConflictException>()));
    expect(f.writes, isEmpty);
  });

  testWidgets('duplicate cards remain separate and actions preserve the selected ID', (tester) async {
    final selected = <String>[];
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: LoginsPage(
        isLoading: false, hasLoaded: true, vaultLabel: 'Synthetic', onRefresh: () async {},
        logins: [for (final id in ['11', '12']) VaultLoginItem.fromJson({'id': id, 'service': 'Duplicate', 'item_type': 'login'})],
        onViewItem: (item) => selected.add('view:${item.itemId}'),
        onEditItem: (item) => selected.add('edit:${item.itemId}'),
        onDeleteItem: (item) => selected.add('delete:${item.itemId}'),
      )),
    ));
    for (final action in ['View', 'Edit', 'Delete']) {
      final button = find.descendant(of: find.byKey(const Key('secure_item_card_id_12')), matching: find.text(action));
      await tester.ensureVisible(button);
      await tester.tap(button);
    }
    expect(selected, ['view:12', 'edit:12', 'delete:12']);
    expect(find.byKey(const Key('secure_item_card_id_11')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  test('dashboard create and row controls carry separate create/identity contracts', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('createOnly: createMode'));
    expect(source, contains('onViewItem: (item)'));
    expect(source, contains('onEditItem: (item)'));
    expect(source, contains('onDeleteItem: (item)'));
    expect(source, contains('final itemId = _pendingClientSecureItemDeleteId'));
    expect(source, contains('itemId: itemId'));
  });

  test('all generic non-login create/edit helper callers emit bounded intent', () async {
    final f = Fixture()..unlock();
    await f.run(() async {
      for (final type in ['wallet_account', 'crypto_note', 'crypto_sensitive_backup', 'private_note']) {
        for (final id in [null, 77]) {
          await client.tryZkVaultItemCiphertextUpsert(
            baseUrl: client.baseUrl, authToken: 'synthetic',
            existingItemId: id, itemType: type, service: 'synthetic',
            payload: {'note': 'synthetic'},
          );
          final body = jsonDecode(f.writes.last.body);
          expect(body['mutation_intent'], id == null ? 'create' : 'edit');
          expect(body['item_id'], id);
        }
      }
    });
  });

  test('crypto profile helper stays encrypted and never falls back after intent refusal', () async {
    final f = Fixture()..unlock();
    f.rejectCiphertextWrite = true;
    await expectLater(f.run(() => client.saveCryptoWalletProfile(
      pin: 'synthetic', authToken: 'synthetic', asset: 'ETH',
      walletLabel: 'synthetic', publicAddress: '0x2222222222222222222222222222222222222222',
    )), throwsA(isA<SavedItemUpdateRequiredException>()));
    expect(f.writes.length, 1);
    expect(f.writes.single.url.path, '/vault/ciphertext/vault-items');
    expect(jsonDecode(f.writes.single.body)['mutation_intent'], 'create');
  });

  test('legacy update requirement has accurate message, not duplicate or ambiguity', () async {
    final f = Fixture();
    ZkActiveMvk.clear();
    f.legacyConflictCode = 'update_app_required';
    await expectLater(f.run(() => edit(id: '21')),
        throwsA(isA<SavedItemUpdateRequiredException>().having(
            (error) => error.toString(), 'message', savedItemUpdateRequiredMessage)));
    expect(f.writes.length, 1);
  });

  test('normal legacy duplicate and ambiguity conflicts keep their original messages', () async {
    final f = Fixture();
    ZkActiveMvk.clear();
    f.legacyConflictCode = 'duplicate_saved_item';
    await expectLater(f.run(() => edit(create: true)),
        throwsA(isA<SavedItemConflictException>().having(
            (error) => error.duplicate, 'duplicate', true)));
    f.legacyConflictCode = 'ambiguous_saved_item';
    await expectLater(f.run(() => edit()),
        throwsA(isA<SavedItemConflictException>().having(
            (error) => error.duplicate, 'duplicate', false)));
  });

  test('invalid existing ID never becomes create or plaintext fallback', () async {
    final f = Fixture()..unlock();
    await expectLater(f.run(() => client.tryZkVaultItemCiphertextUpsert(
      baseUrl: client.baseUrl, authToken: 'synthetic', existingItemId: 0,
      itemType: 'login', service: 'synthetic', payload: {},
    )), throwsArgumentError);
    expect(f.writes, isEmpty);
  });
}
