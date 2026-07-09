


import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';


String _readLib(String relativePath) {
  return File(
    '${Directory.current.path}/lib/$relativePath',
  ).readAsStringSync().replaceAll('\r\n', '\n');
}




void main() {

  group('Source guardrails — billing timeout/error does NOT full-page '
      'block the Crypto Vault section', () {

    test('_buildCryptoVaultSection has no "if (!app.isBillingLoaded)" '
        'top-level early-return anymore', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('Widget _buildCryptoVaultSection(');
      expect(start, greaterThan(0),
          reason: '_buildCryptoVaultSection must still exist');


      final scope = src.substring(start, start + 4000);
      expect(
        scope.contains('if (!app.isBillingLoaded) {'),
        isFalse,
        reason: 'Legacy full-page gate is forbidden — billing loading '
            'must not block the crypto vault shell.',
      );
    });

    test('_buildCryptoVaultSection composes a compact overlay banner '
        'over the engine content when billing is loading or errored', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('Widget _buildCryptoVaultSection(');
      final end = src.indexOf('Widget _buildCryptoVaultEngineContent(');
      expect(start, greaterThan(0));
      expect(end, greaterThan(start),
          reason: 'engine content helper must be extracted');

      final scope = src.substring(start, end);
      expect(
        scope.contains('_CryptoVaultBillingStatusBanner('),
        isTrue,
        reason: 'the section must mount the compact banner overlay on '
            'top of the engine content when billing is not confirmed '
            'loaded.',
      );
      expect(
        scope.contains('Positioned.fill(child: content)'),
        isTrue,
        reason: 'crypto vault content must fill the whole area so the '
            'banner is only an overlay, never a strip that pushes '
            'content down.',
      );
      expect(
        scope.contains('billingLoading || billingErrored'),
        isTrue,
        reason: 'banner must appear both while loading AND on error '
            '— never as a full-page block.',
      );
      expect(
        scope.contains('_cryptoBillingBannerDismissed'),
        isTrue,
        reason: 'banner must gate on the dismissed state so it '
            'disappears when the user closes it.',
      );
    });

    test('Engine content helper is called for both known-upgraded and '
        'unknown-billing paths', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('Widget _buildCryptoVaultSection(');
      expect(start, greaterThan(0));


      final scope = src.substring(start, start + 4000);
      expect(
        scope.contains('_buildCryptoVaultEngineContent(app, isMobile)'),
        isTrue,
        reason: 'section must fall through to the engine helper when '
            'the user is not known-not-upgraded (i.e. billing is '
            'loaded+upgraded, OR billing is loading/errored).',
      );
    });

    test('Locked (subscription) card only appears when we KNOW the '
        'user is not upgraded, not just because billing timed out', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('Widget _buildCryptoVaultSection(');
      final end = src.indexOf('Widget _buildCryptoVaultEngineContent(');
      final scope = src.substring(start, end);

      expect(
        scope.contains('isKnownNotUpgraded'),
        isTrue,
        reason: 'code must use the explicit isKnownNotUpgraded gate.',
      );
      expect(
        scope.contains('billingLoaded'),
        isTrue,
        reason: 'the "known" side of the gate must depend on '
            'billingLoaded — never on an unknown billing state.',
      );
      expect(
        scope.contains('billingBlockCount > 0'),
        isTrue,
        reason: 'the subscription enforcement math (block count / '
            'purchased bytes > 0) must still be checked — this is '
            'the real subscription gate.',
      );
      expect(
        scope.contains('billingPurchasedBytes > 0'),
        isTrue,
        reason: 'subscription enforcement must still check '
            'purchased-bytes > 0.',
      );
    });

    test('Crypto Vault section never routes billing failure through '
        'the removed _CryptoVaultAccessErrorCard', () {
      final src = _readLib('main.dart');
      expect(
        src.contains('_CryptoVaultAccessErrorCard'),
        isFalse,
        reason: 'the full-page timeout card widget must be removed.',
      );
      expect(
        src.contains('Access check timed out. Please retry.'),
        isFalse,
        reason: 'the loud full-page timeout copy must be removed — '
            'the compact banner uses "Subscription status is '
            'temporarily unavailable." instead.',
      );
      expect(
        src.contains('Subscription status is temporarily unavailable.'),
        isTrue,
        reason: 'the banner copy must be the short, compact form.',
      );
    });
  });


  group('Widget behavior — non-blocking banner', () {

    testWidgets('banner renders "loading" state when billing is loading',
        (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: _bannerForTest(errored: false, onRetry: () {}),
        ),
      ));
      await tester.pump();

      expect(
        find.byKey(const Key('crypto_vault_billing_status_banner')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_vault_billing_banner_loading_icon')),
        findsOneWidget,
      );
      expect(find.text('Checking subscription status…'), findsOneWidget);


      expect(
        find.byKey(const Key('crypto_vault_access_error_retry_button')),
        findsNothing,
        reason: 'no retry button while merely loading',
      );
    });

    testWidgets('banner renders "error" state with Retry button when '
        'billing errored', (tester) async {
      var retries = 0;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: _bannerForTest(errored: true, onRetry: () => retries++),
        ),
      ));
      await tester.pump();

      expect(
        find.byKey(const Key('crypto_vault_billing_status_banner')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_vault_billing_banner_error_icon')),
        findsOneWidget,
      );
      expect(
        find.text('Subscription status is temporarily unavailable.'),
        findsOneWidget,
      );

      final retry =
          find.byKey(const Key('crypto_vault_access_error_retry_button'));
      expect(retry, findsOneWidget);
      await tester.tap(retry);
      await tester.pump();
      expect(retries, 1,
          reason: 'Retry button must invoke the provided callback');
    });

    testWidgets('banner does not overflow at 360 x 720 mobile viewport',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: _bannerForTest(errored: true, onRetry: () {}),
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });


  group('Source guardrail — retry hook still exists', () {
    test('main.dart still exposes retryBilling()', () {
      final src = _readLib('main.dart');
      expect(
        src.contains('Future<void> retryBilling()'),
        isTrue,
        reason: 'AppState must still expose retryBilling() so the '
            'banner Retry button has a hook to call.',
      );
    });

    test('banner still uses the crypto_vault_access_error_retry_button '
        'key so integration tests can pin the retry action', () {
      final src = _readLib('main.dart');
      expect(
        src.contains("Key('crypto_vault_access_error_retry_button')"),
        isTrue,
        reason: 'retry button key must remain stable for tests.',
      );
    });
  });
}




Widget _bannerForTest({required bool errored, required VoidCallback onRetry}) {
  return _TestOnlyBannerHarness(errored: errored, onRetry: onRetry);
}




class _TestOnlyBannerHarness extends StatelessWidget {
  final bool errored;
  final VoidCallback onRetry;
  const _TestOnlyBannerHarness({
    required this.errored,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    final label = errored
        ? 'Subscription status is temporarily unavailable.'
        : 'Checking subscription status…';
    return Container(
      key: const Key('crypto_vault_billing_status_banner'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: const BoxDecoration(
        color: Color(0xFF262626),
        border: Border(
          bottom: BorderSide(color: Color(0x1AFFFFFF)),
        ),
      ),
      child: Row(
        children: [
          Icon(
            errored
                ? Icons.cloud_off_outlined
                : Icons.hourglass_top_outlined,
            key: Key(errored
                ? 'crypto_vault_billing_banner_error_icon'
                : 'crypto_vault_billing_banner_loading_icon'),
            color: const Color(0xFFEFB66B),
            size: 18,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              label,
              key: const Key('crypto_vault_billing_banner_message'),
              style: const TextStyle(
                color: Color(0xFFDDDDDD),
                fontSize: 13,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (errored) ...[
            const SizedBox(width: 10),
            TextButton(
              key: const Key('crypto_vault_access_error_retry_button'),
              onPressed: onRetry,
              style: TextButton.styleFrom(
                foregroundColor: const Color(0xFFE6E6E6),
                padding: const EdgeInsets.symmetric(
                  horizontal: 10, vertical: 6,
                ),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              child: const Text('Retry'),
            ),
          ],
        ],
      ),
    );
  }
}
