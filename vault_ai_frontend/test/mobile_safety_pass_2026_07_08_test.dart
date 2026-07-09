
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/help_center_content.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart'
    as vcr;
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';


const List<Size> kMobileSizes = <Size>[
  Size(360, 800),
  Size(390, 844),
  Size(400, 900),
  Size(430, 932),
];


Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  required Size size,
  bool settle = true,
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Scaffold(body: child),
    ),
  );

  if (settle) {
    await tester.pumpAndSettle();
  } else {
    await tester.pump(const Duration(milliseconds: 100));
  }
}


Map<String, dynamic> _cardEnv(
  String cardType, {
  Map<String, dynamic>? data,
  Map<String, dynamic>? extra,
  String intent = vcr.kVcrIntentVaultOverview,
}) {
  return <String, dynamic>{
    'intent': intent,
    'card': <String, dynamic>{
      'schema':   'vault_chat_router_v1',
      'cardType': cardType,
      if (data != null) 'data': data,
      if (extra != null) ...extra,
    },
  };
}


VaultChatCardView _renderCard(Map<String, dynamic> env) {
  return VaultChatCardView(
    response: vcr.VaultChatResponse.fromJson(env),
  );
}


VaultLoginItem _item(String type, String service) =>
    VaultLoginItem(service: service, itemType: type);


void _forEachMobileSize(String description,
    Widget Function() build, {bool settle = true}) {
  for (final size in kMobileSizes) {
    testWidgets(
      '$description @ ${size.width.toInt()}x${size.height.toInt()}',
      (tester) async {
        await _pump(tester, build(), size: size, settle: settle);
        expect(tester.takeException(), isNull);
      },
    );
  }
}

void main() {


  group('Public Help Center (mode: public)', () {
    _forEachMobileSize('renders without exception',
        () => const HelpCenterPage(mode: HelpCenterMode.public));
  });

  group('Signed-in Help Center (mode: signedIn)', () {
    _forEachMobileSize('renders without exception',
        () => const HelpCenterPage(mode: HelpCenterMode.signedIn));
  });


  group('Logins & Secure Items page (empty vault)', () {
    _forEachMobileSize('renders empty state', () => LoginsPage(
          isLoading: false, hasLoaded: true,
          logins: const <VaultLoginItem>[],
          vaultLabel: 'MyVault',
          onRefresh: () async {},
        ));
  });

  group('Logins & Secure Items page (mixed items)', () {
    _forEachMobileSize('renders mixed items', () => LoginsPage(
          isLoading: false, hasLoaded: true,
          logins: [
            _item('login', 'Netflix'),
            _item('card', 'MyBankNote'),
            _item('crypto_wallet_address', 'MyLedgerETH'),
            _item('imei', 'PhoneIMEI'),
            _item('backup_code', 'BackupCode1'),
          ],
          vaultLabel: 'MyVault',
          onRefresh: () async {},
          onAskVault: (_) {},
          onView: (_, __) {},
          onEdit: (_, __) {},
          onDelete: (_, __) {},
        ));
  });

  group('Logins & Secure Items page (loading)', () {
    _forEachMobileSize('renders loading state', () => LoginsPage(
          isLoading: true, hasLoaded: false,
          logins: const <VaultLoginItem>[],
          vaultLabel: 'MyVault',
          onRefresh: () async {},
        ), settle: false);
  });

  group('Logins & Secure Items page (error)', () {
    _forEachMobileSize('renders error state', () => LoginsPage(
          isLoading: false, hasLoaded: true,
          error: 'Network timed out',
          logins: const <VaultLoginItem>[],
          vaultLabel: 'MyVault',
          onRefresh: () async {},
        ));
  });


  group('Vault overview chat card', () {
    _forEachMobileSize('renders empty counts',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardVaultOverview,
              intent: vcr.kVcrIntentVaultOverview,
              data: {
                'schema': 'vault_overview_data_v1',
                'available': true,
                'counts': {
                  'files': 0, 'documents': 0,
                  'logins': 0, 'secure_items': 0,
                  'id_documents': 0,
                  'generated_logins': 0,
                  'crypto_assets': 0, 'recent_activity': 0,
                },
                'storage': {
                  'used_bytes': 0, 'quota_bytes': 1073741824,
                  'percent_used': 0.0,
                },
              },
            )));
    _forEachMobileSize('renders large counts',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardVaultOverview,
              intent: vcr.kVcrIntentVaultOverview,
              data: {
                'schema': 'vault_overview_data_v1',
                'available': true,
                'counts': {
                  'files': 4321, 'documents': 987,
                  'logins': 654, 'secure_items': 210,
                  'id_documents': 12,
                  'generated_logins': 88,
                  'crypto_assets': 6, 'recent_activity': 200,
                },
                'storage': {
                  'used_bytes': 12345678900,
                  'quota_bytes': 21474836480,
                  'percent_used': 57.5,
                },
              },
            )));
  });

  group('Login chat card', () {
    _forEachMobileSize('renders empty list',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardLogin,
              intent: vcr.kVcrIntentLoginList,
              data: {
                'schema': 'vault_login_data_v1',
                'available': true,
                'view': 'list',
                'logins': [],
                'count': 0, 'limit_applied': 20,
              },
            )));
    _forEachMobileSize('renders many logins with long emails',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardLogin,
              intent: vcr.kVcrIntentLoginList,
              data: {
                'schema': 'vault_login_data_v1',
                'available': true,
                'view': 'list',
                'logins': [
                  for (int i = 0; i < 8; i++) {
                    'id': 'row-$i',
                    'title': 'Service $i with a rather long name',
                    'service': 'service$i',
                    'username_masked':
                        'v***_a_very_long_username_$i@example.com',
                    'has_username': true,
                    'domain': 'example.com',
                    'updated_at': '2026-01-01T00:00:00Z',
                    'generated': i % 2 == 0,
                  },
                ],
                'count': 8, 'limit_applied': 20,
              },
            )));
  });

  group('Secure item chat card', () {
    _forEachMobileSize('renders list', () => _renderCard(_cardEnv(
          vcr.kVcrCardSecureItem,
          intent: vcr.kVcrIntentSecureItemList,
          data: {
            'schema': 'vault_secure_item_data_v1',
            'available': true,
            'view': 'list',
            'items': [
              {
                'id': 'a', 'title': 'Very Long Secure Note Title '
                    'That Should Wrap On Mobile Nicely',
                'type': 'private_note',
                'snippet': 'A quite long snippet to test wrapping '
                    'behavior on mobile widths without overflow.',
                'updated_at': '2026-01-01T00:00:00Z',
              },
            ],
            'count': 1, 'limit_applied': 20,
          },
        )));
  });

  group('ID document chat card', () {
    _forEachMobileSize('renders masked ID list',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardIdDocument,
              intent: vcr.kVcrIntentIdDocumentList,
              data: {
                'schema': 'vault_id_document_data_v1',
                'available': true,
                'view': 'list',
                'documents': [
                  {
                    'id': 'a', 'type': 'passport',
                    'issuing_country': 'US',
                    'issuing_state': 'CA',
                    'expires_at': '2030-01-01',
                    'id_number_masked': '•••4567',
                  },
                ],
                'count': 1, 'limit_applied': 20,
              },
            )));
  });

  group('Billing status chat card', () {
    _forEachMobileSize('renders free plan',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardBillingStatus,
              intent: vcr.kVcrIntentBillingStatus,
              data: {
                'schema': 'vault_billing_data_v1',
                'available': true,
                'plan': 'free', 'status': 'no_account',
                'storage_tier': 'free',
                'has_active_subscription': false,
              },
            )));
    _forEachMobileSize('renders upgraded plan with long numbers',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardBillingStatus,
              intent: vcr.kVcrIntentBillingStatus,
              data: {
                'schema': 'vault_billing_data_v1',
                'available': true,
                'plan': 'upgraded', 'status': 'active',
                'storage_tier': 'upgraded',
                'block_count': 42,
                'purchased_bytes': 107374182400,
                'included_bytes': 5368709120,
                'cancel_at_period_end': false,
                'has_active_subscription': true,
              },
            )));
  });

  group('Storage usage chat card', () {
    _forEachMobileSize('renders usage bar',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardStorageUsage,
              intent: vcr.kVcrIntentStorageUsage,
              data: {
                'schema': 'vault_storage_data_v1',
                'available': true,
                'used_bytes': 12345678, 'quota_bytes': 21474836480,
                'percent_used': 5.7, 'file_count': 42,
                'document_count': 12, 'largest_categories': [],
              },
            )));
  });

  group('Vault activity chat card', () {
    _forEachMobileSize('renders events',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardVaultActivity,
              intent: vcr.kVcrIntentActivityRecent,
              data: {
                'schema': 'vault_activity_data_v1',
                'available': true,
                'events': [
                  {
                    'action': 'file_uploaded', 'category': 'file',
                    'title': 'A Very Long File Name That Should '
                        'Not Overflow The Card.pdf',
                    'timestamp': '2026-01-01T00:00:00Z',
                    'asset_type': 'application/pdf',
                  },
                  {
                    'action': 'item_saved', 'category': 'login',
                    'title': 'Very Long Service Name',
                    'timestamp': '2026-01-01T00:00:00Z',
                  },
                ],
                'count': 2, 'limit_applied': 20,
              },
            )));
  });

  group('Cross-vault search chat card', () {
    _forEachMobileSize('renders groups',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardCrossVaultSearch,
              intent: vcr.kVcrIntentCrossVaultSearch,
              extra: {'query': 'invoice'},
              data: {
                'schema': 'vault_search_data_v1',
                'available': true,
                'query': 'invoice',
                'groups': [
                  {
                    'category': 'files', 'count': 2,
                    'items': [
                      {
                        'id': 'f1',
                        'file_name': 'Invoice-Q4-2025.pdf',
                        'content_type': 'application/pdf',
                        'file_size': 12345,
                        'created_at': '2026-01-01T00:00:00Z',
                      },
                    ],
                  },
                ],
                'group_count': 1, 'limit_applied': 5,
              },
            )));
  });

  group('Refusal chat card', () {
    _forEachMobileSize('renders refusal',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardRefusal,
              intent: vcr.kVcrIntentRefusalSecretMaterial,
              extra: {
                'refusalReason': 'secret_material_request',
                'message':
                    'VaultAI never surfaces your seed, mnemonic, '
                    'private keys, encrypted wallet secret, auth '
                    'token, or API key through chat.',
              },
            )));
  });

  group('Confirmation required chat card', () {
    _forEachMobileSize('renders confirmation prompt',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardConfirmationRequired,
              intent: vcr.kVcrIntentLoginReveal,
              extra: {
                'action': 'reveal_login_password',
                'message':
                    'Revealing a password requires trusted '
                    'device, PIN unlock, and explicit '
                    'confirmation.',
                'requiresPinUnlock': true,
                'requiresTrustedDevice': true,
                'requiresLocalSigning': false,
                'requiresExplicitConfirmation': true,
              },
            )));
  });

  group('FAQ chat card', () {
    _forEachMobileSize('renders long FAQ answer + related chips',
        () => _renderCard(_cardEnv(
              vcr.kVcrCardFaq,
              intent: vcr.kVcrIntentFaq,
              extra: {
                'faqId': 'usdt-erc20-vs-trc20',
                'category': 'crypto',
                'categoryLabel': 'Crypto Vault',
                'question': 'Why does USDT have ERC20 and TRC20?',
                'answer': 'USDT exists on multiple networks. '
                    'VaultAI supports USDT ERC20 on Ethereum and '
                    'USDT TRC20 on TRON. You must pick the '
                    'correct network — addresses, fees, and '
                    'transfers are network-specific.',
                'relatedIds': [
                  'usdc-uses-eth-address', 'erc20-needs-eth-gas',
                ],
                'relatedQuestions': [
                  {'id': 'usdc-uses-eth-address',
                   'question':
                       'Why does USDC use my Ethereum address?'},
                  {'id': 'erc20-needs-eth-gas',
                   'question':
                       'Why do token transfers need ETH for gas?'},
                ],
                'relatedActions': ['open_crypto_vault'],
                'message': 'USDT exists on multiple networks.',
              },
            )));
  });

  group('Crypto delegated: balance card XMR (scanner-gated)', () {
    _forEachMobileSize(
      'renders XMR scanner-gated state',
      () => VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson({
          'intent': vcr.kVcrIntentCryptoDelegated,
          'card': {
            'schema': 'vault_chat_router_v1',
            'cardType': vcr.kVcrCardCryptoDelegated,
            'innerIntent': 'crypto_vault_balance',
            'innerCard': {
              'schema': 'crypto_vault_chat_control_v1',
              'cardType': 'crypto_vault_balance_card',
              'asset': 'XMR',
              'data': {
                'schema': 'crypto_balance',
                'available': true,
                'balanceStatus': 'scanner_gated',
                'reason': 'monero_scanner_disabled',
              },
            },
          },
        }),
      ),
    );
  });

  group('Crypto delegated: send draft (canBroadcast=false)', () {
    _forEachMobileSize(
      'renders send draft with clear warning banner',
      () => VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson({
          'intent': vcr.kVcrIntentCryptoDelegated,
          'card': {
            'schema': 'vault_chat_router_v1',
            'cardType': vcr.kVcrCardCryptoDelegated,
            'innerIntent': 'crypto_vault_send_draft',
            'innerCard': {
              'schema': 'crypto_vault_chat_control_v1',
              'cardType': 'crypto_vault_send_draft_card',
              'asset': 'ETH',
              'amount': '0.05',
              'canBroadcast': false,
              'data': {
                'schema': 'crypto_send_draft',
                'available': true,
              },
            },
          },
        }),
      ),
    );
  });
}
