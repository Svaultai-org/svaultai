

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/chat/crypto_wallet_action_card.dart';

ChatMessage _buildMsg({
  required String intent,
  String? asset,
  String? network,
  String? amount,
  String? amountUnit,
  String? destination,
  String? blockedReason,
  String message = 'Test wallet chat message.',
}) {
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kCryptoWalletAction,
    payload: {
      'intent': intent,
      if (asset != null) 'asset': asset,
      if (network != null) 'network': network,
      if (amount != null) 'amount': amount,
      if (amountUnit != null) 'amountUnit': amountUnit,
      if (destination != null) 'destinationAddress': destination,
      if (blockedReason != null) 'blockedReason': blockedReason,
    },
  );
}

void main() {
  group('CryptoWalletActionCard — slice 7 chat control', () {
    test('C1: chat kind exposes kCryptoWalletAction', () {
      expect(
        ChatMessage.kCryptoWalletAction,
        equals('crypto_wallet_action'),
      );
    });

    test('C2: isCard returns true for kCryptoWalletAction', () {
      final m = _buildMsg(intent: kCryptoWalletActionIntentShowWallet);
      expect(m.isCard, isTrue);
    });

    test('C10: closed-set intent constants match the backend exactly', () {
      expect(
        kAllCryptoWalletActionIntents.toSet(),
        equals({
          'open_crypto_wallet',
          'show_wallet',
          'show_balance',
          'receive_address',
          'receive_qr',
          'send_draft',
          'show_transactions',
          'unsupported_asset',
          'unsupported_network',
          'monero_special',
          'clarify_network',
        }),
      );
    });

    testWidgets('C3a: show_balance renders the "Balance" header',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentShowBalance,
                asset: 'ETH', network: 'ethereum_sepolia',
                message: 'Opening your Ethereum balance on Sepolia.',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_action_card_header')),
        findsOneWidget,
      );
      expect(find.text('Balance'), findsOneWidget);
    });

    testWidgets('C3b: receive_address renders the "Receive" header',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentReceiveAddress,
                asset: 'ETH', network: 'ethereum_sepolia',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Receive'), findsOneWidget);
    });

    testWidgets('C3c: send_draft renders the "Send review" header',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentSendDraft,
                asset: 'ETH', network: 'ethereum_sepolia',
                amount: '0.01', amountUnit: 'ETH',
                destination: '0x${'ab' * 20}',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Send review'), findsOneWidget);
    });

    testWidgets('C3d: show_wallet renders the "Crypto Vault" header',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(intent: kCryptoWalletActionIntentShowWallet),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Crypto Vault'), findsOneWidget);
    });

    testWidgets('C3e: show_transactions renders the "Transactions" header',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentShowTransactions,
                asset: 'ETH', network: 'ethereum_sepolia',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Transactions'), findsOneWidget);
    });

    testWidgets(
        'C4: card renders the asset chip + network display label',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentShowBalance,
                asset: 'USDT_ERC20', network: 'ethereum_sepolia',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('USDT_ERC20'), findsOneWidget);
      expect(find.text('Ethereum Sepolia testnet'), findsOneWidget);
    });

    testWidgets(
        'C5: tapping the open-panel button fires onAction with the parsed '
        'request', (tester) async {
      CryptoWalletActionRequest? captured;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentReceiveAddress,
                asset: 'ETH', network: 'ethereum_sepolia',
              ),
              onAction: (req) => captured = req,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final btn = find.byKey(
        const Key('crypto_wallet_action_card_open_btn'),
      );
      expect(btn, findsOneWidget);
      await tester.tap(btn);
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.intent, equals(kCryptoWalletActionIntentReceiveAddress));
      expect(captured!.asset, equals('ETH'));
      expect(captured!.network, equals('ethereum_sepolia'));
    });

    testWidgets(
        'C6: send_draft renders amount + destination preview + PIN copy',
        (tester) async {
      const dest = '0xabababababababababababababababababababab';
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentSendDraft,
                asset: 'ETH', network: 'ethereum_sepolia',
                amount: '0.05', amountUnit: 'ETH', destination: dest,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_action_card_send_preview')),
        findsOneWidget,
      );
      expect(find.textContaining('0.05'), findsAtLeastNWidgets(1));
      expect(find.textContaining(dest), findsAtLeastNWidgets(1));
      expect(
        find.textContaining('PIN is required'),
        findsOneWidget,
      );
    });

    testWidgets(
        'C7a: mainnet_disabled blocker hides the open-panel button + '
        'shows the blocker note', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentUnsupportedNetwork,
                asset: 'ETH', network: 'ethereum_mainnet',
                blockedReason: 'mainnet_disabled',
                message: 'Ethereum Mainnet sending is not enabled yet.',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_action_card_open_btn')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_action_card_blocker_note')),
        findsOneWidget,
      );
      expect(
        find.text('Ethereum Mainnet — not enabled'),
        findsOneWidget,
      );
    });

    testWidgets(
        'C7b: monero_special blocker hides the open-panel button',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentMoneroSpecial,
                asset: 'XMR',
                blockedReason: 'monero_special',
                message: 'Monero requires a separate privacy-wallet '
                    'design and is not connected to the live wallet '
                    'engine yet.',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_action_card_open_btn')),
        findsNothing,
      );
      expect(find.text('Monero — special design needed'), findsOneWidget);
    });

    testWidgets(
        'C7c: unsupported_asset blocker hides the open-panel button',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentUnsupportedAsset,
                asset: 'BTC',
                blockedReason: 'unsupported_asset',
                message: 'Bitcoin is not connected to the wallet '
                    'engine yet.',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_action_card_open_btn')),
        findsNothing,
      );
    });

    testWidgets(
        'C7d: engine_disabled blocker hides the open-panel button',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentShowWallet,
                blockedReason: 'engine_disabled',
                message: 'The Crypto Wallet Engine is not yet enabled.',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_action_card_open_btn')),
        findsNothing,
      );
    });

    testWidgets(
        'C7e: missing_send_fields blocker shows the missing-fields note',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletActionCard(
              msg: _buildMsg(
                intent: kCryptoWalletActionIntentSendDraft,
                asset: 'ETH', network: 'ethereum_sepolia',
                blockedReason: 'missing_send_fields',
                message: 'I need both the amount and the destination '
                    'address to prepare a send review.',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_action_card_open_btn')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_action_card_blocker_note')),
        findsOneWidget,
      );
    });

    testWidgets(
        'C8: receive / balance / show_wallet cards do NOT render a 0x address',
        (tester) async {
      for (final intent in const [
        kCryptoWalletActionIntentShowBalance,
        kCryptoWalletActionIntentReceiveAddress,
        kCryptoWalletActionIntentReceiveQr,
        kCryptoWalletActionIntentShowWallet,
        kCryptoWalletActionIntentOpenCryptoWallet,
        kCryptoWalletActionIntentShowTransactions,
      ]) {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: CryptoWalletActionCard(
                msg: _buildMsg(
                  intent: intent,
                  asset: 'ETH', network: 'ethereum_sepolia',
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        final addrRe = RegExp(r'0x[0-9a-fA-F]{40}');
        for (final el in find.byType(Text).evaluate()) {
          final w = el.widget as Text;
          final txt = w.data ?? '';
          expect(
            addrRe.hasMatch(txt), isFalse,
            reason: 'Intent $intent must not render a 0x address: $txt',
          );
        }
      }
    });

    testWidgets(
        'C9: non-send cards do NOT render a numeric balance / tx-hash / fake '
        'amount string', (tester) async {
      for (final intent in const [
        kCryptoWalletActionIntentShowBalance,
        kCryptoWalletActionIntentReceiveAddress,
        kCryptoWalletActionIntentReceiveQr,
        kCryptoWalletActionIntentShowWallet,
        kCryptoWalletActionIntentOpenCryptoWallet,
        kCryptoWalletActionIntentShowTransactions,
      ]) {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: CryptoWalletActionCard(
                msg: _buildMsg(
                  intent: intent,
                  asset: 'ETH', network: 'ethereum_sepolia',
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        final balRe = RegExp(
          r'\d+\.\d+\s*(ETH|BTC|SOL|BNB|USDT|USDC|XMR)',
        );
        for (final el in find.byType(Text).evaluate()) {
          final w = el.widget as Text;
          final txt = w.data ?? '';
          expect(
            balRe.hasMatch(txt), isFalse,
            reason: 'Intent $intent must not render a balance literal: $txt',
          );
        }
      }
    });

    test('payload field shape — send draft round-trips fields', () {
      const dest = '0xfefefefefefefefefefefefefefefefefefefefe';
      final msg = _buildMsg(
        intent: kCryptoWalletActionIntentSendDraft,
        asset: 'USDT_ERC20', network: 'ethereum_sepolia',
        amount: '10', amountUnit: 'USDT_ERC20', destination: dest,
      );
      expect(msg.kind, equals(ChatMessage.kCryptoWalletAction));
      expect(msg.payload?['intent'], equals('send_draft'));
      expect(msg.payload?['asset'], equals('USDT_ERC20'));
      expect(msg.payload?['network'], equals('ethereum_sepolia'));
      expect(msg.payload?['amount'], equals('10'));
      expect(msg.payload?['amountUnit'], equals('USDT_ERC20'));
      expect(msg.payload?['destinationAddress'], equals(dest));
    });
  });
}
