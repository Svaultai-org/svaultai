import 'dart:async';
import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';
import 'package:vault_ai_frontend/services/asset_live_store.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/ethereum_transaction.dart';
import 'package:vault_ai_frontend/services/local_outgoing_tx_store.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';

import 'asset_catalog_2026_10_09_test.dart'
    show catalogFixture, paxgDraftFixture;

// Offline client/UI fixtures only. The deliberately public Ethereum key 1 is
// never stored, logged, funded or sent to a socket/provider.
const _key = '0000000000000000000000000000000000000000000000000000000000000001';
const _sender = '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf';
const _recipient = '0x2222222222222222222222222222222222222222';
const _network = 'ethereum_mainnet';
const _amount = '1.000000000000000001';
final _features = CryptoWalletFeatures.fromBackend({
  'walletEngineEnabled': true,
  'mainnetReceiveEnabled': true,
  'mainnetErc20ReceiveEnabled': true,
  'mainnetSendEnabled': true,
  'mainnetSendPaused': false,
});

Map<String, dynamic> _balance(String asset, String address) => {
      'asset': asset,
      'networkId': _network,
      'chainId': 1,
      'publicAddress': address,
      'balanceStatus': 'available',
      'unit': asset == 'ETH' ? 'ETH' : 'PAXG',
      'weiAmount': '2000000000000000000',
      'spendableBalanceWei': '2000000000000000000',
      'availableAmount': '2',
      'baseUnits': '2000000000000000000',
      'decimals': 18,
      'tokenContract': kPaxgContractAddress,
    };

class _Client extends VaultAIClient {
  _Client() : super(baseUrl: 'http://offline.invalid');
  int keyCalls = 0;
  int broadcasts = 0;
  int balanceCalls = 0;
  int historyWrites = 0;
  String? quotedAmount;
  Map<String, dynamic> feeOverrides = {};
  Map<String, dynamic> balanceOverrides = {};
  bool balanceThrows = false;
  bool malformedBroadcast = false;
  bool mismatchedBroadcastHash = false;
  String? broadcastWalletEngine;
  Completer<Map<String, dynamic>>? balanceGate;
  Completer<Map<String, dynamic>>? broadcastGate;
  String? signed;

  @override
  Future<Map<String, dynamic>> postCryptoWalletPaxgOutgoingHistoryCiphertext({
    required String authToken,
    required String signatureLookupHash,
    required String outcomePayloadCiphertext,
  }) async {
    historyWrites++;
    return {'status': 'stored'};
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async =>
      {'wallet_engine': 'receive_ready', 'publicAddress': _sender};

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    String? address,
  }) async {
    balanceCalls++;
    if (balanceThrows) throw StateError('Offline balance unavailable');
    if (balanceGate != null) return balanceGate!.future;
    return {..._balance(asset, address!), ...balanceOverrides};
  }

  @override
  Future<Map<String, dynamic>> listCryptoWalletTransactionsNetwork({
    required String network,
    required String asset,
    required String authToken,
    int limit = 20,
  }) async =>
      {'transactionsStatus': 'available', 'transactions': []};

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
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async =>
      {
        ...paxgDraftFixture(amount: amountEth!),
        'fromAddress': _sender,
        'status': 'draft_ready',
        'draftId': 'offline-paxg-draft',
        'nonce': '7',
        'gasLimit': '60000',
        'gasPrice': '1000000000',
      };

  @override
  Future<Map<String, dynamic>> postCryptoWalletPaxgSendFeeEstimateNetwork({
    required String fromAddress,
    required String destinationAddress,
    required String amountEth,
    required String authToken,
  }) async {
    quotedAmount = amountEth;
    return {
      'status': 'fee_estimate_ready',
      'asset': kPaxgAssetId,
      'network': _network,
      'chainId': 1,
      'amountBaseUnits': '${parseAssetBaseUnits(amountEth, 18)}',
      'gasLimit': '60000',
      'gasPriceWei': '1000000000',
      'authorizedMaxFeeBaseUnits': '60000000000000',
      ...feeOverrides,
    };
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    keyCalls++;
    return {
      'status': 'encrypted_secret_ready',
      'encryptedWalletSecret': 'offline-encrypted-key-placeholder'
    };
  }

  @override
  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
    String? draftId,
  }) async {
    broadcasts++;
    signed = signedTransaction as String;
    if (broadcastGate != null) return broadcastGate!.future;
    if (malformedBroadcast) return {'unexpected': true};
    return {
      'status': 'submitted',
      if (broadcastWalletEngine != null) 'wallet_engine': broadcastWalletEngine,
      'txHash': mismatchedBroadcastHash
          ? '0x${'1' * 64}'
          : computeLocalEthTxHash(signed!)
    };
  }
}

class _DelayedKey extends SecretKey {
  _DelayedKey() : super.constructor();
  final started = Completer<void>();
  final ready = Completer<SecretKeyData>();
  @override
  Future<SecretKeyData> extract() {
    if (!started.isCompleted) started.complete();
    return ready.future;
  }
}

Widget _app(Widget child) => MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate
      ],
      supportedLocales: const [Locale('en')],
      home: Scaffold(body: child),
    );

Future<void> _review(WidgetTester tester) async {
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_destination_input')), _recipient);
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_amount_input')), _amount);
  await tester
      .ensureVisible(find.byKey(const Key('eth_send_panel_review_btn')));
  await tester.tap(find.byKey(const Key('eth_send_panel_review_btn')));
  await tester.pumpAndSettle();
  expect(find.byKey(const Key('eth_send_panel_review_stage')), findsOneWidget);
}

Future<void> _confirm(WidgetTester tester) async {
  await tester
      .ensureVisible(find.byKey(const Key('eth_send_panel_confirm_btn')));
  await tester.tap(find.byKey(const Key('eth_send_panel_confirm_btn')));
  await tester.pumpAndSettle();
  await tester.enterText(
      find.byKey(const Key('eth_send_panel_pin_input')), '918273');
  await tester.tap(find.byKey(const Key('eth_send_panel_pin_confirm')));
  for (var i = 0; i < 8; i++) {
    await tester.pump();
  }
}

Future<void> _send(
  WidgetTester tester,
  _Client client, {
  Future<BigInt?> Function()? tokens,
  Future<BigInt?> Function()? eth,
  bool Function()? unlocked,
  LocalOutgoingTxStore? outgoing,
}) async {
  await tester.pumpWidget(_app(CryptoWalletEngineSendPanel(
    authToken: 'offline-session',
    client: client,
    fromAddress: _sender,
    asset: kPaxgAssetId,
    network: _network,
    registeredAsset: VaultAssetCatalog.fromJson(catalogFixture()).digitalGold,
    mainnetSendEnabled: true,
    decryptForVault: (_) async => _key,
    isVaultKeyAvailable: unlocked ?? () => true,
    verifyPin: (_) async => true,
    fetchAvailableBalance: () async => 2,
    fetchEthBalance: () async => 2,
    fetchAvailableBalanceWei: tokens,
    fetchEthBalanceWei: eth ?? () async => BigInt.parse('2000000000000000000'),
    outgoingTxStore: outgoing,
  )));
  await tester.pumpAndSettle();
  await _review(tester);
}

Future<CryptoWalletEngineSendPanel> _detailSend(
    WidgetTester tester, _Client client,
    {bool Function()? unlocked}) async {
  await tester.pumpWidget(_app(CryptoWalletEngineAssetDetailPage(
    asset: kPaxgAssetId,
    network: _network,
    authToken: 'offline-session',
    registeredAsset: VaultAssetCatalog.fromJson(catalogFixture()).digitalGold,
    apiClient: client,
    features: _features,
    encryptForVault: (_) async => 'unused-offline-ciphertext',
    isVaultKeyAvailable: unlocked ?? () => true,
    decryptForVault: (_) async => _key,
    verifyPin: (_) async => true,
    loadFromAddress: (_) async => _sender,
  )));
  await tester.pumpAndSettle();
  await tester.ensureVisible(
      find.byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')));
  await tester
      .tap(find.byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')));
  await tester.pumpAndSettle();
  return tester.widget<CryptoWalletEngineSendPanel>(
      find.byType(CryptoWalletEngineSendPanel));
}

void main() {
  setUp(() {
    ZkActiveMvk.clear();
    AssetLiveStore.instance.resetForTest();
  });
  tearDown(() {
    ZkActiveMvk.clear();
    AssetLiveStore.instance.resetForTest();
  });

  test('PAXG quote sends the exact amount on the closed mainnet token route',
      () async {
    final client = VaultAIClient(baseUrl: 'http://offline.invalid');
    await http.runWithClient(() async {
      await client.postCryptoWalletPaxgSendFeeEstimateNetwork(
          fromAddress: _sender,
          destinationAddress: _recipient,
          amountEth: _amount,
          authToken: 'offline-session');
    },
        () => MockClient((request) async {
              expect(request.url.path,
                  '/crypto/wallet/network/ethereum_mainnet/send/fee_estimate');
              expect(jsonDecode(request.body), {
                'fromAddress': _sender,
                'destinationAddress': _recipient,
                'asset': kPaxgAssetId,
                'amountEth': _amount
              });
              return http.Response('{}', 200);
            }));
  });

  test('legacy fee quote payload and public signature remain unchanged',
      () async {
    final client = VaultAIClient(baseUrl: 'http://offline.invalid');
    await http.runWithClient(() async {
      await client.postCryptoWalletSendFeeEstimateNetwork(
          network: _network,
          fromAddress: _sender,
          destinationAddress: _recipient,
          asset: 'USDC_ERC20',
          authToken: 'offline-session');
    },
        () => MockClient((request) async {
              expect(jsonDecode(request.body), {
                'fromAddress': _sender,
                'destinationAddress': _recipient,
                'asset': 'USDC_ERC20'
              });
              return http.Response('{}', 200);
            }));
  });

  for (final amount in ['.1', '1.']) {
    test('valid reviewed PAXG decimal $amount stays exact in the fee quote',
        () async {
      await http.runWithClient(() async {
        await VaultAIClient(baseUrl: 'http://offline.invalid')
            .postCryptoWalletPaxgSendFeeEstimateNetwork(
                fromAddress: _sender,
                destinationAddress: _recipient,
                amountEth: amount,
                authToken: 'offline-session');
      },
          () => MockClient((request) async {
                expect((jsonDecode(request.body) as Map)['amountEth'], amount);
                return http.Response('{}', 200);
              }));
    });
  }

  for (final amount in ['0', '-1', '1e-18', '0.0000000000000000001', ' 1']) {
    test('invalid PAXG quote amount $amount never dispatches', () async {
      var dispatches = 0;
      await http.runWithClient(() async {
        expect(
            () => VaultAIClient(baseUrl: 'http://offline.invalid')
                .postCryptoWalletPaxgSendFeeEstimateNetwork(
                    fromAddress: _sender,
                    destinationAddress: _recipient,
                    amountEth: amount,
                    authToken: 'offline-session'),
            throwsFormatException);
      },
          () => MockClient((_) async {
                dispatches++;
                return http.Response('{}', 200);
              }));
      expect(dispatches, 0);
    });
  }

  test('late PAXG quote cannot publish or classify a newer session', () async {
    var current = true;
    final response = Completer<http.Response>();
    final started = Completer<void>();
    final client = VaultAIClient(
        baseUrl: 'http://offline.invalid',
        walletResponseIsCurrent: () => current);
    await http.runWithClient(() async {
      final pending = client.postCryptoWalletPaxgSendFeeEstimateNetwork(
          fromAddress: _sender,
          destinationAddress: _recipient,
          amountEth: _amount,
          authToken: 'offline-session');
      await started.future;
      current = false;
      final rejected = expectLater(pending, throwsStateError);
      response.complete(
          http.Response('{"detail":{"code":"session_superseded"}}', 401));
      await rejected;
    },
        () => MockClient((_) {
              started.complete();
              return response.future;
            }));
  });

  test('PAXG history cannot dispatch after its wallet lease is revoked',
      () async {
    var writes = 0;
    final client = VaultAIClient(
        baseUrl: 'http://offline.invalid',
        walletResponseIsCurrent: () => false);
    await http.runWithClient(() async {
      await expectLater(
          client.postCryptoWalletPaxgOutgoingHistoryCiphertext(
              authToken: 'offline-session',
              signatureLookupHash: 'opaque-lookup',
              outcomePayloadCiphertext: 'opaque-history-ciphertext'),
          throwsStateError);
    },
        () => MockClient((_) async {
              writes++;
              return http.Response('{}', 200);
            }));
    expect(writes, 0);
  });

  test('PAXG history rejects a late response after its wallet lease changes',
      () async {
    var current = true;
    final client = VaultAIClient(
        baseUrl: 'http://offline.invalid',
        walletResponseIsCurrent: () => current);
    final started = Completer<void>();
    final response = Completer<http.Response>();
    await http.runWithClient(() async {
      final pending = client.postCryptoWalletPaxgOutgoingHistoryCiphertext(
          authToken: 'offline-session',
          signatureLookupHash: 'opaque-lookup',
          outcomePayloadCiphertext: 'opaque-history-ciphertext');
      await started.future;
      current = false;
      final rejected = expectLater(pending, throwsStateError);
      response.complete(http.Response('{}', 200));
      await rejected;
    },
        () => MockClient((_) {
              started.complete();
              return response.future;
            }));
  });

  for (final mutation in [
    {'amountBaseUnits': '1'},
    {'asset': 'USDC_ERC20'},
    {'network': 'ethereum_sepolia'},
    {'chainId': 11155111},
    {'gasLimit': null},
    {'gasLimit': 'invalid'},
    {'gasLimit': '0'},
    {'gasLimit': '-1'},
    {'gasPriceWei': null},
    {'gasPriceWei': 1000000000},
    {'gasPriceWei': '0'},
    {'gasPriceWei': '-1'},
    {'authorizedMaxFeeBaseUnits': null},
    {'authorizedMaxFeeBaseUnits': '0'},
    {'authorizedMaxFeeBaseUnits': '-1'},
    {'authorizedMaxFeeBaseUnits': '1'},
    {'estimatedFeeWei': '1'},
    {'maximumFeeWei': '0'},
  ]) {
    testWidgets('mismatched PAXG quote $mutation prevents key access',
        (tester) async {
      final client = _Client()..feeOverrides = mutation;
      await _send(tester, client,
          tokens: () async => BigInt.parse('2000000000000000000'));
      await _confirm(tester);
      expect(client.quotedAmount, _amount);
      expect(find.text(kMainnetSendFeeEstimateFailedError), findsOneWidget);
      expect(client.keyCalls, 0);
      expect(client.broadcasts, 0);
    });
  }

  testWidgets(
      'one base-unit token shortfall after Review blocks before decryption',
      (tester) async {
    final client = _Client();
    await _send(tester, client,
        tokens: () async => BigInt.parse('1000000000000000000'));
    await _confirm(tester);
    expect(
        find.text(kMainnetSendExactFeeInsufficientTokenError), findsOneWidget);
    expect(client.keyCalls, 0);
    expect(client.broadcasts, 0);
  });

  testWidgets('lower coherent PAXG quote cannot underfund original signed gas',
      (tester) async {
    final client = _Client();
    var eth = BigInt.parse('2000000000000000000');
    await _send(tester, client,
        tokens: () async => BigInt.parse('2000000000000000000'),
        eth: () async => eth);
    client.feeOverrides = {
      'gasPriceWei': '500000000',
      'authorizedMaxFeeBaseUnits': '30000000000000',
    };
    eth = BigInt.parse('30000000000000');
    await _confirm(tester);
    expect(
        find.text(kMainnetSendExactFeeInsufficientGasEthError), findsOneWidget);
    expect(client.keyCalls, 0);
    expect(client.broadcasts, 0);
  });

  testWidgets('missing PAXG integer hook fails closed before key access',
      (tester) async {
    final client = _Client();
    await _send(tester, client);
    await _confirm(tester);
    expect(find.text(kMainnetSendExactFeeUnverifiedError), findsOneWidget);
    expect(client.keyCalls, 0);
  });

  testWidgets('lock during exact token authorization does not fetch gas or key',
      (tester) async {
    final client = _Client();
    final balance = Completer<BigInt?>();
    var unlocked = true;
    var ethReads = 0;
    await _send(tester, client,
        unlocked: () => unlocked,
        tokens: () => balance.future,
        eth: () async {
          ethReads++;
          return BigInt.parse('2000000000000000000');
        });
    await _confirm(tester);
    final preLockEthReads = ethReads;
    unlocked = false;
    balance.complete(BigInt.parse('2000000000000000000'));
    await tester.pumpAndSettle();
    expect(ethReads, preLockEthReads);
    expect(client.keyCalls, 0);
    expect(client.broadcasts, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'PAXG detail integer hooks fetch new verified balances, not display cache',
      (tester) async {
    final client = _Client();
    final panel = await _detailSend(tester, client);
    final displayedReads = client.balanceCalls;
    client.balanceOverrides = {
      'availableAmount': '0.000000000000000001',
      'baseUnits': '1'
    };
    expect(await panel.fetchAvailableBalanceWei!(), BigInt.one);
    expect(
        await panel.fetchEthBalanceWei!(), BigInt.parse('2000000000000000000'));
    expect(client.balanceCalls, displayedReads + 2);
    client.balanceThrows = true;
    expect(await panel.fetchAvailableBalanceWei!(), isNull);
    expect(await panel.fetchEthBalanceWei!(), isNull);
  });

  for (final mutation in [
    {'chainId': 11155111},
    {'publicAddress': _recipient},
    {'weiAmount': '-1', 'spendableBalanceWei': '-1'}
  ]) {
    testWidgets('PAXG parent gas hook rejects mismatched response $mutation',
        (tester) async {
      final client = _Client();
      final panel = await _detailSend(tester, client);
      client.balanceOverrides = mutation;
      expect(await panel.fetchEthBalanceWei!(), isNull);
    });
  }

  testWidgets('PAXG detail drops late integer authorization after lock',
      (tester) async {
    final client = _Client();
    var unlocked = true;
    final panel = await _detailSend(tester, client, unlocked: () => unlocked);
    client.balanceGate = Completer<Map<String, dynamic>>();
    final pending = panel.fetchAvailableBalanceWei!();
    unlocked = false;
    client.balanceGate!.complete(_balance(kPaxgAssetId, _sender));
    expect(await pending, isNull);
    final before = client.balanceCalls;
    expect(await panel.fetchEthBalanceWei!(), isNull);
    expect(client.balanceCalls, before);
  });

  for (final mismatchedHash in [false, true]) {
    testWidgets(
        'opaque PAXG broadcast preserves uncertain local hash (hash mismatch=$mismatchedHash)',
        (tester) async {
      final client = _Client()
        ..malformedBroadcast = !mismatchedHash
        ..mismatchedBroadcastHash = mismatchedHash;
      final outgoing = LocalOutgoingTxStore();
      await _send(tester, client,
          outgoing: outgoing,
          tokens: () async => BigInt.parse('2000000000000000000'));
      await _confirm(tester);
      await tester.pumpAndSettle();
      final row =
          outgoing.rowsFor(networkId: _network, asset: kPaxgAssetId).single;
      expect(row.status, LocalOutgoingTxStatus.submissionUncertain);
      expect(row.txHash, computeLocalEthTxHash(client.signed!));
      expect(client.broadcasts, 1);
      expect(find.byKey(const Key('eth_send_panel_confirm_btn')), findsNothing);
      expect(find.text('Submitted'), findsNothing);
    });
  }

  testWidgets(
      'late dispatched PAXG response never changes revoked store or disposed UI',
      (tester) async {
    final client = _Client()..broadcastGate = Completer<Map<String, dynamic>>();
    final outgoing = LocalOutgoingTxStore();
    var unlocked = true;
    await _send(tester, client,
        outgoing: outgoing,
        unlocked: () => unlocked,
        tokens: () async => BigInt.parse('2000000000000000000'));
    await _confirm(tester);
    expect(client.broadcasts, 1);
    final rowBefore =
        outgoing.rowsFor(networkId: _network, asset: kPaxgAssetId).single;
    expect(rowBefore.status, LocalOutgoingTxStatus.submitting);
    unlocked = false;
    await tester.pumpWidget(_app(const SizedBox.shrink()));
    client.broadcastGate!.complete({
      'status': 'submitted',
      'txHash': computeLocalEthTxHash(client.signed!)
    });
    await tester.pumpAndSettle();
    expect(
        outgoing
            .rowsFor(networkId: _network, asset: kPaxgAssetId)
            .single
            .status,
        LocalOutgoingTxStatus.submitting);
    expect(tester.takeException(), isNull);
  });

  for (final engine in ['mainnet_send_paused', 'rate_limited']) {
    testWidgets(
        'contradictory PAXG $engine submission keeps the hash uncertain',
        (tester) async {
      final client = _Client()..broadcastWalletEngine = engine;
      final outgoing = LocalOutgoingTxStore();
      await _send(tester, client,
          outgoing: outgoing,
          tokens: () async => BigInt.parse('2000000000000000000'));
      await _confirm(tester);
      await tester.pumpAndSettle();
      final row =
          outgoing.rowsFor(networkId: _network, asset: kPaxgAssetId).single;
      expect(row.status, LocalOutgoingTxStatus.submissionUncertain);
      expect(row.txHash, computeLocalEthTxHash(client.signed!));
      expect(find.byKey(const Key('eth_send_panel_confirm_btn')), findsNothing);
      expect(client.broadcasts, 1);
    });
  }

  testWidgets(
      'PAXG encryption finishing after lock cannot start a history write',
      (tester) async {
    final client = _Client();
    final outgoing = LocalOutgoingTxStore();
    var unlocked = true;
    await _send(tester, client,
        outgoing: outgoing,
        unlocked: () => unlocked,
        tokens: () async => BigInt.parse('2000000000000000000'));
    // Review is already complete. Delay only the real history encryption's
    // subkey extraction after the fixture broadcast is verified.
    final delayed = _DelayedKey();
    ZkActiveMvk.set(
        mvk: delayed, vaultId: 'offline-vault', vaultHandle: 'offline-handle');
    await _confirm(tester);
    await delayed.started.future;
    expect(client.broadcasts, 1);
    final hash = outgoing
        .rowsFor(networkId: _network, asset: kPaxgAssetId)
        .single
        .txHash;
    unlocked = false;
    ZkActiveMvk.clear();
    delayed.ready.complete(SecretKeyData(List<int>.filled(32, 7)));
    for (var i = 0; i < 20; i++) {
      await tester.pump();
    }
    expect(client.historyWrites, 0);
    expect(
        outgoing
            .rowsFor(networkId: _network, asset: kPaxgAssetId)
            .single
            .txHash,
        hash);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'late PAXG broadcast cannot publish into a newer unlocked session',
      (tester) async {
    final client = _Client()..broadcastGate = Completer<Map<String, dynamic>>();
    final outgoing = LocalOutgoingTxStore();
    await _send(tester, client,
        outgoing: outgoing,
        tokens: () async => BigInt.parse('2000000000000000000'));
    await _confirm(tester);
    expect(client.broadcasts, 1);
    final old = tester.widget<CryptoWalletEngineSendPanel>(
        find.byType(CryptoWalletEngineSendPanel));
    await tester.pumpWidget(_app(CryptoWalletEngineSendPanel(
      authToken: 'newer-offline-session',
      client: old.client,
      fromAddress: old.fromAddress,
      asset: old.asset,
      network: old.network,
      registeredAsset: old.registeredAsset,
      mainnetSendEnabled: true,
      isVaultKeyAvailable: () => true,
      decryptForVault: old.decryptForVault,
      verifyPin: old.verifyPin,
      outgoingTxStore: outgoing,
      fetchAvailableBalance: old.fetchAvailableBalance,
      fetchEthBalance: old.fetchEthBalance,
      fetchAvailableBalanceWei: old.fetchAvailableBalanceWei,
      fetchEthBalanceWei: old.fetchEthBalanceWei,
    )));
    client.broadcastGate!.complete({
      'status': 'submitted',
      'txHash': computeLocalEthTxHash(client.signed!)
    });
    // The old signing spinner deliberately receives no late result. Bounded
    // pumps verify no mutation without waiting for that animation to settle.
    for (var i = 0; i < 8; i++) {
      await tester.pump();
    }
    expect(
        outgoing
            .rowsFor(networkId: _network, asset: kPaxgAssetId)
            .single
            .status,
        LocalOutgoingTxStatus.submitting);
    expect(find.text(kEthSendResultHeadingSubmitted), findsNothing);
    expect(client.historyWrites, 0);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(_app(const SizedBox.shrink()));
    await tester.pumpAndSettle();
  });
}
