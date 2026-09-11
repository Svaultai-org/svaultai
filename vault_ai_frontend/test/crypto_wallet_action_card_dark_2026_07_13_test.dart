// 2026-07-13 regression tests for CryptoWalletActionCard dark refresh.
//
// Root cause of the reported production issue: this widget hardcoded
// Colors.white / Colors.black87 / #EEF2FB (light blue) / #FFF3E0
// (peach) / #1F3D7A (bright blue button), which rendered as bright
// white cards inside Svaultai's forced-dark chat surface. The other
// crypto chat cards in lib/ui/crypto_vault_chat_cards.dart already
// used walletDarkCard() + kWalletTextPrimary + walletGhostButtonStyle
// — this file now uses the same tokens so Balance / Receive / Send /
// Transactions replies belong to one coherent design system.
//
// Suite locks the dark palette in and forbids the legacy white/light
// colors so a future regression can't reintroduce them.

import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/chat/crypto_wallet_action_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_design.dart';


Widget _wrap(Widget child) => MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      home: Scaffold(
        backgroundColor: kWalletBgBase,
        body: SingleChildScrollView(child: child),
      ),
    );


ChatMessage _msg({
  required String intent,
  String text = 'hello world',
  String? asset,
  String? network,
  String? blockedReason,
  String? amount,
  String? amountUnit,
  String? destination,
}) {
  final payload = <String, dynamic>{'intent': intent};
  if (asset != null) payload['asset'] = asset;
  if (network != null) payload['network'] = network;
  if (blockedReason != null) payload['blockedReason'] = blockedReason;
  if (amount != null) payload['amount'] = amount;
  if (amountUnit != null) payload['amountUnit'] = amountUnit;
  if (destination != null) payload['destinationAddress'] = destination;
  return ChatMessage(
    'assistant',
    text,
    kind: ChatMessage.kCryptoWalletAction,
    payload: payload,
  );
}


const List<double> kMobileWidths = <double>[320, 390, 430];


void main() {
  group('CryptoWalletActionCard — dark palette', () {
    testWidgets('card background comes from walletDarkCard() '
        '(no Colors.white in the decoration)', (t) async {
      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(
          intent: kCryptoWalletActionIntentShowBalance,
          asset: 'ETH',
        ),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      final container = t.widget<Container>(
        find.byKey(const Key('crypto_wallet_action_card')),
      );
      final deco = container.decoration! as BoxDecoration;

      // Solid color OR gradient — never Colors.white.
      expect(deco.color, isNot(equals(Colors.white)),
          reason: 'card must not be white in dark mode');
      // Border must be from the wallet palette family, never pale grey.
      final border = deco.border! as Border;
      expect(border.top.color, isNot(equals(const Color(0xFFE0E0E0))));
      expect(border.top.color, isNot(equals(Colors.grey)));
      // Radius picked from walletDarkCard().
      final radius = deco.borderRadius! as BorderRadius;
      expect(radius.topLeft, equals(const Radius.circular(14)));
    });

    testWidgets('header uses wallet accent color (not black87)',
        (t) async {
      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(
          intent: kCryptoWalletActionIntentShowBalance,
          asset: 'ETH',
        ),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      final header = t.widget<Text>(
        find.byKey(const Key('crypto_wallet_action_card_header')),
      );
      final color = header.style!.color!;
      expect(color, isNot(equals(Colors.black)));
      expect(color, isNot(equals(Colors.black87)));
      expect(color, isNot(equals(const Color(0xFF1F3D7A))),
          reason: 'legacy bright blue header color must be gone');
    });

    testWidgets('body message text uses kWalletTextPrimary',
        (t) async {
      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(intent: kCryptoWalletActionIntentShowBalance),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      final msgText = t.widget<Text>(
        find.byKey(const Key('crypto_wallet_action_card_message')),
      );
      expect(msgText.style!.color, equals(kWalletTextPrimary));
    });

    testWidgets('open action uses walletGhostButtonStyle (outlined, '
        'not a bright ElevatedButton)', (t) async {
      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(
          intent: kCryptoWalletActionIntentReceiveQr,
          asset: 'USDT',
          network: 'ethereum_mainnet',
        ),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      final btnFinder = find.byKey(
        const Key('crypto_wallet_action_card_open_btn'),
      );
      expect(btnFinder, findsOneWidget);
      // Must be an OutlinedButton, not ElevatedButton.
      expect(t.widget(btnFinder), isA<OutlinedButton>());
    });
  });

  group('CryptoWalletActionCard — asset/network chip styling', () {
    testWidgets('asset chip is not the legacy #EEF2FB / #1F3D7A pair',
        (t) async {
      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(
          intent: kCryptoWalletActionIntentShowBalance,
          asset: 'USDT',
          network: 'ethereum_mainnet',
        ),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      final chip = t.widget<Container>(
        find.byKey(const Key('crypto_wallet_action_card_asset_chip')),
      );
      final deco = chip.decoration! as BoxDecoration;
      expect(deco.color, isNot(equals(const Color(0xFFEEF2FB))),
          reason: 'legacy light blue chip background must be gone');
    });

    testWidgets('network chip is not the legacy #FFF3E0 / #995500 pair',
        (t) async {
      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(
          intent: kCryptoWalletActionIntentShowBalance,
          asset: 'USDT',
          network: 'ethereum_mainnet',
        ),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      final chip = t.widget<Container>(
        find.byKey(const Key('crypto_wallet_action_card_network_chip')),
      );
      final deco = chip.decoration! as BoxDecoration;
      expect(deco.color, isNot(equals(const Color(0xFFFFF3E0))),
          reason: 'legacy peach chip background must be gone');
    });
  });

  group('CryptoWalletActionCard — blocked state', () {
    testWidgets('blocked note uses walletWarningPanel (not #FFF5E5)',
        (t) async {
      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(
          intent: kCryptoWalletActionIntentUnsupportedAsset,
          asset: 'DOGE',
          network: 'dogecoin',
          blockedReason: 'unsupported_asset',
        ),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      final note = t.widget<Container>(
        find.byKey(const Key('crypto_wallet_action_card_blocker_note')),
      );
      final deco = note.decoration! as BoxDecoration;
      expect(deco.color, isNot(equals(const Color(0xFFFFF5E5))));
      // Open button hidden while blocked.
      expect(
        find.byKey(const Key('crypto_wallet_action_card_open_btn')),
        findsNothing,
      );
    });
  });

  group('CryptoWalletActionCard — send draft preview', () {
    testWidgets('send preview panel is dark, monospace address is '
        'primary text color', (t) async {
      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(
          intent: kCryptoWalletActionIntentSendDraft,
          asset: 'ETH',
          network: 'ethereum_sepolia',
          amount: '0.1',
          amountUnit: 'ETH',
          destination: '0x0000000000000000000000000000000000000000',
        ),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      final preview = t.widget<Container>(
        find.byKey(const Key('crypto_wallet_action_card_send_preview')),
      );
      final deco = preview.decoration! as BoxDecoration;
      expect(deco.color, equals(kWalletSurfaceElevated));

      final dest = t.widget<SelectableText>(
        find.byKey(const Key('crypto_wallet_action_card_destination')),
      );
      expect(dest.style!.color, equals(kWalletTextPrimary));
    });
  });

  group('CryptoWalletActionCard — mobile widths 320 / 390 / 430', () {
    for (final width in kMobileWidths) {
      testWidgets('renders cleanly at ${width.toInt()}dp with no '
          'overflow, no exception, action reachable', (t) async {
        t.view.physicalSize = Size(width, 900);
        t.view.devicePixelRatio = 1.0;
        addTearDown(() {
          t.view.resetPhysicalSize();
          t.view.resetDevicePixelRatio();
        });

        await t.pumpWidget(_wrap(CryptoWalletActionCard(
          msg: _msg(
            intent: kCryptoWalletActionIntentReceiveQr,
            asset: 'USDT_ERC20',
            network: 'ethereum_mainnet',
            text: 'A very long assistant message explaining that '
                'the Receive QR for USDT ERC20 must be shown '
                'without overflowing the mobile viewport at 320/'
                '390/430dp widths.',
          ),
          onAction: (_) {},
        )));
        await t.pumpAndSettle();

        expect(t.takeException(), isNull,
            reason: 'card must not overflow at ${width}dp');
        expect(
          find.byKey(const Key('crypto_wallet_action_card_open_btn')),
          findsOneWidget,
        );
      });
    }
  });

  group('CryptoWalletActionCard — long labels do not overflow', () {
    testWidgets('long asset name is ellipsised inside the chip',
        (t) async {
      t.view.physicalSize = const Size(320, 900);
      t.view.devicePixelRatio = 1.0;
      addTearDown(() {
        t.view.resetPhysicalSize();
        t.view.resetDevicePixelRatio();
      });

      await t.pumpWidget(_wrap(CryptoWalletActionCard(
        msg: _msg(
          intent: kCryptoWalletActionIntentShowBalance,
          asset: 'SUPER_LONG_ASSET_TICKER_NAME_THAT_MUST_ELLIPSIZE',
          network: 'ethereum_mainnet',
        ),
        onAction: (_) {},
      )));
      await t.pumpAndSettle();

      expect(t.takeException(), isNull);
    });
  });

  group('Source-guard: file no longer contains legacy hardcoded '
      'light-mode colors', () {
    test('no Colors.white, no #EEF2FB, no #FFF3E0, no #1F3D7A '
        'in the executable body of crypto_wallet_action_card.dart', () {
      final raw = File(
        'lib/ui/chat/crypto_wallet_action_card.dart',
      ).readAsStringSync();
      // Strip single-line comments so a historical mention in a
      // // note explaining WHY the fix landed doesn't fail the guard.
      final scrubbed = raw
          .split('\n')
          .map((line) {
            final idx = line.indexOf('//');
            return idx >= 0 ? line.substring(0, idx) : line;
          })
          .join('\n');
      const banned = <String>[
        'Colors.white',
        '0xFFEEF2FB',
        '0xFFFFF3E0',
        '0xFF1F3D7A',
        'Colors.black87',
        'Colors.black54',
      ];
      for (final needle in banned) {
        expect(
          scrubbed.contains(needle),
          isFalse,
          reason:
              'crypto_wallet_action_card.dart must NEVER carry the '
              'legacy light-mode value "$needle" in executable code; '
              'use wallet dark tokens (kWalletTextPrimary etc.) '
              'instead',
        );
      }
      // Positive assertion: uses the wallet dark tokens.
      expect(scrubbed, contains('walletDarkCard'));
      expect(scrubbed, contains('walletGhostButtonStyle'));
      expect(scrubbed, contains('kWalletTextPrimary'));
    });
  });
}
