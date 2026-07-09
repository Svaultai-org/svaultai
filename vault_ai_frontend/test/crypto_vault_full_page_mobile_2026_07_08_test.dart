
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_locked_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


const List<Size> kMobileWidths = <Size>[
  Size(360, 800),
  Size(390, 844),
  Size(400, 900),
  Size(430, 932),
];


Future<void> _pumpAt(
  WidgetTester tester,
  Widget child, {
  required Size size,

  double taller = 2.0,
}) async {
  tester.view.physicalSize = Size(size.width, size.height * taller);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(
    MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: child),
    ),
  );
  await tester.pumpAndSettle(const Duration(seconds: 4));
}


CryptoWalletFeatures _featuresReceiveOnlyEth() {
  return const CryptoWalletFeatures(
    walletEngineEnabled:       true,
    sepoliaReceiveEnabled:     false,
    sepoliaSendEnabled:        false,
    mainnetReceiveEnabled:     true,
    mainnetErc20ReceiveEnabled: true,
    mainnetSendEnabled:        false,
    mainnetSendPaused:         true,
    defaultNetwork:            'ethereum_mainnet',
    defaultNetworkConfigValid: true,
    solanaEnabled:             false,
    solanaReceiveEnabled:      false,
    solanaBalanceEnabled:      false,
    solanaSendEnabled:         false,
    solanaSendPaused:          false,
    solanaActivityConnected:   false,
    solanaStatusReady:         false,
    solanaFeeReady:            false,
    tronEnabled:               false,
    tronReceiveEnabled:        false,
    tronBalanceEnabled:        false,
    tronSendEnabled:           false,
    tronSendPaused:            false,
    tronActivityConnected:     false,
    tronUsdtContractConfigured: false,
    xmrEnabled:                true,
    xmrReceiveEnabled:         true,
    xmrBalanceEnabled:         false,
    xmrSendEnabled:            false,
    xmrActivityConnected:      false,
    xmrScannerMode:            'client_local',
    xmrClientScannerSupported: false,
    xmrBackendScannerEnabled:  false,
    supportedNetworks:         ['ethereum_mainnet'],
    supportedAssetsByNetwork:  {},
  );
}


Widget _detailPage(String asset, {String? network,
    CryptoWalletFeatures? features}) {
  return CryptoWalletEngineAssetDetailPage(
    asset: asset,
    network: network,
    features: features,
  );
}


void _forEachMobile(String description,
    Widget Function() build) {
  for (final size in kMobileWidths) {
    testWidgets(
      '$description @ ${size.width.toInt()}x${size.height.toInt()}',
      (tester) async {
        await _pumpAt(tester, build(), size: size);
        expect(
          tester.takeException(),
          isNull,
          reason: '$description raised at '
              '${size.width}×${size.height}',
        );
      },
    );
  }
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {


  group('Crypto Vault dashboard (CryptoWalletEnginePage)', () {
    _forEachMobile('renders without exception',
        () => const CryptoWalletEnginePage());

    _forEachMobile('renders key sections',
        () => const CryptoWalletEnginePage());


    testWidgets('mobile 360 renders every named section without exception',
        (tester) async {
      await _pumpAt(tester, const CryptoWalletEnginePage(),
          size: const Size(360, 900));
      expect(tester.takeException(), isNull);
      for (final k in const [
        'crypto_wallet_engine_portfolio_summary',
        'crypto_wallet_engine_primary_actions',
        'crypto_wallet_engine_asset_grid',
        'crypto_wallet_engine_activity_section',
        'crypto_wallet_engine_security_section',
        'crypto_wallet_engine_ask_ai_section',
      ]) {
        expect(find.byKey(Key(k)), findsOneWidget,
            reason: 'section $k missing at 360×900');
      }
    });
  });


  group('ETH detail page (no wiring — no-wallet state)', () {
    _forEachMobile('renders empty state',
        () => _detailPage('ETH', network: kEvmNetworkEthereumMainnet));
  });

  group('ETH detail page (receive-only features)', () {
    _forEachMobile(
      'renders with receive-only features fixture',
      () => _detailPage('ETH',
          network: kEvmNetworkEthereumMainnet,
          features: _featuresReceiveOnlyEth()),
    );
  });


  group('USDT ERC20 detail page', () {
    _forEachMobile(
      'renders empty state',
      () => _detailPage('USDT_ERC20',
          network: kEvmNetworkEthereumMainnet),
    );
  });

  group('USDC ERC20 detail page', () {
    _forEachMobile(
      'renders empty state',
      () => _detailPage('USDC_ERC20',
          network: kEvmNetworkEthereumMainnet),
    );
  });


  group('SOL detail page', () {
    _forEachMobile(
      'renders empty state',
      () => _detailPage('SOL', network: kSolanaNetworkId),
    );
  });


  group('USDT TRC20 detail page', () {
    _forEachMobile(
      'renders empty state',
      () => _detailPage('USDT_TRC20', network: kTronNetworkId),
    );
  });


  group('XMR detail page (scanner-gated by default)', () {
    _forEachMobile(
      'renders scanner-gated / no-wallet state',
      () => _detailPage('XMR', network: kMoneroNetworkId),
    );
  });


  group('CryptoVaultLockedCard (envelope=null)', () {
    _forEachMobile(
      'renders locked state without exception',
      () => const CryptoVaultLockedCard(),
    );
  });

  group('CryptoVaultLockedCard (envelope + free tier)', () {
    _forEachMobile(
      'renders locked-with-envelope state',
      () => const CryptoVaultLockedCard(
        tier: 'free',
        envelope: <String, dynamic>{
          'crypto_vault_locked': true,
          'reason': 'plan_upgrade_required',
        },
      ),
    );
  });


  group('CryptoVaultLitePage', () {
    _forEachMobile(
      'renders empty saved-records state',
      () => const CryptoVaultLitePage(),
    );
  });


  group('Content invariants at mobile widths', () {
    testWidgets(
      'dashboard @ 360x900 contains no obsolete placeholder copy',
      (tester) async {
        await _pumpAt(tester, const CryptoWalletEnginePage(),
            size: const Size(360, 900));
        expect(tester.takeException(), isNull);
        for (final banned in <String>[
          'Coming next', 'Coming soon',
          'Privacy wallet later',
          'No Send, no Receive, no QR',
        ]) {
          expect(
            find.textContaining(banned, findRichText: true),
            findsNothing,
            reason: 'dashboard shows obsolete copy "$banned"',
          );
        }
      },
    );

    testWidgets(
      'XMR detail @ 360x900 does NOT show a fake zero balance',
      (tester) async {
        await _pumpAt(tester,
            _detailPage('XMR', network: kMoneroNetworkId),
            size: const Size(360, 900));
        expect(tester.takeException(), isNull);

        expect(
          find.textContaining(
            RegExp(r'^\s*0(?:\.0+)?\s+XMR\b'),
            findRichText: true,
          ),
          findsNothing,
          reason: 'XMR must not render a fake "0 XMR" balance',
        );
      },
    );

    testWidgets(
      'no exchange verbs in any 360×900 crypto surface',
      (tester) async {

        final surfaces = <Widget>[
          const CryptoWalletEnginePage(),
          _detailPage('ETH', network: kEvmNetworkEthereumMainnet),
          _detailPage('USDT_ERC20',
              network: kEvmNetworkEthereumMainnet),
          _detailPage('USDC_ERC20',
              network: kEvmNetworkEthereumMainnet),
          _detailPage('SOL', network: kSolanaNetworkId),
          _detailPage('USDT_TRC20', network: kTronNetworkId),
          _detailPage('XMR', network: kMoneroNetworkId),
        ];

        for (int i = 0; i < surfaces.length; i++) {
          await _pumpAt(tester, surfaces[i],
              size: const Size(360, 900));
          expect(tester.takeException(), isNull,
              reason: 'surface #$i raised');

          for (final v in const <String>[
            'Buy crypto', 'Sell crypto', 'Swap crypto',
            'Trade crypto', 'Stake crypto', 'Bridge crypto',
            'Convert crypto',
          ]) {
            expect(
              find.textContaining(v, findRichText: true),
              findsNothing,
              reason: 'surface #$i renders exchange verb "$v"',
            );
          }
        }
      },
    );

    testWidgets(
      'XMR detail @ 360x900 does not render a "Send XMR" button',
      (tester) async {
        await _pumpAt(tester,
            _detailPage('XMR', network: kMoneroNetworkId),
            size: const Size(360, 900));
        expect(tester.takeException(), isNull);

        expect(
          find.widgetWithText(FilledButton, 'Send XMR'),
          findsNothing,
        );
        expect(
          find.widgetWithText(OutlinedButton, 'Send XMR'),
          findsNothing,
        );
        expect(
          find.widgetWithText(ElevatedButton, 'Send XMR'),
          findsNothing,
        );
      },
    );

    testWidgets(
      'no "Aisha" in generic copy on any mobile-pumped crypto surface',
      (tester) async {
        final surfaces = <Widget>[
          const CryptoWalletEnginePage(),
          _detailPage('ETH', network: kEvmNetworkEthereumMainnet),
          _detailPage('XMR', network: kMoneroNetworkId),
          const CryptoVaultLockedCard(),
          const CryptoVaultLitePage(),
        ];
        for (int i = 0; i < surfaces.length; i++) {
          await _pumpAt(tester, surfaces[i],
              size: const Size(360, 900));
          expect(tester.takeException(), isNull);
          expect(
            find.textContaining(
              RegExp(r'\bAisha\b', caseSensitive: false),
              findRichText: true,
            ),
            findsNothing,
            reason: 'surface #$i shows generic "Aisha" copy',
          );
        }
      },
    );
  });
}
