

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/solana_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_activity_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_solana_send_panel.dart';


class _ActivitySpyClient extends VaultAIClient {
  Map<String, dynamic> nextActivityResponse = {
    'transactionsStatus': 'available',
    'transactions':       [],
  };
  final List<String> activityCalls = [];

  _ActivitySpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactionsNetwork({
    required String network,
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    activityCalls.add('$network/$asset');
    return nextActivityResponse;
  }
}


class _StatusSpyClient extends VaultAIClient {
  Map<String, dynamic> nextDraftResponse = {};
  Map<String, dynamic> nextSecretResponse = {
    'wallet_engine':         'encrypted_secret_ready',
    'encryptedWalletSecret': 'ct-solana-secret',
  };
  Map<String, dynamic> nextBroadcastResponse = {
    'status':    'submitted',
    'signature': _kFakeSignature,
  };
  final List<Map<String, dynamic>> statusCalls = [];
  List<String> nextStatuses = ['pending', 'confirmed'];
  int _statusIdx = 0;

  _StatusSpyClient() : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> createCryptoWalletSendDraftNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String fromAddress,
    required String destinationAddress,
    String? amountEth,
    String? amountSol,
    String? amountUsdt,
  }) async {
    return nextDraftResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    return nextSecretResponse;
  }

  @override
  Future<Map<String, dynamic>>
      broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
    String? draftId,
  }) async {
    return nextBroadcastResponse;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletTransactionStatusNetwork({
    required String network,
    required String asset,
    required String txHash,
    required String authToken,
  }) async {
    statusCalls.add({
      'network': network, 'asset': asset, 'txHash': txHash,
    });
    if (_statusIdx >= nextStatuses.length) {
      _statusIdx = nextStatuses.length - 1;
    }
    final s = nextStatuses[_statusIdx++];
    return {
      'transactionStatus':  s,
      'signature':          txHash,
      'network':            'solana_mainnet',
    };
  }
}


const String _kAddrA =
    'So11111111111111111111111111111111111111112';
const String _kAddrB = '11111111111111111111111111111111';
const String _kBlockhash =
    'FwZbEB4YfDjK6iEy4uP5oXwUTL7jXbGgnh8UyKz4EbCE';
const String _kFakeSignature =
    '4vGVQpTJyGgQMTkwoUn7Xf4WScDW6RxDGNhWQb1QxLGyKcksVezR'
    'GNS4pmH24DngjyfNhBGpAtWxdD8gwucjFCG9';


CryptoWalletFeatures _features({
  bool activityConnected = true,
  bool statusReady = true,
  bool feeReady = true,
}) {
  return CryptoWalletFeatures.fromBackend({
    'walletEngineEnabled':       true,
    'sepoliaReceiveEnabled':     true,
    'sepoliaSendEnabled':        true,
    'mainnetReceiveEnabled':     false,
    'mainnetErc20ReceiveEnabled': false,
    'mainnetSendEnabled':        false,
    'mainnetSendPaused':         false,
    'defaultNetwork':            'ethereum_sepolia',
    'defaultNetworkConfigValid': true,
    'solanaEnabled':             true,
    'solanaReceiveEnabled':      true,
    'solanaBalanceEnabled':      true,
    'solanaSendEnabled':         true,
    'solanaSendPaused':          false,
    'solanaActivityConnected':   activityConnected,
    'solanaStatusReady':         statusReady,
    'solanaFeeReady':            feeReady,
    'supportedNetworks':        const [
      'ethereum_sepolia', 'ethereum_mainnet', 'solana_mainnet',
    ],
    'supportedAssetsByNetwork': const {
      'ethereum_sepolia': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
      'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
      'solana_mainnet':   ['SOL'],
    },
  });
}


final String _fixedTestSecretB58 = () {
  final bytes = Uint8List(64);
  for (var i = 0; i < 32; i++) bytes[i] = (i + 1) & 0xff;
  return base58Encode(bytes);
}();


Future<void> _pumpActivity(
  WidgetTester tester, {
  required _ActivitySpyClient client,
  CryptoWalletFeatures? features,
}) async {
  tester.view.physicalSize = const Size(1200, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: CryptoWalletEngineSolanaActivityCard(
          apiClient: client,
          authToken: 'test-token',
          features: features,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}





const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('CryptoWalletFeatures — new Solana readiness flags', () {
    test('unknown() reports all Solana readiness flags false', () {
      const f = CryptoWalletFeatures.unknown();
      expect(f.solanaActivityConnected, isFalse);
      expect(f.solanaStatusReady, isFalse);
      expect(f.solanaFeeReady, isFalse);
    });

    test('fromBackend parses new flags', () {
      final f = CryptoWalletFeatures.fromBackend({
        'solanaActivityConnected': true,
        'solanaStatusReady':       true,
        'solanaFeeReady':          true,
      });
      expect(f.solanaActivityConnected, isTrue);
      expect(f.solanaStatusReady, isTrue);
      expect(f.solanaFeeReady, isTrue);
    });
  });

  group('Solana fee label helper', () {
    test('rpc_getFeeForMessage → real network fee', () {
      expect(
        solanaSendFeeLabelFor('rpc_getFeeForMessage'),
        equals(kSolanaSendFeeRealLabel),
      );
    });

    test('default_lamports → estimated label', () {
      expect(
        solanaSendFeeLabelFor('default_lamports'),
        equals(kSolanaSendFeeEstimatedLabel),
      );
    });

    test('null or unknown → estimated label', () {
      expect(
        solanaSendFeeLabelFor(null),
        equals(kSolanaSendFeeEstimatedLabel),
      );
      expect(
        solanaSendFeeLabelFor('mystery'),
        equals(kSolanaSendFeeEstimatedLabel),
      );
    });
  });

  group('Solana send status copy helper', () {
    test('all closed-set states map to safe copy', () {
      expect(
        solanaSendStatusCopyFor('confirmed'),
        equals(kSolanaSendStatusConfirmedCopy),
      );
      expect(
        solanaSendStatusCopyFor('failed'),
        equals(kSolanaSendStatusFailedCopy),
      );
      expect(
        solanaSendStatusCopyFor('pending'),
        equals(kSolanaSendStatusPendingCopy),
      );
      expect(
        solanaSendStatusCopyFor('unavailable'),
        equals(kSolanaSendStatusUnavailableCopy),
      );
      expect(
        solanaSendStatusCopyFor(null),
        equals(kSolanaSendStatusPollingCopy),
      );
    });
  });

  group('Solana activity card — no-wallet and rpc-missing states', () {
    testWidgets('renders no-wallet copy when reason=no_wallet_yet',
        (tester) async {
      final client = _ActivitySpyClient();
      client.nextActivityResponse = {
        'transactionsStatus': 'unavailable',
        'reason':             'no_wallet_yet',
        'transactions':       [],
      };
      await _pumpActivity(
        tester, client: client, features: _features(),
      );
      expect(
        find.byKey(const Key(kSolanaActivityNoWalletKey)),
        findsOneWidget,
      );
      expect(
        find.text(kSolanaActivityNoWalletCopy),
        findsOneWidget,
      );
    });

    testWidgets('renders rpc-missing copy when reason=rpc_not_configured',
        (tester) async {
      final client = _ActivitySpyClient();
      client.nextActivityResponse = {
        'transactionsStatus': 'unavailable',
        'reason':             'rpc_not_configured',
        'transactions':       [],
      };
      await _pumpActivity(
        tester, client: client, features: _features(),
      );
      expect(
        find.byKey(const Key(kSolanaActivityRpcMissingKey)),
        findsOneWidget,
      );
    });

    testWidgets('renders empty state when available with zero rows',
        (tester) async {
      final client = _ActivitySpyClient();
      client.nextActivityResponse = {
        'transactionsStatus': 'available',
        'transactions':       [],
      };
      await _pumpActivity(
        tester, client: client, features: _features(),
      );
      expect(
        find.byKey(const Key(kSolanaActivityEmptyKey)),
        findsOneWidget,
      );
    });
  });

  group('Solana activity card — list rendering', () {
    testWidgets(
      'renders signature list with status but no fake amount/direction',
      (tester) async {
        final client = _ActivitySpyClient();
        client.nextActivityResponse = {
          'transactionsStatus': 'available',
          'transactions': [
            {
              'schema':        'crypto_wallet_transaction_v1',
              'txHash':        _kFakeSignature,
              'direction':     'unknown',
              'amount':        null,
              'unit':          'SOL',
              'status':        'confirmed',
              'confirmations': null,
              'timestamp':     1700000000,
              'source':        'rpc_signatures',
            },
            {
              'schema':        'crypto_wallet_transaction_v1',
              'txHash':        _kFakeSignature,
              'direction':     'unknown',
              'amount':        null,
              'unit':          'SOL',
              'status':        'pending',
              'confirmations': null,
              'timestamp':     1699999900,
              'source':        'rpc_signatures',
            },
          ],
        };
        await _pumpActivity(
          tester, client: client, features: _features(),
        );
        expect(
          find.byKey(const Key(kSolanaActivityListKey)),
          findsOneWidget,
        );
        expect(find.text('Confirmed'), findsOneWidget);
        expect(find.text('Pending'), findsOneWidget);

        for (final el in find.byType(Text).evaluate()) {
          final w = el.widget as Text;
          final txt = (w.data ?? '').toLowerCase();
          expect(txt, isNot(contains('in ')),
              reason: 'must not render direction "In" when unknown');
          expect(txt, isNot(contains('out ')),
              reason: 'must not render direction "Out" when unknown');
          expect(
            RegExp(r'-?\d+(\.\d+)?\s*sol').hasMatch(txt),
            isFalse,
            reason: 'must not render fake SOL amount: $txt',
          );
        }
      },
    );

    test('short signature helper truncates', () {
      final short =
          solanaActivityShortSignature(_kFakeSignature);
      expect(short.length, lessThan(_kFakeSignature.length));
      expect(short.startsWith(_kFakeSignature.substring(0, 6)),
          isTrue);
    });

    test('activity status closed-set copy', () {
      expect(
        solanaActivityStatusCopyFor('confirmed'),
        equals(kSolanaActivityStatusConfirmedCopy),
      );
      expect(
        solanaActivityStatusCopyFor('pending'),
        equals(kSolanaActivityStatusPendingCopy),
      );
      expect(
        solanaActivityStatusCopyFor('failed'),
        equals(kSolanaActivityStatusFailedCopy),
      );
      expect(
        solanaActivityStatusCopyFor(null),
        equals(kSolanaActivityStatusUnknownCopy),
      );
    });
  });

  group('Solana send panel — submitted screen polls status', () {
    testWidgets(
      'submitted screen shows real signature + polls status → confirmed',
      (tester) async {
        final client = _StatusSpyClient();
        client.nextDraftResponse = {
          'status':             'draft_ready',
          'schema':             'crypto_wallet_send_draft_v1',
          'asset':              'SOL',
          'network':            'solana_mainnet',
          'fromAddress':        _kAddrA,
          'destinationAddress': _kAddrB,
          'amountSol':          '0.5',
          'lamports':           '500000000',
          'recentBlockhash':    _kBlockhash,
          'feeLamports':        7500,
          'feeSol':             '0.0000075',
          'feeSource':          'rpc_getFeeForMessage',
        };
        client.nextStatuses = ['confirmed'];

        tester.view.physicalSize = const Size(1200, 2400);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
            home: Scaffold(
              body: CryptoWalletEngineSolanaSendPanel(
                authToken: 'test-token',
                fromAddress: _kAddrA,
                client: client,
                decryptForVault: (ct) async => jsonEncode({
                  'schema':          'solana_secret_v1',
                  'keyOrigin':       'generated_client_side',
                  'secretKeyBase58': _fixedTestSecretB58,
                }),
                isVaultKeyAvailable: () => true,
                features: _features(),
                idempotencyKeyGenerator: () => 'sol-fixed-idem',
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();

        await tester.enterText(
          find.byKey(const Key(kSolanaSendDestinationInputKey)),
          _kAddrB,
        );
        await tester.enterText(
          find.byKey(const Key(kSolanaSendAmountInputKey)),
          '0.5',
        );
        await tester.tap(
          find.byKey(const Key(kSolanaSendReviewButtonKey)),
        );
        await tester.pumpAndSettle();


        expect(
          find.text(kSolanaSendFeeRealLabel),
          findsOneWidget,
        );

        await tester.tap(
          find.byKey(const Key(kSolanaSendConfirmButtonKey)),
        );
        await tester.pumpAndSettle();


        expect(
          find.byKey(const Key(kSolanaSendSubmittedCardKey)),
          findsOneWidget,
        );
        expect(
          find.text(_kFakeSignature),
          findsOneWidget,
        );


        expect(
          find.byKey(const Key('solana_send_panel_status_text')),
          findsOneWidget,
        );
        expect(
          find.text(kSolanaSendStatusPendingCopy),
          findsOneWidget,
        );


        for (var i = 0; i < 5; i++) {
          await tester.pump(const Duration(seconds: 3));
          await tester.pumpAndSettle();
          if (client.statusCalls.isNotEmpty) break;
        }

        expect(client.statusCalls.length, greaterThanOrEqualTo(1));
        expect(
          find.text(kSolanaSendStatusConfirmedCopy),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'estimated fee label appears when feeSource is default_lamports',
      (tester) async {
        final client = _StatusSpyClient();
        client.nextDraftResponse = {
          'status':             'draft_ready',
          'schema':             'crypto_wallet_send_draft_v1',
          'asset':              'SOL',
          'network':            'solana_mainnet',
          'fromAddress':        _kAddrA,
          'destinationAddress': _kAddrB,
          'amountSol':          '0.5',
          'lamports':           '500000000',
          'recentBlockhash':    _kBlockhash,
          'feeLamports':        5000,
          'feeSol':             '0.000005',
          'feeSource':          'default_lamports',
        };
        tester.view.physicalSize = const Size(1200, 2400);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
            home: Scaffold(
              body: CryptoWalletEngineSolanaSendPanel(
                authToken: 'test-token',
                fromAddress: _kAddrA,
                client: client,
                decryptForVault: (ct) async => jsonEncode({
                  'schema':          'solana_secret_v1',
                  'keyOrigin':       'generated_client_side',
                  'secretKeyBase58': _fixedTestSecretB58,
                }),
                isVaultKeyAvailable: () => true,
                features: _features(feeReady: false),
                idempotencyKeyGenerator: () => 'sol-fixed-idem2',
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(const Key(kSolanaSendDestinationInputKey)),
          _kAddrB,
        );
        await tester.enterText(
          find.byKey(const Key(kSolanaSendAmountInputKey)),
          '0.5',
        );
        await tester.tap(
          find.byKey(const Key(kSolanaSendReviewButtonKey)),
        );
        await tester.pumpAndSettle();
        expect(
          find.text(kSolanaSendFeeEstimatedLabel),
          findsOneWidget,
        );
      },
    );
  });

  group('non-exchange surface', () {
    test('activity card copy contains no exchange verbs', () {
      final blobs = [
        kSolanaActivityCardHeading,
        kSolanaActivityNoWalletCopy,
        kSolanaActivityRpcMissingCopy,
        kSolanaActivityEmptyCopy,
        kSolanaActivityErrorCopy,
        kSolanaActivityDirectionLabel,
      ];
      for (final b in blobs) {
        final lower = b.toLowerCase();
        for (final banned in ['swap ', 'stake ', 'bridge ',
                              ' buy ', ' sell ', ' trade ']) {
          expect(lower, isNot(contains(banned)),
              reason: 'activity card copy leaked: $b');
        }
      }
    });

    test('status/fee copy constants have no exchange verbs', () {
      final blobs = [
        kSolanaSendFeeEstimatedLabel,
        kSolanaSendFeeRealLabel,
        kSolanaSendFeeUnavailableLabel,
        kSolanaSendStatusPollingCopy,
        kSolanaSendStatusPendingCopy,
        kSolanaSendStatusConfirmedCopy,
        kSolanaSendStatusFailedCopy,
        kSolanaSendStatusUnavailableCopy,
      ];
      for (final b in blobs) {
        final lower = b.toLowerCase();
        for (final banned in ['swap ', 'stake ', 'bridge ',
                              ' buy ', ' sell ', ' trade ']) {
          expect(lower, isNot(contains(banned)),
              reason: 'status/fee copy leaked: $b');
        }
      }
    });
  });
}
