

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_admin_health_panel.dart';


class _FakeHealthClient extends VaultAIClient {
  Map<String, dynamic>? healthResponse;
  Object? throwOnHealth;
  String? lastAdminTokenSeen;

  _FakeHealthClient({this.healthResponse})
      : super(baseUrl: 'http://test.invalid');

  @override
  Future<Map<String, dynamic>> getCryptoWalletHealth({
    required String authToken,
    String? adminToken,
  }) async {
    lastAdminTokenSeen = adminToken;
    if (throwOnHealth != null) throw throwOnHealth!;
    return healthResponse ?? const {
      'status': 'ok',
      'schema': 'crypto_wallet_health_v1',
      'overallStatus': 'ready',
      'networks': [],
      'features': {},
    };
  }
}


Map<String, dynamic> _sampleHealthEnvelope() => const {
      'status':        'ok',
      'schema':        'crypto_wallet_health_v1',
      'overallStatus': 'degraded',
      'networks': [
        {
          'id':                  'ethereum_sepolia',
          'displayName':         'Ethereum Sepolia',
          'status':              'ready',
          'reason':              null,
          'rpcConfigured':       true,
          'rpcReachable':        true,
          'chainIdExpected':     11155111,
          'chainIdObserved':     11155111,
          'nativeBalanceReadReady': true,
          'txIndexerConfigured': true,
          'txIndexerReachable':  true,
          'txIndexerProvider':   'etherscan',
          'tokens': [
            {
              'asset':      'USDT_ERC20',
              'configured': true,
              'readable':   true,
              'reason':     null,
            },
            {
              'asset':      'USDC_ERC20',
              'configured': true,
              'readable':   true,
              'reason':     null,
            },
          ],
          'send': {
            'receiveEnabled': true,
            'sendEnabled':    true,
          },
        },
        {
          'id':                  'ethereum_mainnet',
          'displayName':         'Ethereum Mainnet',
          'status':              'degraded',
          'reason':              'indexer_not_configured',
          'rpcConfigured':       true,
          'rpcReachable':        true,
          'chainIdExpected':     1,
          'chainIdObserved':     1,
          'nativeBalanceReadReady': true,
          'txIndexerConfigured': false,
          'txIndexerReachable':  false,
          'txIndexerProvider':   null,
          'tokens': [
            {
              'asset':      'USDT_ERC20',
              'configured': true,
              'readable':   true,
              'reason':     null,
            },
            {
              'asset':      'USDC_ERC20',
              'configured': false,
              'readable':   false,
              'reason':     'token_contract_not_configured',
            },
          ],
          'send': {
            'mainnetReceiveEnabled':      true,
            'mainnetErc20ReceiveEnabled': true,
            'mainnetSendEnabled':         false,
            'mainnetSendPaused':          false,
            'mainnetBroadcastRateLimit':  3,
            'mainnetBroadcastRateWindowSecs': 60,
          },
        },
      ],
      'features': {
        'walletEngineEnabled':      true,
        'sepoliaReceiveEnabled':    true,
        'sepoliaSendEnabled':       true,
        'mainnetReceiveEnabled':    true,
        'mainnetErc20ReceiveEnabled': true,
        'mainnetSendEnabled':       false,
        'mainnetSendPaused':        false,
        'broadcastRateLimit':       3,
        'broadcastRateWindowSecs':  60,
      },
      'checkedAt': '2026-06-30T00:00:00+00:00',
    };


void main() {
  group('Crypto Wallet features model — slice 13', () {
    test('PF1: fromBackend parses closed-set envelope', () {
      final feats = CryptoWalletFeatures.fromBackend({
        'walletEngineEnabled':      true,
        'sepoliaReceiveEnabled':    true,
        'sepoliaSendEnabled':       true,
        'mainnetReceiveEnabled':    true,
        'mainnetErc20ReceiveEnabled': false,
        'mainnetSendEnabled':       true,
        'mainnetSendPaused':        false,
        'supportedNetworks':        ['ethereum_sepolia', 'ethereum_mainnet'],
        'supportedAssetsByNetwork': {
          'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
        },
      });
      expect(feats.walletEngineEnabled, isTrue);
      expect(feats.mainnetReceiveEnabled, isTrue);
      expect(feats.mainnetErc20ReceiveEnabled, isFalse);
      expect(feats.mainnetSendEnabled, isTrue);
      expect(feats.supportedNetworks,
          equals(['ethereum_sepolia', 'ethereum_mainnet']));
      expect(feats.supportedAssetsByNetwork['ethereum_mainnet'],
          equals(['ETH', 'USDT_ERC20', 'USDC_ERC20']));
    });

    test('PF1b: fromBackend defaults missing keys to safe-off', () {
      final feats = CryptoWalletFeatures.fromBackend(const {});
      expect(feats.walletEngineEnabled, isFalse);
      expect(feats.mainnetReceiveEnabled, isFalse);
      expect(feats.mainnetSendEnabled, isFalse);
    });

    test('PF2: effectiveMainnetSendEnabled requires backend AND build flag',
        () {
      
      final feats = CryptoWalletFeatures.fromBackend(const {
        'mainnetSendEnabled': true,
      });
      expect(feats.mainnetSendEnabled, isTrue);
      
      expect(feats.effectiveMainnetSendEnabled, isFalse);
    });

    test('PF3: paused → effective send disabled', () {
      final feats = CryptoWalletFeatures.fromBackend(const {
        'mainnetSendEnabled': true,
        'mainnetSendPaused':  true,
      });
      expect(feats.mainnetSendPaused, isTrue);
      expect(feats.effectiveMainnetSendEnabled, isFalse);
    });

    test('PF-receive-effective: receive flags also AND with build flag',
        () {
      final feats = CryptoWalletFeatures.fromBackend(const {
        'mainnetReceiveEnabled':    true,
        'mainnetErc20ReceiveEnabled': true,
      });
      
      expect(feats.effectiveMainnetReceiveEnabled, isFalse);
      expect(feats.effectiveMainnetErc20ReceiveEnabled, isFalse);
    });
  });

  group('Admin health panel — slice 13', () {
    testWidgets('PF4 + PF5: renders overall + per-network cards',
        (tester) async {
      final client = _FakeHealthClient(
        healthResponse: _sampleHealthEnvelope(),
      );
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CryptoWalletEngineAdminHealthPanel(
              client: client,
              authToken: 'tok',
              adminToken: 'admin-token-xyz',
            ),
          ),
        ),
      ));
      
      
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      expect(
        find.byKey(const Key(kAdminHealthPanelKey)),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key(kAdminHealthPanelOverallChipKey)),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key(
          '${kAdminHealthPanelNetworkCardKey}_ethereum_sepolia',
        )),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(
          '${kAdminHealthPanelNetworkCardKey}_ethereum_mainnet',
        )),
        findsOneWidget,
      );
      
      expect(find.text(kAdminHealthPanelTitle), findsOneWidget);
      
      expect(find.text(kAdminHealthPanelOverallDegraded), findsWidgets);
    });

    testWidgets('PF6: panel renders no RPC URL / API key text',
        (tester) async {
      
      
      final tainted = Map<String, dynamic>.from(
        _sampleHealthEnvelope(),
      );
      
      tainted['_secret_rpc_url'] = 'https://example.invalid/SECRET';
      final client = _FakeHealthClient(healthResponse: tainted);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CryptoWalletEngineAdminHealthPanel(
              client: client,
              authToken: 'tok',
              adminToken: 'admin-token-xyz',
            ),
          ),
        ),
      ));
      
      
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      
      final urlRe = RegExp(r'https?://');
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(txt.contains('SECRET'), isFalse,
            reason: 'panel leaks secret: $txt');
        expect(urlRe.hasMatch(txt), isFalse,
            reason: 'panel leaks URL: $txt');
      }
    });

    testWidgets('PF7: panel forwards admin token to API client',
        (tester) async {
      final client = _FakeHealthClient(
        healthResponse: _sampleHealthEnvelope(),
      );
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CryptoWalletEngineAdminHealthPanel(
              client: client,
              authToken: 'tok',
              adminToken: 'admin-token-xyz',
            ),
          ),
        ),
      ));
      
      
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      expect(client.lastAdminTokenSeen, equals('admin-token-xyz'));
    });

    testWidgets('PF8: 403 surfaces safe admin-token-required banner',
        (tester) async {
      final client = _FakeHealthClient()
        ..throwOnHealth = Exception('Get wallet health failed (403)');
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: CryptoWalletEngineAdminHealthPanel(
            client: client,
            authToken: 'tok',
          ),
        ),
      ));
      
      
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      expect(
        find.byKey(const Key(kAdminHealthPanelErrorBannerKey)),
        findsOneWidget,
      );
      expect(find.text(kAdminHealthPanelUnauthorizedBanner),
          findsOneWidget);
    });

    testWidgets('PF9: mobile width renders without overflow',
        (tester) async {
      tester.view.physicalSize = const Size(360, 1200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final client = _FakeHealthClient(
        healthResponse: _sampleHealthEnvelope(),
      );
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CryptoWalletEngineAdminHealthPanel(
              client: client,
              authToken: 'tok',
              adminToken: 'admin-token-xyz',
            ),
          ),
        ),
      ));
      
      
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      expect(tester.takeException(), isNull);
    });

    test('PF10: source guard — no debugPrint of envelope/token', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_admin_health_panel.dart',
      ).readAsStringSync();
      final printRe = RegExp(r'(debugPrint|print)\s*\([^)]*\)');
      for (final m in printRe.allMatches(src)) {
        final call = m.group(0)!;
        for (final banned in const [
          'adminToken', 'authToken', 'envelope',
          'rpcUrl', 'apiKey',
        ]) {
          expect(call.contains(banned), isFalse,
              reason: 'debugPrint leaks $banned: $call');
        }
      }
    });

    test('PF11: source guard — no buy/sell/swap/trade/stake/bridge',
        () {
      final src = File(
        'lib/ui/crypto_wallet_engine_admin_health_panel.dart',
      ).readAsStringSync();
      final scrubbed = src.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');
      final stringLit = RegExp(r"'([^'\\]|\\.)*'|" + r'"([^"\\]|\\.)*"');
      final banned = RegExp(
        r'\b(buy|sell|swap|trade|stake|staking|bridge)\b',
        caseSensitive: false,
      );
      for (final m in stringLit.allMatches(scrubbed)) {
        final lit = m.group(0)!;
        expect(banned.hasMatch(lit), isFalse,
            reason: 'panel uses banned word in literal: $lit');
      }
    });
  });
}
