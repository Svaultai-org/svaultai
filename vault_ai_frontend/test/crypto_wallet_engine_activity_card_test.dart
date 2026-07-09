

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_activity_card.dart';


class _StubVaultAIClient extends VaultAIClient {
  Map<String, dynamic> Function(String asset)? respond;
  Exception? throwOn;

  _StubVaultAIClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactions({
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    if (throwOn != null) throw throwOn!;
    if (respond != null) return respond!(asset);
    return {'status': 'ok', 'transactionsStatus': 'unavailable',
            'reason': 'indexer_not_configured', 'transactions': []};
  }
}


Map<String, dynamic> _row({
  required String hash,
  String direction = 'incoming',
  String amount = '0.5',
  String unit = 'ETH',
  String status = 'confirmed',
  int confirmations = 5,
  int? timestamp,
  String fromAddress = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  String toAddress = '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
}) {
  return {
    'schema':        kActivityCardSchemaV1,
    'asset':         'ETH',
    'network':       'ethereum_sepolia',
    'networkLabel':  'Ethereum Sepolia',
    'txHash':        hash,
    'direction':     direction,
    'amount':        amount,
    'unit':          unit,
    'status':        status,
    'confirmations': confirmations,
    'fromAddress':   fromAddress,
    'toAddress':     toAddress,
    'timestamp':     timestamp,
    'source':        'indexer',
  };
}


void main() {
  group('CryptoWalletActivityCard — slice 8 transaction history', () {
    test('A1: closed-set constants', () {
      expect(kActivityCardSchemaV1, equals('crypto_wallet_transaction_v1'));
      expect(kActivityDirectionIncoming, equals('incoming'));
      expect(kActivityDirectionOutgoing, equals('outgoing'));
      expect(kActivityStatusPending,   equals('pending'));
      expect(kActivityStatusConfirmed, equals('confirmed'));
      expect(kActivityStatusFailed,    equals('failed'));
      expect(kActivityStatusUnknown,   equals('unknown'));
      expect(kActivityTxsStatusAvailable,   equals('available'));
      expect(kActivityTxsStatusUnavailable, equals('unavailable'));
      expect(
        kActivityReasonIndexerNotConfigured, equals('indexer_not_configured'),
      );
      expect(kActivityReasonNoWalletYet, equals('no_wallet_yet'));
      expect(kActivityReasonUpstreamError, equals('upstream_error'));
      expect(kActivityReasonInvalidAddress, equals('invalid_address'));
      expect(
        kActivityLiveAssets,
        equals({'ETH', 'USDT_ERC20', 'USDC_ERC20'}),
      );
    });

    test('A2: activityTxHashShort returns operator-pinned shape', () {
      final tx = '0x${'ab' * 32}';
      final shortened = activityTxHashShort(tx);
      expect(shortened.length, lessThan(tx.length));
      expect(shortened.startsWith('0x'), isTrue);
      expect(shortened.endsWith(tx.substring(tx.length - 4)), isTrue);
      expect(activityTxHashShort(null), equals(''));
      expect(activityTxHashShort(''), equals(''));
      expect(activityTxHashShort('0x123'), equals(''));
      expect(activityTxHashShort('not-a-hash-at-all'), equals(''));
    });

    test('A3: fromJson rejects rows that miss a tx hash', () {
      expect(
        CryptoWalletActivityRow.fromJson({}),
        isNull,
      );
      expect(
        CryptoWalletActivityRow.fromJson({'txHash': ''}),
        isNull,
      );
      final row = CryptoWalletActivityRow.fromJson({
        'txHash': '0x${'ab' * 32}',
        'direction': 'incoming',
        'amount': '1.5',
        'unit': 'ETH',
        'status': 'confirmed',
        'confirmations': 5,
        'fromAddress': '0x${'11' * 20}',
        'toAddress': '0x${'22' * 20}',
        'timestamp': 1700000000,
        'source': 'indexer',
      });
      expect(row, isNotNull);
      expect(row!.isIncoming, isTrue);
      expect(row.unit, equals('ETH'));
      expect(row.timestamp, equals(1700000000));
    });

    testWidgets('A4: no-wiring mount renders honest unavailable copy',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(asset: 'ETH'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_activity_card_unavailable')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_activity_card_list')),
        findsNothing,
      );
      
      
      final hashRe = RegExp(r'0x[0-9a-fA-F]{8,}');
      final balRe = RegExp(r'\d+\.\d+\s*(ETH|USDT|USDC|BTC|SOL|BNB|XMR)');
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(hashRe.hasMatch(txt), isFalse, reason: 'No 0x hash: $txt');
        expect(balRe.hasMatch(txt), isFalse, reason: 'No balance: $txt');
      }
    });

    testWidgets('A5: indexer_not_configured envelope renders unavailable',
        (tester) async {
      final stub = _StubVaultAIClient()
        ..respond = (asset) => {
              'status': 'ok',
              'transactionsStatus': 'unavailable',
              'reason': 'indexer_not_configured',
              'transactions': [],
            };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(
              asset: 'ETH', authToken: 'tok', apiClient: stub,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_activity_card_unavailable')),
        findsOneWidget,
      );
      expect(
        find.text(kActivityCopyHonestUnavailable),
        findsOneWidget,
      );
    });

    testWidgets('A6: available + empty list renders empty-state copy',
        (tester) async {
      final stub = _StubVaultAIClient()
        ..respond = (asset) => {
              'status': 'ok',
              'transactionsStatus': 'available',
              'transactions': [],
            };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(
              asset: 'ETH', authToken: 'tok', apiClient: stub,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_activity_card_empty')),
        findsOneWidget,
      );
      expect(find.text(kActivityCopyEmpty), findsOneWidget);
    });

    testWidgets(
        'A7: available + non-empty list renders rows with direction + '
        'amount + status + shortened hash', (tester) async {
      
      
      final longHashA = '0x' + 'aa' * 32;
      final longHashB = '0x' + 'bb' * 32;
      final stub = _StubVaultAIClient()
        ..respond = (asset) => {
              'status': 'ok',
              'transactionsStatus': 'available',
              'transactions': [
                _row(hash: longHashA, direction: 'incoming',
                    amount: '1.25', status: 'confirmed'),
                _row(hash: longHashB, direction: 'outgoing',
                    amount: '0.5', status: 'pending'),
              ],
            };
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(
              asset: 'ETH', authToken: 'tok', apiClient: stub,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_activity_card_list')),
        findsOneWidget,
      );
      expect(
        find.byKey(Key('crypto_wallet_activity_card_row_$longHashA')),
        findsOneWidget,
      );
      expect(
        find.byKey(Key('crypto_wallet_activity_card_row_$longHashB')),
        findsOneWidget,
      );
      
      expect(find.text('In'), findsOneWidget);
      expect(find.text('Out'), findsOneWidget);
      
      expect(find.text('1.25 ETH'), findsOneWidget);
      expect(find.text('0.5 ETH'), findsOneWidget);
      
      expect(find.text('confirmed'), findsOneWidget);
      expect(find.text('pending'), findsOneWidget);
      
      expect(find.text(longHashA), findsNothing);
      expect(find.text(longHashB), findsNothing);
      expect(
        find.text(activityTxHashShort(longHashA)),
        findsOneWidget,
      );
      expect(
        find.text(activityTxHashShort(longHashB)),
        findsOneWidget,
      );
    });

    testWidgets('A8: no balance literal outside per-row amount cells',
        (tester) async {
      final stub = _StubVaultAIClient()
        ..respond = (asset) => {
              'status': 'ok',
              'transactionsStatus': 'available',
              'transactions': [
                _row(hash: '0x${'ab' * 32}',
                    direction: 'incoming', amount: '1.5'),
              ],
            };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(
              asset: 'ETH', authToken: 'tok', apiClient: stub,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      
      
      final balRe = RegExp(r'\d+\.\d+\s*(ETH|USDT|USDC)');
      var hits = 0;
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        if (balRe.hasMatch(txt)) hits += 1;
      }
      expect(hits, equals(1));
    });

    testWidgets('A9: 360 px mobile rendering survives across states',
        (tester) async {
      tester.view.physicalSize = const Size(360, 1200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(asset: 'ETH'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      
      final stub = _StubVaultAIClient()
        ..respond = (asset) => {
              'status': 'ok',
              'transactionsStatus': 'available',
              'transactions': [
                _row(hash: '0x${'cd' * 32}',
                    direction: 'incoming', amount: '0.01'),
                _row(hash: '0x${'ef' * 32}',
                    direction: 'outgoing', amount: '12345.6789'),
              ],
            };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(
              asset: 'ETH', authToken: 'tok', apiClient: stub,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    test('A10: source guards on crypto_wallet_engine_activity_card.dart', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_activity_card.dart',
      ).readAsStringSync();
      
      const bannedImports = [
        "ethereum_wallet", "ethereum_transaction",
        "ethereum_sepolia_proxy",
      ];
      for (final name in bannedImports) {
        expect(
          src.contains("import '../$name"),
          isFalse,
          reason: 'Activity card must not import $name',
        );
      }
      
      
      final stringLit = RegExp(
        r"'([^'\\]|\\.)*'|" + r'"([^"\\]|\\.)*"',
      );
      final scrubbed = src.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');
      final addrInLit = RegExp(r'0x[0-9a-fA-F]{40,}');
      for (final m in stringLit.allMatches(scrubbed)) {
        final lit = m.group(0)!;
        
        
        if (lit.contains(r'^0x[0-9a-fA-F]{64}$')) continue;
        expect(
          addrInLit.hasMatch(lit), isFalse,
          reason: 'Activity card string literal contains hardcoded '
              'address/tx hash: $lit',
        );
      }
    });

    testWidgets(
        'A11: tapping a row copies the FULL tx hash to clipboard',
        (tester) async {
      const hash = '0xfafafafafafafafafafafafafafafafafafafafafafafa'
          'fafafafafafafafafafafa';
      final stub = _StubVaultAIClient()
        ..respond = (asset) => {
              'status': 'ok',
              'transactionsStatus': 'available',
              'transactions': [
                _row(hash: hash, direction: 'incoming', amount: '0.1'),
              ],
            };
      String? clipboardPayload;
      
      TestDefaultBinaryMessengerBinding
          .instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') {
          clipboardPayload =
              (call.arguments as Map<dynamic, dynamic>)['text'] as String?;
        }
        return null;
      });
      addTearDown(() {
        TestDefaultBinaryMessengerBinding
            .instance.defaultBinaryMessenger
            .setMockMethodCallHandler(SystemChannels.platform, null);
      });
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(
              asset: 'ETH', authToken: 'tok', apiClient: stub,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final row = find.byKey(
        Key('crypto_wallet_activity_card_row_$hash'),
      );
      expect(row, findsOneWidget);
      await tester.tap(row);
      await tester.pumpAndSettle();
      expect(clipboardPayload, equals(hash));
      
      expect(find.text(kActivityCopyTxHashCopied), findsOneWidget);
    });

    testWidgets('error path renders the closed-set error copy',
        (tester) async {
      final stub = _StubVaultAIClient()
        ..throwOn = Exception('network failure');
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(
              asset: 'ETH', authToken: 'tok', apiClient: stub,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_activity_card_error')),
        findsOneWidget,
      );
      expect(find.text(kActivityCopyError), findsOneWidget);
    });

    testWidgets(
        'no_wallet_yet reason renders the create-wallet-first copy',
        (tester) async {
      final stub = _StubVaultAIClient()
        ..respond = (asset) => {
              'status': 'ok',
              'transactionsStatus': 'unavailable',
              'reason': 'no_wallet_yet',
              'transactions': [],
            };
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActivityCard(
              asset: 'ETH', authToken: 'tok', apiClient: stub,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text(kActivityCopyNoWalletYet), findsOneWidget);
    });
  });
}
