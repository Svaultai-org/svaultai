
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart' as vcr;
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';




Widget _wrap(Widget child) => MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Scaffold(body: child),
    );


Map<String, dynamic> _cryptoShowVaultEnv({
  required bool locked,
  bool available = true,
}) {
  return <String, dynamic>{
    'intent': 'vault_crypto_delegated',
    'card': {
      'schema':   'vault_chat_router_v1',
      'cardType': 'vault_crypto_delegated_card',
      'innerIntent': 'crypto_vault_show_vault',
      'innerCard': {
        'schema':   'crypto_vault_chat.v1',
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'vault_crypto_overview_data.v1',
          'available': available,
          'assets':    <dynamic>[],
          'locked':    locked,
          'entitlement':
              locked ? 'upgrade_required' : 'upgraded',
          'tier':      locked ? 'free' : 'upgraded',
        },
      },
    },
  };
}

void main() {

  group('Bug 2 — Crypto Vault chat entitlement gate', () {
    testWidgets(
      'non-entitled user sees Upgrade required — not Open Crypto '
      'Vault',
      (t) async {
        final env = _cryptoShowVaultEnv(locked: true);
        var openedVault = false;
        var openedUpgrade = false;
        await t.pumpWidget(_wrap(VaultChatCardView(
          response: vcr.VaultChatResponse.fromJson(env),
          onOpenVault: () => openedVault = true,
          onOpenCryptoUpgrade: () => openedUpgrade = true,
          cryptoEntitled: false,
        )));
        await t.pumpAndSettle();


        expect(
          find.byKey(const Key(
              'crypto_vault_chat_show_vault_upgrade_btn')),
          findsOneWidget,
          reason:
              'non-entitled user must see the Upgrade required CTA',
        );
        expect(
          find.byKey(const Key(
              'crypto_vault_chat_show_vault_open_btn')),
          findsNothing,
          reason:
              'the Open Crypto Vault affordance must NOT render for a '
              'non-entitled user',
        );

        await t.tap(find.byKey(const Key(
            'crypto_vault_chat_show_vault_upgrade_btn')));
        await t.pump();
        expect(openedUpgrade, isTrue);
        expect(openedVault, isFalse);
      },
    );

    testWidgets(
      'entitled user sees Open Crypto Vault — not Upgrade required',
      (t) async {
        final env = _cryptoShowVaultEnv(locked: false);
        var openedVault = false;
        await t.pumpWidget(_wrap(VaultChatCardView(
          response: vcr.VaultChatResponse.fromJson(env),
          onOpenVault: () => openedVault = true,
          onOpenCryptoUpgrade: () {},
          cryptoEntitled: true,
        )));
        await t.pumpAndSettle();

        expect(
          find.byKey(const Key(
              'crypto_vault_chat_show_vault_open_btn')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(
              'crypto_vault_chat_show_vault_upgrade_btn')),
          findsNothing,
        );

        await t.tap(find.byKey(const Key(
            'crypto_vault_chat_show_vault_open_btn')));
        await t.pump();
        expect(openedVault, isTrue);
      },
    );

    testWidgets(
      'client-side cryptoEntitled=false overrides a stale server '
      'locked=false card',
      (t) async {

        final env = _cryptoShowVaultEnv(locked: false);
        await t.pumpWidget(_wrap(VaultChatCardView(
          response: vcr.VaultChatResponse.fromJson(env),
          onOpenVault: () {},
          onOpenCryptoUpgrade: () {},

          cryptoEntitled: false,
        )));
        await t.pumpAndSettle();

        expect(
          find.byKey(const Key(
              'crypto_vault_chat_show_vault_upgrade_btn')),
          findsOneWidget,
          reason: 'client-side entitlement is authoritative when the '
              'server snapshot is stale',
        );
        expect(
          find.byKey(const Key(
              'crypto_vault_chat_show_vault_open_btn')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'server locked=true overrides a stale client cryptoEntitled=true',
      (t) async {

        final env = _cryptoShowVaultEnv(locked: true);
        await t.pumpWidget(_wrap(VaultChatCardView(
          response: vcr.VaultChatResponse.fromJson(env),
          onOpenVault: () {},
          onOpenCryptoUpgrade: () {},
          cryptoEntitled: true,
        )));
        await t.pumpAndSettle();


        expect(
          find.byKey(const Key(
              'crypto_vault_chat_show_vault_upgrade_btn')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(
              'crypto_vault_chat_show_vault_open_btn')),
          findsNothing,
        );
      },
    );
  });


  group(
    'Bug 3 — media viewer Close: uses dCtx + useRootNavigator:false '
    '(source guard)',
    () {
      testWidgets(
          'all five media dialogs use useRootNavigator: false and '
          'pop the dialog context, not the outer chat context',
          (t) async {
        // Static source-scan: we can't stand up the full ChatDashboard
        // page in a widget test without provider + backend, so instead
        // guard the fix by asserting the exact code shape lives in
        // main.dart. Regression sentinel — mirrors how earlier
        // audits already lock the drawer + composer wiring.
        //
        // The pre-fix production code did:
        //   showDialog(context: context, builder: (_) => AlertDialog(
        //     actions: [TextButton(
        //       onPressed: () => Navigator.pop(context),
        //     ),],
        //   ));
        // which — when combined with a HtmlElementView video whose
        // blob URL was revoked synchronously in the `finally` — was
        // observed to trigger a Flutter web shell reload, landing the
        // user on /pin.
        //
        // The fix installs (a) useRootNavigator: false to keep the
        // dialog on the enclosing navigator, (b) Navigator.pop(dCtx)
        // to guarantee we pop the dialog route, and (c) a
        // WidgetsBinding.addPostFrameCallback + Future.delayed +
        // try/catch around player.dispose() so the blob revocation
        // never races the platform-view detach.

        final source = File('lib/main.dart').readAsStringSync();

        for (final key in const [
          'media_video_dialog_close',
          'media_metadata_dialog_close',
          'text_viewer_dialog_close',
          'image_viewer_dialog_close',
          'attachment_preview_dialog_close',
        ]) {
          expect(source.contains(key), isTrue,
              reason: 'Close key $key missing from main.dart');
        }

        expect(
          RegExp(r"useRootNavigator:\s*false").allMatches(source).length,
          greaterThanOrEqualTo(5),
          reason:
              'each of the 5 media dialogs must call showDialog with '
              'useRootNavigator: false',
        );


        expect(
          source.contains('addPostFrameCallback') &&
              source.contains('player.dispose()'),
          isTrue,
          reason:
              'video-dialog dispose must be deferred to a '
              'post-frame + Future.delayed to prevent MediaError '
              'from racing the platform-view detach',
        );


        expect(
          source
                  .contains('onPressed: () => Navigator.pop(dCtx)') ||
              source.contains('Navigator.pop(dCtx)'),
          isTrue,
          reason:
              'Close must pop the dialog context (dCtx), not the '
              'enclosing chat page context — see diagnosis',
        );
      });

      testWidgets(
          'media_player_web routes blob-URL MediaError into a visible '
          'errorNotifier, not silent swallow', (t) async {
        final src = File('lib/media_player_web.dart').readAsStringSync();
        expect(
          RegExp(r"\.onError\.listen").allMatches(src).length,
          greaterThanOrEqualTo(2),
          reason:
              'both VideoElement and AudioElement must attach an '
              'onError listener so the browser error cannot bubble to '
              'window.onerror (which was observed to reload the '
              'Flutter web shell). The listener body must NOT be a '
              'silent no-op — it must push the failure into a visible '
              'errorNotifier so the dialog can render a controlled '
              'error banner.',
        );
        expect(src.contains('errorNotifier.value ='), isTrue,
            reason:
                'the onError listener must write into errorNotifier so '
                'the dialog renders a controlled error banner instead '
                'of silently hiding the failure');
        expect(src.contains('ValueNotifier<String?>'), isTrue);

        expect(
          src.contains('_errorSubs.add') &&
              src.contains('sub.cancel()') &&
              src.contains('_errorSubs.clear()'),
          isTrue,
          reason:
              'onError subscriptions must be retained and cancelled '
              'in dispose() before the blob URL is revoked — otherwise '
              'a late-fired error reaches a disposed notifier',
        );
        expect(
          src.contains('errorNotifier.dispose()'),
          isTrue,
          reason:
              'errorNotifier must be disposed to release its listener '
              'chain when the dialog closes',
        );
        expect(src.contains('bool _disposed'), isTrue,
            reason: 'dispose() must be idempotent (a re-entry guard)');

        final mainSrc = File('lib/main.dart').readAsStringSync();
        expect(
          mainSrc.contains('media_video_dialog_error_banner'),
          isTrue,
          reason:
              'the video dialog must render a visible error banner '
              'wired to player.errorNotifier',
        );
      });
    },
  );
}
