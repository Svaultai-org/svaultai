

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n/app_localizations.dart';


const String kCryptoVaultStrongWarning =
    "This is extremely sensitive. Anyone with this phrase or "
    "key can control the wallet. Store it only if you "
    "understand the risk.";


const String kCryptoVaultLiteHeading  = 'Crypto Vault';
const String kCryptoVaultLiteStatus   = 'Active';
const String kCryptoVaultLiteSubtitle =
    'Store wallet addresses, seed phrases, private keys, '
    'recovery phrases, crypto notes, and receive QR codes '
    'securely.';


const String kCryptoVaultLiteSecurityNote =
    'Send features are not enabled yet. Receive QR only shows '
    'saved addresses.';


const String kCryptoPromptAddWallet =
    'Save a new crypto wallet address';
const String kCryptoPromptAddSeed =
    'Save a new crypto seed phrase or private key';
const String kCryptoPromptAddCryptoNote =
    'Save a new crypto note';
const String kCryptoPromptAddTransactionNote =
    'Save a new transaction note';


const String kCryptoLiteEmptyTitle =
    'Start by saving your first crypto record';
const String kCryptoLiteEmptyBody  =
    'Add a wallet address, seed phrase, private key, crypto '
    'note, or transaction note. Everything is encrypted inside '
    'your vault.';
const String kCryptoLiteEmptyPrimaryLabel   = 'Add wallet address';
const String kCryptoLiteEmptySecondarySeed  =
    'Add seed phrase / private key';
const String kCryptoLiteEmptySecondaryNote  = 'Add crypto note';


class CryptoFeatureTileData {
  final String key;
  final String title;
  final String body;
  final IconData icon;
  const CryptoFeatureTileData({
    required this.key,
    required this.title,
    required this.body,
    required this.icon,
  });
}

const CryptoFeatureTileData kCryptoTileWallets = CryptoFeatureTileData(
  key:   'crypto_lite_tile_wallets',
  title: 'Wallet addresses',
  body:  'Save addresses and show receive QR codes.',
  icon:  Icons.account_balance_wallet_outlined,
);
const CryptoFeatureTileData kCryptoTileSeedKeys = CryptoFeatureTileData(
  key:   'crypto_lite_tile_seed_keys',
  title: 'Seed & private keys',
  body:  'Encrypted storage for sensitive recovery data.',
  icon:  Icons.password_outlined,
);
const CryptoFeatureTileData kCryptoTileNotes = CryptoFeatureTileData(
  key:   'crypto_lite_tile_notes',
  title: 'Crypto notes',
  body:  'Keep exchange, hardware wallet, and transaction notes.',
  icon:  Icons.notes_outlined,
);
const CryptoFeatureTileData kCryptoTileReceiveQR = CryptoFeatureTileData(
  key:   'crypto_lite_tile_receive_qr',
  title: 'Receive QR',
  body:  'Show QR codes for saved wallet addresses.',
  icon:  Icons.qr_code_2_outlined,
);

const List<CryptoFeatureTileData> kCryptoFeatureTiles =
    <CryptoFeatureTileData>[
  kCryptoTileWallets,
  kCryptoTileSeedKeys,
  kCryptoTileNotes,
  kCryptoTileReceiveQR,
];


class CryptoCounterSpec {
  final String key;
  final String label;
  final IconData icon;
  
  final bool Function(String itemType) matches;
  const CryptoCounterSpec({
    required this.key,
    required this.label,
    required this.icon,
    required this.matches,
  });
}

bool _matchWallet(String t) => t == 'crypto_wallet_address';
bool _matchSensitiveKey(String t) =>
    t == 'crypto_seed_phrase'
    || t == 'crypto_private_key'
    || t == 'crypto_recovery_phrase';
bool _matchNotes(String t) =>
    t == 'crypto_note'
    || t == 'crypto_exchange_note'
    || t == 'crypto_hardware_wallet_note';
bool _matchTransactions(String t) => t == 'crypto_transaction_note';

const CryptoCounterSpec kCryptoCounterWallets = CryptoCounterSpec(
  key:   'crypto_lite_counter_wallets',
  label: 'Wallets',
  icon:  Icons.account_balance_wallet_outlined,
  matches: _matchWallet,
);
const CryptoCounterSpec kCryptoCounterSensitiveKeys = CryptoCounterSpec(
  key:   'crypto_lite_counter_sensitive_keys',
  label: 'Sensitive keys',
  icon:  Icons.password_outlined,
  matches: _matchSensitiveKey,
);
const CryptoCounterSpec kCryptoCounterNotes = CryptoCounterSpec(
  key:   'crypto_lite_counter_notes',
  label: 'Notes',
  icon:  Icons.notes_outlined,
  matches: _matchNotes,
);
const CryptoCounterSpec kCryptoCounterTransactions = CryptoCounterSpec(
  key:   'crypto_lite_counter_transactions',
  label: 'Transactions',
  icon:  Icons.receipt_long_outlined,
  matches: _matchTransactions,
);

const List<CryptoCounterSpec> kCryptoCounters = <CryptoCounterSpec>[
  kCryptoCounterWallets,
  kCryptoCounterSensitiveKeys,
  kCryptoCounterNotes,
  kCryptoCounterTransactions,
];


class CryptoChatSuggestion {
  final String key;
  final String label;
  final String prompt;
  const CryptoChatSuggestion({
    required this.key,
    required this.label,
    required this.prompt,
  });
}

const List<CryptoChatSuggestion> kCryptoChatSuggestions =
    <CryptoChatSuggestion>[
  CryptoChatSuggestion(
    key:    'crypto_lite_suggest_save_btc_wallet',
    label:  '"save my bitcoin wallet address…"',
    prompt: 'save my bitcoin wallet address',
  ),
  CryptoChatSuggestion(
    key:    'crypto_lite_suggest_show_btc_qr',
    label:  '"show my BTC receive QR"',
    prompt: 'show my BTC receive QR',
  ),
  CryptoChatSuggestion(
    key:    'crypto_lite_suggest_save_recovery',
    label:  '"save my ledger recovery phrase…"',
    prompt: 'save my ledger recovery phrase',
  ),
  CryptoChatSuggestion(
    key:    'crypto_lite_suggest_show_records',
    label:  '"show my crypto records"',
    prompt: 'show my crypto records',
  ),
];


const String kCryptoLiteSearchHint =
    'Search crypto records';


const String kCryptoBalanceUnavailable        = 'Balance unavailable';
const String kCryptoBalanceUnavailableMonero  =
    'Balance unavailable for Monero privacy addresses.';
const String kCryptoBalanceLookupNotConnected =
    'Balance lookup not connected';
const String kCryptoNoWalletSaved             = 'No wallet saved';
const String kCryptoAddWalletAction           = 'Add wallet';
const String kCryptoViewWalletsAction         = 'View wallets';


const String kCryptoAddWalletDialogTitle  = 'Add crypto wallet';
const String kCryptoAddWalletDialogSaveLabel    = 'Save wallet';
const String kCryptoAddWalletDialogCancelLabel  = 'Cancel';
const String kCryptoAddWalletAssetFieldLabel    = 'Asset / network';
const String kCryptoAddWalletLabelFieldLabel    = 'Wallet label';
const String kCryptoAddWalletAddressFieldLabel  = 'Public wallet address';
const String kCryptoAddWalletNoteFieldLabel     = 'Optional note';
const String kCryptoAddWalletAddressFormatHint  =
    'Format does not match the selected network. You can still '
    'save manually if you are sure the address is correct.';
const String kCryptoAddWalletValidationErrorAsset   =
    'Select an asset or network.';
const String kCryptoAddWalletValidationErrorLabel   =
    'Select a wallet label.';
const String kCryptoAddWalletValidationErrorAddress =
    'Enter the public wallet address.';
const String kCryptoAddWalletSecurityNote =
    'The public address is stored encrypted. Never paste a seed '
    'phrase or private key here.';


class CryptoAsset {
  
  final String id;
  
  final String ticker;
  
  final String displayName;
  
  
  final String networkLabel;
  
  final IconData icon;
  
  final int accentArgb;
  
  
  final bool balanceLookupSupported;
  
  
  final bool isPrivacyChain;
  
  
  final String addressFormatRegex;

  const CryptoAsset({
    required this.id,
    required this.ticker,
    required this.displayName,
    required this.networkLabel,
    required this.icon,
    required this.accentArgb,
    required this.addressFormatRegex,
    this.balanceLookupSupported = false,
    this.isPrivacyChain         = false,
  });
}

const CryptoAsset kCryptoAssetBTC = CryptoAsset(
  id:                  'btc',
  ticker:              'BTC',
  displayName:         'Bitcoin',
  networkLabel:        'Bitcoin',
  icon:                Icons.currency_bitcoin,
  accentArgb:          0xFFF7931A,
  addressFormatRegex:
      r'^(bc1[a-z0-9]{6,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$',
);
const CryptoAsset kCryptoAssetETH = CryptoAsset(
  id:                  'eth',
  ticker:              'ETH',
  displayName:         'Ethereum',
  networkLabel:        'Ethereum',
  icon:                Icons.diamond_outlined,
  accentArgb:          0xFF627EEA,
  addressFormatRegex:  r'^0x[a-fA-F0-9]{40}$',
);
const CryptoAsset kCryptoAssetUsdtTrc20 = CryptoAsset(
  id:                  'usdt_trc20',
  ticker:              'USDT',
  displayName:         'USDT TRC20',
  networkLabel:        'Tron TRC20',
  icon:                Icons.attach_money,
  accentArgb:          0xFF26A17B,
  addressFormatRegex:  r'^T[1-9A-HJ-NP-Za-km-z]{33}$',
);
const CryptoAsset kCryptoAssetUsdtErc20 = CryptoAsset(
  id:                  'usdt_erc20',
  ticker:              'USDT',
  displayName:         'USDT ERC20',
  networkLabel:        'Ethereum ERC20',
  icon:                Icons.attach_money,
  accentArgb:          0xFF26A17B,
  addressFormatRegex:  r'^0x[a-fA-F0-9]{40}$',
);
const CryptoAsset kCryptoAssetUsdcErc20 = CryptoAsset(
  id:                  'usdc_erc20',
  ticker:              'USDC',
  displayName:         'USDC ERC20',
  networkLabel:        'Ethereum ERC20',
  icon:                Icons.attach_money,
  accentArgb:          0xFF2775CA,
  addressFormatRegex:  r'^0x[a-fA-F0-9]{40}$',
);
const CryptoAsset kCryptoAssetSOL = CryptoAsset(
  id:                  'sol',
  ticker:              'SOL',
  displayName:         'Solana',
  networkLabel:        'Solana',
  icon:                Icons.wb_sunny_outlined,
  accentArgb:          0xFF9945FF,
  addressFormatRegex:  r'^[1-9A-HJ-NP-Za-km-z]{32,44}$',
);
const CryptoAsset kCryptoAssetBNB = CryptoAsset(
  id:                  'bnb',
  ticker:              'BNB',
  displayName:         'BNB Smart Chain',
  networkLabel:        'BNB Smart Chain',
  icon:                Icons.local_fire_department_outlined,
  accentArgb:          0xFFF3BA2F,
  addressFormatRegex:  r'^0x[a-fA-F0-9]{40}$',
);
const CryptoAsset kCryptoAssetXMR = CryptoAsset(
  id:                  'xmr',
  ticker:              'XMR',
  displayName:         'Monero',
  networkLabel:        'Monero',
  icon:                Icons.visibility_off_outlined,
  accentArgb:          0xFFFF6600,
  addressFormatRegex:  r'^[48][1-9A-HJ-NP-Za-km-z]{94}$',
  isPrivacyChain:      true,
);

const List<CryptoAsset> kCryptoAssets = <CryptoAsset>[
  kCryptoAssetBTC,
  kCryptoAssetETH,
  kCryptoAssetUsdtTrc20,
  kCryptoAssetUsdtErc20,
  kCryptoAssetUsdcErc20,
  kCryptoAssetSOL,
  kCryptoAssetBNB,
  kCryptoAssetXMR,
];


CryptoAsset? cryptoAssetById(String id) {
  for (final a in kCryptoAssets) {
    if (a.id == id) return a;
  }
  return null;
}


CryptoAsset? cryptoAssetFromNetwork(String? network) {
  if (network == null) return null;
  final n = network.trim().toLowerCase();
  if (n.isEmpty) return null;
  for (final a in kCryptoAssets) {
    if (n == a.id) return a;
    if (n == a.ticker.toLowerCase()) return a;
    if (n == a.displayName.toLowerCase()) return a;
    if (n == a.networkLabel.toLowerCase()) return a;
  }
  
  if (n.contains('bitcoin')) return kCryptoAssetBTC;
  if (n.contains('ethereum') && !n.contains('erc20')) {
    return kCryptoAssetETH;
  }
  if (n.contains('usdt') && n.contains('trc')) {
    return kCryptoAssetUsdtTrc20;
  }
  if (n.contains('usdt') && n.contains('erc')) {
    return kCryptoAssetUsdtErc20;
  }
  if (n.contains('usdc')) return kCryptoAssetUsdcErc20;
  if (n.contains('solana')) return kCryptoAssetSOL;
  if (n.contains('bnb')
      || n.contains('binance smart')
      || n == 'bsc'
      || n.contains(' bsc ')
      || n.endsWith(' bsc')
      || n.startsWith('bsc ')) {
    return kCryptoAssetBNB;
  }
  if (n.contains('monero')) return kCryptoAssetXMR;
  return null;
}


int cryptoWalletCountForAsset(
  List<Map<String, dynamic>> records,
  CryptoAsset asset,
) {
  int n = 0;
  for (final r in records) {
    final type = (r['type'] ?? r['item_type'] ?? '').toString();
    if (type != 'crypto_wallet_address') continue;
    final preview = r['preview'];
    if (preview is! Map) continue;
    final network = preview['network'];
    final hit = cryptoAssetFromNetwork(
      network is String ? network : null,
    );
    if (hit?.id == asset.id) n++;
  }
  return n;
}


int cryptoTotalWalletCount(List<Map<String, dynamic>> records) {
  int n = 0;
  for (final r in records) {
    final type = (r['type'] ?? r['item_type'] ?? '').toString();
    if (type == 'crypto_wallet_address') n++;
  }
  return n;
}


bool cryptoAddressMatchesAsset(CryptoAsset asset, String address) {
  final a = address.trim();
  if (a.isEmpty) return false;
  final re = RegExp(asset.addressFormatRegex);
  return re.hasMatch(a);
}


class CryptoWalletLabel {
  final String id;
  final String displayName;
  final IconData icon;
  
  
  final bool isHardware;
  
  
  final bool isExchange;
  
  final bool isCustom;
  const CryptoWalletLabel({
    required this.id,
    required this.displayName,
    required this.icon,
    this.isHardware = false,
    this.isExchange = false,
    this.isCustom   = false,
  });
}

const CryptoWalletLabel kWalletLabelMetaMask = CryptoWalletLabel(
  id:          'metamask',
  displayName: 'MetaMask',
  icon:        Icons.account_balance_wallet_outlined,
);
const CryptoWalletLabel kWalletLabelTrustWallet = CryptoWalletLabel(
  id:          'trust_wallet',
  displayName: 'Trust Wallet',
  icon:        Icons.shield_outlined,
);
const CryptoWalletLabel kWalletLabelLedger = CryptoWalletLabel(
  id:          'ledger',
  displayName: 'Ledger',
  icon:        Icons.usb_outlined,
  isHardware:  true,
);
const CryptoWalletLabel kWalletLabelTrezor = CryptoWalletLabel(
  id:          'trezor',
  displayName: 'Trezor',
  icon:        Icons.usb_outlined,
  isHardware:  true,
);
const CryptoWalletLabel kWalletLabelBinance = CryptoWalletLabel(
  id:          'binance',
  displayName: 'Binance',
  icon:        Icons.account_balance_outlined,
  isExchange:  true,
);
const CryptoWalletLabel kWalletLabelCoinbase = CryptoWalletLabel(
  id:          'coinbase',
  displayName: 'Coinbase',
  icon:        Icons.account_balance_outlined,
  isExchange:  true,
);
const CryptoWalletLabel kWalletLabelCustom = CryptoWalletLabel(
  id:          'custom',
  displayName: 'Custom',
  icon:        Icons.edit_outlined,
  isCustom:    true,
);

const List<CryptoWalletLabel> kCryptoWalletLabels =
    <CryptoWalletLabel>[
  kWalletLabelMetaMask,
  kWalletLabelTrustWallet,
  kWalletLabelLedger,
  kWalletLabelTrezor,
  kWalletLabelBinance,
  kWalletLabelCoinbase,
  kWalletLabelCustom,
];

CryptoWalletLabel? cryptoWalletLabelById(String id) {
  for (final l in kCryptoWalletLabels) {
    if (l.id == id) return l;
  }
  return null;
}


class CryptoFilterChip {
  final String id;
  final String label;
  final IconData icon;
  const CryptoFilterChip({
    required this.id,
    required this.label,
    required this.icon,
  });
}

const CryptoFilterChip kCryptoChipAll = CryptoFilterChip(
  id:    'all',
  label: 'All',
  icon:  Icons.inventory_2_outlined,
);
const CryptoFilterChip kCryptoChipWallets = CryptoFilterChip(
  id:    'wallets',
  label: 'Wallets',
  icon:  Icons.account_balance_wallet_outlined,
);
const CryptoFilterChip kCryptoChipSeedKeys = CryptoFilterChip(
  id:    'seed_keys',
  label: 'Seed/Keys',
  icon:  Icons.password_outlined,
);
const CryptoFilterChip kCryptoChipNotes = CryptoFilterChip(
  id:    'notes',
  label: 'Notes',
  icon:  Icons.notes_outlined,
);
const CryptoFilterChip kCryptoChipTransactions = CryptoFilterChip(
  id:    'transactions',
  label: 'Transactions',
  icon:  Icons.receipt_long_outlined,
);
const CryptoFilterChip kCryptoChipExchangeHardware = CryptoFilterChip(
  id:    'exchange_hardware',
  label: 'Exchange/Hardware',
  icon:  Icons.usb_outlined,
);

const List<CryptoFilterChip> kCryptoFilterChips =
    <CryptoFilterChip>[
  kCryptoChipAll,
  kCryptoChipWallets,
  kCryptoChipSeedKeys,
  kCryptoChipNotes,
  kCryptoChipTransactions,
  kCryptoChipExchangeHardware,
];


String cryptoChipIdForType(String itemType) {
  switch (itemType) {
    case 'crypto_wallet_address':
      return kCryptoChipWallets.id;
    case 'crypto_seed_phrase':
    case 'crypto_private_key':
    case 'crypto_recovery_phrase':
      return kCryptoChipSeedKeys.id;
    case 'crypto_note':
      return kCryptoChipNotes.id;
    case 'crypto_transaction_note':
      return kCryptoChipTransactions.id;
    case 'crypto_exchange_note':
    case 'crypto_hardware_wallet_note':
      return kCryptoChipExchangeHardware.id;
    default:
      return kCryptoChipAll.id;
  }
}

bool cryptoRecordMatchesChip(
  Map<String, dynamic> record,
  CryptoFilterChip chip,
) {
  if (chip.id == kCryptoChipAll.id) return true;
  final type = (record['type'] ?? record['item_type'] ?? '').toString();
  return cryptoChipIdForType(type) == chip.id;
}

bool cryptoRecordMatchesQuery(
  Map<String, dynamic> record,
  String query,
) {
  final q = query.trim().toLowerCase();
  if (q.isEmpty) return true;
  final title    = (record['title'] ?? '').toString().toLowerCase();
  final catLabel = (record['category_label'] ?? '').toString().toLowerCase();
  String network = '';
  final preview = record['preview'];
  if (preview is Map && preview['network'] is String) {
    network = (preview['network'] as String).toLowerCase();
  }
  return title.contains(q)
      || catLabel.contains(q)
      || network.contains(q);
}


class CryptoVaultLitePage extends StatefulWidget {
  const CryptoVaultLitePage({
    super.key,
    this.savedRecords = const <Map<String, dynamic>>[],
    this.onSendChatPrompt,
    this.onView,
    this.onEdit,
    this.onDelete,
    this.onCopyValue,
    this.onShowQR,
    this.onDirectSaveWalletProfile,
    this.onDirectSaveSensitiveBackup,
    this.onLoadCryptoRecordDetail,
    this.onUpdateCryptoWalletProfile,
    this.onUpdateCryptoBackupMetadata,
    this.onDeleteCryptoRecord,
    this.onRevealCryptoSensitiveBackup,
    this.onDirectSaveCryptoNote,
  });

  
  final List<Map<String, dynamic>> savedRecords;

  
  final void Function(String prompt)? onSendChatPrompt;

  
  final void Function(Map<String, dynamic> record)? onView;

  
  final void Function(Map<String, dynamic> record)? onEdit;

  
  final void Function(Map<String, dynamic> record)? onDelete;

  
  final void Function(Map<String, dynamic> record)? onCopyValue;

  
  final void Function(Map<String, dynamic> record)? onShowQR;

  
  final Future<void> Function(CryptoAddWalletDraft draft)?
      onDirectSaveWalletProfile;

  
  final Future<void> Function(CryptoAddSensitiveBackupDraft draft)?
      onDirectSaveSensitiveBackup;

  
  final Future<Map<String, dynamic>> Function(
    Map<String, dynamic> record,
  )? onLoadCryptoRecordDetail;

  
  final Future<void> Function(
    Map<String, dynamic> record,
    CryptoAddWalletDraft edits,
  )? onUpdateCryptoWalletProfile;

  
  final Future<void> Function(
    Map<String, dynamic> record,
    CryptoBackupMetadataEdit edits,
  )? onUpdateCryptoBackupMetadata;

  
  final Future<void> Function(Map<String, dynamic> record)?
      onDeleteCryptoRecord;

  
  final Future<Map<String, dynamic>> Function(
    Map<String, dynamic> record,
    String pin,
  )? onRevealCryptoSensitiveBackup;

  
  final Future<void> Function(CryptoAddNoteDraft draft)?
      onDirectSaveCryptoNote;

  @override
  State<CryptoVaultLitePage> createState() => _CryptoVaultLitePageState();
}

class _CryptoVaultLitePageState extends State<CryptoVaultLitePage> {
  late final TextEditingController _searchCtrl;
  String _query = '';
  CryptoFilterChip _activeChip = kCryptoChipAll;

  @override
  void initState() {
    super.initState();
    _searchCtrl = TextEditingController(text: '');
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  void _sendPrompt(String prompt) {
    if (widget.onSendChatPrompt != null) widget.onSendChatPrompt!(prompt);
  }

  void _setQuery(String value) {
    setState(() => _query = value);
  }

  void _setChip(CryptoFilterChip chip) {
    setState(() => _activeChip = chip);
  }

  List<Map<String, dynamic>> get _visibleRecords {
    return widget.savedRecords
        .where((r) =>
            cryptoRecordMatchesChip(r, _activeChip)
            && cryptoRecordMatchesQuery(r, _query))
        .toList(growable: false);
  }

  Future<void> _addSeedOrPrivateKey(BuildContext context) async {
    final confirmed = await showCryptoVaultStrongWarningDialog(
      context,
      title: 'Saving a seed phrase or private key',
      bodyExtra: widget.onDirectSaveSensitiveBackup != null
          ? 'Continuing opens the sensitive-backup form. The '
            'backup is encrypted before it leaves the dialog.'
          : 'Continuing will start a draft you can confirm with '
            '"save it now". Cancel if you are not sure.',
    );
    if (confirmed != true) return;
    
    
    if (widget.onDirectSaveSensitiveBackup != null) {
      if (!context.mounted) return;
      await showAddSensitiveBackupDialog(
        context,
        onSave: widget.onDirectSaveSensitiveBackup!,
      );
      return;
    }
    _sendPrompt(kCryptoPromptAddSeed);
  }

  
  Future<void> _addCryptoWallet(
    BuildContext context, {
    CryptoAsset? preselectedAsset,
  }) async {
    
    
    if (widget.onDirectSaveWalletProfile != null) {
      final saved = await showAddCryptoWalletDialog(
        context,
        preselectedAsset: preselectedAsset,
        onSave: widget.onDirectSaveWalletProfile,
      );
      if (saved == null) return;
      if (preselectedAsset != null) {
        setState(() {
          _activeChip = kCryptoChipWallets;
          _query = preselectedAsset.ticker;
          _searchCtrl.text = preselectedAsset.ticker;
        });
      }
      return;
    }
    
    final draft = await showAddCryptoWalletDialog(
      context,
      preselectedAsset: preselectedAsset,
    );
    if (draft == null) return;
    _sendPrompt(draft.toChatPrompt());
    if (preselectedAsset != null) {
      setState(() {
        _activeChip = kCryptoChipWallets;
        _query = preselectedAsset.ticker;
        _searchCtrl.text = preselectedAsset.ticker;
      });
    }
  }

  void _viewWalletsForAsset(CryptoAsset asset) {
    setState(() {
      _activeChip = kCryptoChipWallets;
      _query = asset.ticker;
      _searchCtrl.text = asset.ticker;
    });
  }

  
  Future<void> _addCryptoNote(
    BuildContext context, {
    required String noteType,
  }) async {
    if (widget.onDirectSaveCryptoNote != null) {
      await showAddCryptoNoteDialog(
        context,
        noteType: noteType,
        onSave: widget.onDirectSaveCryptoNote!,
      );
      return;
    }
    
    _sendPrompt(noteType == 'transaction_note'
        ? kCryptoPromptAddTransactionNote
        : kCryptoPromptAddCryptoNote);
  }

  
  Future<void> _onViewCryptoRecord(
    BuildContext context,
    Map<String, dynamic> record,
  ) async {
    if (widget.onLoadCryptoRecordDetail == null) {
      if (widget.onView != null) widget.onView!(record);
      return;
    }
    final type = (record['type'] ?? record['item_type'] ?? '').toString();
    final isWallet = type == 'crypto_wallet_address';
    final isBackup = type == 'crypto_seed_phrase'
        || type == 'crypto_private_key'
        || type == 'crypto_recovery_phrase';
    if (!isWallet && !isBackup) {
      
      
      if (widget.onView != null) widget.onView!(record);
      return;
    }
    Map<String, dynamic>? detail;
    try {
      detail = await widget.onLoadCryptoRecordDetail!(record);
    } catch (_) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(
          AppLocalizations.of(context).cryptoLiteCouldNotLoadRecord,
        ),
      ));
      return;
    }
    if (!context.mounted) return;
    if (isWallet) {
      await showCryptoWalletDetailDialog(
        context,
        record: record,
        detail: detail,
        onCopyAddress: widget.onCopyValue,
        onShowQR: widget.onShowQR,
        onUpdate: widget.onUpdateCryptoWalletProfile,
        onDelete: widget.onDeleteCryptoRecord,
      );
    } else {
      await showCryptoSensitiveBackupDetailDialog(
        context,
        record: record,
        detail: detail,
        onUpdateMetadata: widget.onUpdateCryptoBackupMetadata,
        onDelete: widget.onDeleteCryptoRecord,
        onReveal: widget.onRevealCryptoSensitiveBackup,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final isWide = MediaQuery.of(context).size.width >= 720;
    final visible = _visibleRecords;
    final hasRecords = widget.savedRecords.isNotEmpty;
    return SingleChildScrollView(
      key: const Key('crypto_vault_lite_page'),
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              
              
              _CryptoLiteHero(
                totalWallets: cryptoTotalWalletCount(widget.savedRecords),
              ),
              const SizedBox(height: 16),
              
              
              Wrap(
                key: const Key('crypto_lite_actions'),
                spacing: 12,
                runSpacing: 12,
                children: [
                  _ActionButton(
                    keyName: 'crypto_lite_add_wallet_button',
                    icon: Icons.account_balance_wallet_outlined,
                    label: 'Add wallet address',
                    onPressed: () => _addCryptoWallet(context),
                  ),
                  _ActionButton(
                    keyName: 'crypto_lite_add_seed_button',
                    icon: Icons.warning_amber_outlined,
                    label: 'Add seed phrase / private key',
                    onPressed: () => _addSeedOrPrivateKey(context),
                  ),
                  _ActionButton(
                    keyName: 'crypto_lite_add_crypto_note_button',
                    icon: Icons.notes_outlined,
                    label: 'Add crypto note',
                    onPressed: () => _addCryptoNote(
                      context,
                      noteType: 'general',
                    ),
                  ),
                  _ActionButton(
                    keyName: 'crypto_lite_add_transaction_note_button',
                    icon: Icons.receipt_long_outlined,
                    label: 'Add transaction note',
                    onPressed: () => _addCryptoNote(
                      context,
                      noteType: 'transaction_note',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              
              
              _CryptoAssetDashboard(
                records: widget.savedRecords,
                onAddWalletForAsset: (asset) =>
                    _addCryptoWallet(context, preselectedAsset: asset),
                onViewWalletsForAsset: _viewWalletsForAsset,
              ),
              const SizedBox(height: 20),
              
              
              _CryptoCounterRow(records: widget.savedRecords),
              const SizedBox(height: 16),
              
              
              _CryptoFeatureTiles(),
              
              if (hasRecords) ...[
                const SizedBox(height: 20),
                _SearchBar(
                  controller: _searchCtrl,
                  onChanged: _setQuery,
                ),
                const SizedBox(height: 12),
                _CryptoChipStrip(
                  active: _activeChip,
                  onSelect: _setChip,
                ),
                const SizedBox(height: 20),
                
                Container(
                  key: const Key('crypto_lite_records_section'),
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    color: const Color(0xFF262626),
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: Colors.white10),
                  ),
                  child: visible.isEmpty
                      ? _CryptoFilterEmptyState(
                          query: _query,
                          chip: _activeChip,
                        )
                      : Column(
                          key: const Key('crypto_lite_records_list'),
                          children: visible
                              .map((r) => _CryptoRecordCard(
                                    record: r,
                                    onView: widget.onLoadCryptoRecordDetail != null
                                        ? (rec) {
                                            _onViewCryptoRecord(
                                                context, rec);
                                          }
                                        : widget.onView,
                                    onEdit: widget.onEdit,
                                    onDelete: widget.onDelete,
                                    onCopyValue: widget.onCopyValue,
                                    onShowQR: widget.onShowQR,
                                  ))
                              .toList(growable: false),
                        ),
                ),
              ] else ...[
                
                
                const SizedBox(height: 20),
                _CryptoLiteEmptyState(
                  onAddWallet:
                      () => _addCryptoWallet(context),
                  onAddSeed:
                      () => _addSeedOrPrivateKey(context),
                  onAddNote:
                      () => _addCryptoNote(
                            context, noteType: 'general'),
                ),
                const SizedBox(height: 20),
                _CryptoChatSuggestionsCard(
                  onSendChatPrompt: widget.onSendChatPrompt,
                ),
              ],
              if (isWide) const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}


class _CryptoLiteHero extends StatelessWidget {
  final int totalWallets;
  const _CryptoLiteHero({this.totalWallets = 0});
  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('crypto_lite_hero_card'),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: const Color(0xFF10A37F).withValues(alpha: 0.35),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 12,
            runSpacing: 8,
            children: [
              const Text(
                kCryptoVaultLiteHeading,
                key: Key('crypto_vault_lite_heading'),
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.w800,
                ),
              ),
              Container(
                key: const Key('crypto_lite_active_chip'),
                padding: const EdgeInsets.symmetric(
                  horizontal: 10, vertical: 4,
                ),
                decoration: BoxDecoration(
                  color: const Color(0xFF10A37F).withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(
                    color: const Color(0xFF10A37F).withValues(alpha: 0.45),
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: const [
                    Icon(
                      Icons.check_circle_outline,
                      size: 14,
                      color: Color(0xFF10A37F),
                    ),
                    SizedBox(width: 6),
                    Text(
                      kCryptoVaultLiteStatus,
                      style: TextStyle(
                        color: Color(0xFF10A37F),
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          const Text(
            kCryptoVaultLiteSubtitle,
            key: Key('crypto_vault_lite_subtitle'),
            style: TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 14,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 12),
          
          
          Wrap(
            key: const Key('crypto_lite_hero_totals'),
            spacing: 8,
            runSpacing: 8,
            children: [
              _HeroTotalChip(
                keyName: 'crypto_lite_hero_total_wallets',
                icon: Icons.account_balance_wallet_outlined,
                label: 'Saved wallets',
                value: '$totalWallets',
              ),
              _HeroTotalChip(
                keyName: 'crypto_lite_hero_total_balance',
                icon: Icons.show_chart,
                label: 'Balance',
                value: kCryptoBalanceLookupNotConnected,
                tonal: true,
              ),
            ],
          ),
          const SizedBox(height: 12),
          
          Container(
            key: const Key('crypto_lite_security_note'),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: const Color(0xFF262626),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.white10),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [
                Icon(
                  Icons.shield_outlined,
                  size: 18,
                  color: Color(0xFFB4B4B4),
                ),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    kCryptoVaultLiteSecurityNote,
                    style: TextStyle(
                      color: Color(0xFFB4B4B4),
                      fontSize: 12.5,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


class _HeroTotalChip extends StatelessWidget {
  final String keyName;
  final IconData icon;
  final String label;
  final String value;
  final bool tonal;
  const _HeroTotalChip({
    required this.keyName,
    required this.icon,
    required this.label,
    required this.value,
    this.tonal = false,
  });
  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key(keyName),
      padding: const EdgeInsets.symmetric(
        horizontal: 10, vertical: 6,
      ),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: const Color(0xFFB4B4B4)),
          const SizedBox(width: 6),
          Text(
            '$label: ',
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          Flexible(
            child: Text(
              value,
              key: Key('${keyName}_value'),
              style: TextStyle(
                color: tonal
                    ? const Color(0xFFB4B4B4)
                    : Colors.white,
                fontSize: 12.5,
                fontWeight: FontWeight.w800,
              ),
              overflow: TextOverflow.ellipsis,
              maxLines: 1,
            ),
          ),
        ],
      ),
    );
  }
}


class _CryptoCounterRow extends StatelessWidget {
  final List<Map<String, dynamic>> records;
  const _CryptoCounterRow({required this.records});

  int _count(CryptoCounterSpec spec) {
    int total = 0;
    for (final r in records) {
      final type =
          (r['type'] ?? r['item_type'] ?? '').toString();
      if (spec.matches(type)) total++;
    }
    return total;
  }

  @override
  Widget build(BuildContext context) {
    return Wrap(
      key: const Key('crypto_lite_counters'),
      spacing: 10,
      runSpacing: 10,
      children: kCryptoCounters.map((spec) {
        final count = _count(spec);
        return Container(
          key: Key(spec.key),
          padding: const EdgeInsets.symmetric(
            horizontal: 14, vertical: 10,
          ),
          decoration: BoxDecoration(
            color: const Color(0xFF1F1F1F),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white10),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                spec.icon,
                size: 16,
                color: const Color(0xFFB4B4B4),
              ),
              const SizedBox(width: 8),
              Text(
                '${spec.label}: ',
                style: const TextStyle(
                  color: Color(0xFFB4B4B4),
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                '$count',
                key: Key('${spec.key}_value'),
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        );
      }).toList(growable: false),
    );
  }
}


class _CryptoFeatureTiles extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.of(context).size.width;
    
    
    final isNarrow = width < 520;
    final tileWidth = isNarrow ? (width - 60) / 2 : 168.0;
    return Wrap(
      key: const Key('crypto_lite_feature_tiles'),
      spacing: 12,
      runSpacing: 12,
      children: kCryptoFeatureTiles.map((t) {
        return SizedBox(
          width: tileWidth,
          child: Container(
            key: Key(t.key),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFF1F1F1F),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  t.icon,
                  size: 20,
                  color: const Color(0xFF10A37F),
                ),
                const SizedBox(height: 8),
                Text(
                  t.title,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  t.body,
                  style: const TextStyle(
                    color: Color(0xFFB4B4B4),
                    fontSize: 12,
                    height: 1.35,
                  ),
                ),
              ],
            ),
          ),
        );
      }).toList(growable: false),
    );
  }
}


class _CryptoLiteEmptyState extends StatelessWidget {
  final VoidCallback onAddWallet;
  final VoidCallback onAddSeed;
  final VoidCallback onAddNote;
  const _CryptoLiteEmptyState({
    required this.onAddWallet,
    required this.onAddSeed,
    required this.onAddNote,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('crypto_lite_empty_state_card'),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            kCryptoLiteEmptyTitle,
            key: Key('crypto_lite_empty_title'),
            style: TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w800,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            kCryptoLiteEmptyBody,
            key: Key('crypto_lite_empty_body'),
            style: TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 13,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              ElevatedButton.icon(
                key: const Key('crypto_lite_empty_primary_button'),
                onPressed: onAddWallet,
                icon: const Icon(
                  Icons.account_balance_wallet_outlined, size: 18,
                ),
                label: const Text(kCryptoLiteEmptyPrimaryLabel),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF10A37F),
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16, vertical: 12,
                  ),
                ),
              ),
              OutlinedButton.icon(
                key: const Key('crypto_lite_empty_secondary_seed_button'),
                onPressed: onAddSeed,
                icon: const Icon(
                  Icons.warning_amber_outlined, size: 18,
                ),
                label: const Text(kCryptoLiteEmptySecondarySeed),
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.white,
                  side: const BorderSide(color: Colors.white24),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16, vertical: 12,
                  ),
                ),
              ),
              OutlinedButton.icon(
                key: const Key('crypto_lite_empty_secondary_note_button'),
                onPressed: onAddNote,
                icon: const Icon(Icons.notes_outlined, size: 18),
                label: const Text(kCryptoLiteEmptySecondaryNote),
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.white,
                  side: const BorderSide(color: Colors.white24),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16, vertical: 12,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}


class _CryptoChatSuggestionsCard extends StatelessWidget {
  final void Function(String prompt)? onSendChatPrompt;
  const _CryptoChatSuggestionsCard({required this.onSendChatPrompt});

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('crypto_lite_chat_suggestions_card'),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(
                Icons.chat_bubble_outline,
                size: 16,
                color: Color(0xFFB4B4B4),
              ),
              SizedBox(width: 8),
              Text(
                'Try asking VaultAI:',
                style: TextStyle(
                  color: Color(0xFFB4B4B4),
                  fontSize: 12.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: kCryptoChatSuggestions.map((s) {
              return ActionChip(
                key: Key(s.key),
                label: Text(s.label),
                labelStyle: const TextStyle(
                  color: Color(0xFFE0E0E0),
                  fontSize: 12,
                ),
                backgroundColor: const Color(0xFF262626),
                side: const BorderSide(color: Colors.white12),
                onPressed: () {
                  if (onSendChatPrompt != null) {
                    onSendChatPrompt!(s.prompt);
                  }
                },
              );
            }).toList(growable: false),
          ),
        ],
      ),
    );
  }
}


class _CryptoAssetDashboard extends StatelessWidget {
  final List<Map<String, dynamic>> records;
  final void Function(CryptoAsset asset) onAddWalletForAsset;
  final void Function(CryptoAsset asset) onViewWalletsForAsset;
  const _CryptoAssetDashboard({
    required this.records,
    required this.onAddWalletForAsset,
    required this.onViewWalletsForAsset,
  });

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.of(context).size.width;
    
    final isNarrow = width < 600;
    final tileWidth = isNarrow ? (width - 60) / 2 : 220.0;
    return Column(
      key: const Key('crypto_lite_asset_dashboard'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.only(left: 2, bottom: 8),
          child: Text(
            'Supported assets',
            key: Key('crypto_lite_asset_dashboard_title'),
            style: TextStyle(
              color: Color(0xFFE0E0E0),
              fontSize: 14,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: kCryptoAssets.map((a) {
            return SizedBox(
              width: tileWidth,
              child: _CryptoAssetCard(
                asset: a,
                walletCount: cryptoWalletCountForAsset(records, a),
                onAddWallet: () => onAddWalletForAsset(a),
                onViewWallets: () => onViewWalletsForAsset(a),
              ),
            );
          }).toList(growable: false),
        ),
      ],
    );
  }
}

class _CryptoAssetCard extends StatelessWidget {
  final CryptoAsset asset;
  final int walletCount;
  final VoidCallback onAddWallet;
  final VoidCallback onViewWallets;
  const _CryptoAssetCard({
    required this.asset,
    required this.walletCount,
    required this.onAddWallet,
    required this.onViewWallets,
  });

  String _balanceCopy() {
    if (asset.isPrivacyChain) return kCryptoBalanceUnavailableMonero;
    return kCryptoBalanceUnavailable;
  }

  @override
  Widget build(BuildContext context) {
    final accent = Color(asset.accentArgb);
    final hasWallets = walletCount > 0;
    return Container(
      key: Key('crypto_lite_asset_card_${asset.id}'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: accent.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  asset.icon,
                  size: 16,
                  color: accent,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      asset.displayName,
                      key: Key(
                        'crypto_lite_asset_card_${asset.id}_name',
                      ),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      asset.ticker,
                      style: TextStyle(
                        color: accent,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.6,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          
          Row(
            children: [
              const Icon(
                Icons.account_balance_wallet_outlined,
                size: 14,
                color: Color(0xFFB4B4B4),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  hasWallets
                      ? '$walletCount saved'
                      : kCryptoNoWalletSaved,
                  key: Key(
                    'crypto_lite_asset_card_${asset.id}_count',
                  ),
                  style: const TextStyle(
                    color: Color(0xFFE0E0E0),
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          
          
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(
                Icons.show_chart,
                size: 14,
                color: Color(0xFFB4B4B4),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  _balanceCopy(),
                  key: Key(
                    'crypto_lite_asset_card_${asset.id}_balance',
                  ),
                  style: const TextStyle(
                    color: Color(0xFFB4B4B4),
                    fontSize: 11.5,
                    height: 1.35,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              SizedBox(
                height: 28,
                child: TextButton.icon(
                  key: Key(
                    'crypto_lite_asset_card_${asset.id}_add_button',
                  ),
                  onPressed: onAddWallet,
                  icon: const Icon(Icons.add, size: 14),
                  label: const Text(
                    kCryptoAddWalletAction,
                    style: TextStyle(fontSize: 12),
                  ),
                  style: TextButton.styleFrom(
                    foregroundColor: accent,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8, vertical: 0,
                    ),
                    minimumSize: const Size(0, 28),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
              ),
              if (hasWallets)
                SizedBox(
                  height: 28,
                  child: TextButton.icon(
                    key: Key(
                      'crypto_lite_asset_card_${asset.id}'
                      '_view_button',
                    ),
                    onPressed: onViewWallets,
                    icon: const Icon(Icons.list_alt, size: 14),
                    label: const Text(
                      kCryptoViewWalletsAction,
                      style: TextStyle(fontSize: 12),
                    ),
                    style: TextButton.styleFrom(
                      foregroundColor: const Color(0xFFE0E0E0),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 0,
                      ),
                      minimumSize: const Size(0, 28),
                      tapTargetSize:
                          MaterialTapTargetSize.shrinkWrap,
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}


class CryptoAddWalletDraft {
  final CryptoAsset asset;
  final CryptoWalletLabel label;
  final String address;
  final String note;
  const CryptoAddWalletDraft({
    required this.asset,
    required this.label,
    required this.address,
    required this.note,
  });

  
  String toChatPrompt() {
    final lbl  = label.displayName;
    final net  = asset.networkLabel;
    final addr = address.trim();
    final base = 'Save my $lbl $net wallet at address $addr';
    final n = note.trim();
    if (n.isEmpty) return base;
    final safe = n.replaceAll('"', "'");
    return '$base with note "$safe"';
  }
}


Future<CryptoAddWalletDraft?> showAddCryptoWalletDialog(
  BuildContext context, {
  CryptoAsset? preselectedAsset,
  Future<void> Function(CryptoAddWalletDraft draft)? onSave,
  
  
  CryptoAddWalletDraft? initialDraft,
  
  String? titleOverride,
}) {
  return showDialog<CryptoAddWalletDraft>(
    context: context,
    barrierDismissible: onSave == null,
    builder: (ctx) => _AddCryptoWalletDialog(
      preselectedAsset: preselectedAsset ?? initialDraft?.asset,
      initialDraft:     initialDraft,
      titleOverride:    titleOverride,
      onSave:           onSave,
    ),
  );
}

class _AddCryptoWalletDialog extends StatefulWidget {
  final CryptoAsset? preselectedAsset;
  final CryptoAddWalletDraft? initialDraft;
  final String? titleOverride;
  final Future<void> Function(CryptoAddWalletDraft draft)? onSave;
  const _AddCryptoWalletDialog({
    this.preselectedAsset,
    this.initialDraft,
    this.titleOverride,
    this.onSave,
  });

  @override
  State<_AddCryptoWalletDialog> createState() =>
      _AddCryptoWalletDialogState();
}

class _AddCryptoWalletDialogState
    extends State<_AddCryptoWalletDialog> {
  late CryptoAsset? _asset;
  CryptoWalletLabel? _label;
  late final TextEditingController _addressCtrl;
  late final TextEditingController _noteCtrl;
  String? _assetError;
  String? _labelError;
  String? _addressError;
  String? _saveError;
  bool _addressFormatWarning = false;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final initial = widget.initialDraft;
    _asset = initial?.asset ?? widget.preselectedAsset;
    _label = initial?.label;
    _addressCtrl = TextEditingController(
      text: initial?.address ?? '',
    );
    _noteCtrl = TextEditingController(
      text: initial?.note ?? '',
    );
  }

  @override
  void dispose() {
    _addressCtrl.dispose();
    _noteCtrl.dispose();
    super.dispose();
  }

  Future<void> _onSave() async {
    if (_saving) return;
    setState(() {
      _assetError   = _asset == null
          ? kCryptoAddWalletValidationErrorAsset : null;
      _labelError   = _label == null
          ? kCryptoAddWalletValidationErrorLabel : null;
      final addr = _addressCtrl.text.trim();
      _addressError = addr.isEmpty
          ? kCryptoAddWalletValidationErrorAddress : null;
      _addressFormatWarning = false;
      _saveError = null;
      if (_asset != null
          && addr.isNotEmpty
          && !cryptoAddressMatchesAsset(_asset!, addr)) {
        _addressFormatWarning = true;
      }
    });
    if (_assetError != null
        || _labelError != null
        || _addressError != null) return;
    
    
    if (_addressFormatWarning) {
      final proceed = await showDialog<bool>(
        context: context,
        builder: (ctx2) => AlertDialog(
          key: const Key(
            'crypto_lite_add_wallet_format_warning_dialog',
          ),
          backgroundColor: const Color(0xFF1F1F1F),
          title: Text(
            AppLocalizations.of(ctx2).cryptoLiteAddressFormatMismatchTitle,
          ),
          content: const Text(kCryptoAddWalletAddressFormatHint),
          actions: [
            TextButton(
              key: const Key(
                'crypto_lite_add_wallet_format_warning_cancel',
              ),
              onPressed: () => Navigator.of(ctx2).pop(false),
              child: Text(AppLocalizations.of(ctx2).commonReview),
            ),
            ElevatedButton(
              key: const Key(
                'crypto_lite_add_wallet_format_warning_continue',
              ),
              onPressed: () => Navigator.of(ctx2).pop(true),
              child: Text(AppLocalizations.of(ctx2).cryptoLiteSaveAnyway),
            ),
          ],
        ),
      );
      if (proceed != true) return;
    }
    if (!mounted) return;
    final draft = CryptoAddWalletDraft(
      asset:   _asset!,
      label:   _label!,
      address: _addressCtrl.text.trim(),
      note:    _noteCtrl.text.trim(),
    );
    
    
    if (widget.onSave != null) {
      setState(() {
        _saving    = true;
        _saveError = null;
      });
      try {
        await widget.onSave!(draft);
      } catch (e) {
        if (!mounted) return;
        setState(() {
          _saving    = false;
          _saveError = _formatSaveError(e);
        });
        return;
      }
      if (!mounted) return;
      Navigator.of(context).pop(draft);
      return;
    }
    
    Navigator.of(context).pop(draft);
  }

  static String _formatSaveError(Object e) {
    final s = e.toString();
    
    
    if (s.startsWith('Exception: ')) return s.substring(11);
    return s;
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const Key('crypto_lite_add_wallet_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      title: Text(
        widget.titleOverride ?? kCryptoAddWalletDialogTitle,
        key: const Key('crypto_lite_add_wallet_dialog_title'),
      ),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              
              DropdownButtonFormField<CryptoAsset>(
                key: const Key(
                  'crypto_lite_add_wallet_asset_dropdown',
                ),
                initialValue: _asset,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: kCryptoAddWalletAssetFieldLabel,
                  errorText: _assetError,
                ),
                items: kCryptoAssets.map((a) {
                  return DropdownMenuItem<CryptoAsset>(
                    value: a,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(a.icon,
                            size: 16,
                            color: Color(a.accentArgb)),
                        const SizedBox(width: 8),
                        Flexible(
                          child: Text(
                            a.displayName,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  );
                }).toList(growable: false),
                onChanged: (v) => setState(() {
                  _asset = v;
                  _assetError = null;
                }),
              ),
              const SizedBox(height: 12),
              
              DropdownButtonFormField<CryptoWalletLabel>(
                key: const Key(
                  'crypto_lite_add_wallet_label_dropdown',
                ),
                initialValue: _label,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: kCryptoAddWalletLabelFieldLabel,
                  errorText: _labelError,
                ),
                items: kCryptoWalletLabels.map((l) {
                  return DropdownMenuItem<CryptoWalletLabel>(
                    value: l,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(l.icon, size: 16,
                            color: const Color(0xFFB4B4B4)),
                        const SizedBox(width: 8),
                        Flexible(
                          child: Text(
                            l.displayName,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  );
                }).toList(growable: false),
                onChanged: (v) => setState(() {
                  _label = v;
                  _labelError = null;
                }),
              ),
              const SizedBox(height: 12),
              
              TextField(
                key: const Key(
                  'crypto_lite_add_wallet_address_field',
                ),
                controller: _addressCtrl,
                style: const TextStyle(fontFamily: 'monospace'),
                decoration: InputDecoration(
                  labelText: kCryptoAddWalletAddressFieldLabel,
                  errorText: _addressError,
                ),
              ),
              const SizedBox(height: 12),
              
              TextField(
                key: const Key(
                  'crypto_lite_add_wallet_note_field',
                ),
                controller: _noteCtrl,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: kCryptoAddWalletNoteFieldLabel,
                ),
              ),
              const SizedBox(height: 14),
              Container(
                key: const Key(
                  'crypto_lite_add_wallet_security_note',
                ),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFF262626),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white10),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    Icon(Icons.shield_outlined,
                        size: 16,
                        color: Color(0xFFB4B4B4)),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        kCryptoAddWalletSecurityNote,
                        style: TextStyle(
                          color: Color(0xFFB4B4B4),
                          fontSize: 12,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              if (_saveError != null) ...[
                const SizedBox(height: 12),
                Container(
                  key: const Key(
                    'crypto_lite_add_wallet_save_error',
                  ),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF3A1F1F),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: const Color(0xFFE57373),
                    ),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.error_outline,
                          size: 16, color: Color(0xFFE57373)),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _saveError!,
                          style: const TextStyle(
                            color: Color(0xFFE57373),
                            fontSize: 12.5,
                            height: 1.4,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key('crypto_lite_add_wallet_cancel_button'),
          onPressed: _saving
              ? null
              : () => Navigator.of(context).pop(),
          child: const Text(kCryptoAddWalletDialogCancelLabel),
        ),
        ElevatedButton(
          key: const Key('crypto_lite_add_wallet_save_button'),
          onPressed: _saving ? null : _onSave,
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF10A37F),
            foregroundColor: Colors.white,
          ),
          child: _saving
              ? const SizedBox(
                  height: 16, width: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : const Text(kCryptoAddWalletDialogSaveLabel),
        ),
      ],
    );
  }
}


const String kCryptoSensitiveBackupDialogTitle = 'Save sensitive backup';
const String kCryptoSensitiveBackupSaveLabel   = 'Save backup';
const String kCryptoSensitiveBackupCancelLabel = 'Cancel';
const String kCryptoSensitiveBackupSecretField = 'Secret value';
const String kCryptoSensitiveBackupNoteField   = 'Optional note';
const String kCryptoSensitiveBackupAssetField  = 'Asset / network (optional)';
const String kCryptoSensitiveBackupLabelField  = 'Wallet label';
const String kCryptoSensitiveBackupTypeField   = 'Backup type';
const String kCryptoSensitiveBackupWarningCopy =
    'This is extremely sensitive. Anyone with this phrase or '
    'key can control the wallet. It is encrypted before storage.';
const String kCryptoSensitiveBackupValidationLabel =
    'Select a wallet label.';
const String kCryptoSensitiveBackupValidationType =
    'Select a backup type.';
const String kCryptoSensitiveBackupValidationValue =
    'Enter the secret value.';


class CryptoSecretType {
  final String id;
  final String displayName;
  const CryptoSecretType({required this.id, required this.displayName});
}

const CryptoSecretType kSecretTypeSeedPhrase = CryptoSecretType(
  id: 'seed_phrase', displayName: 'Seed phrase',
);
const CryptoSecretType kSecretTypePrivateKey = CryptoSecretType(
  id: 'private_key', displayName: 'Private key',
);
const CryptoSecretType kSecretTypeRecoveryPhrase = CryptoSecretType(
  id: 'recovery_phrase', displayName: 'Recovery phrase',
);

const List<CryptoSecretType> kCryptoSecretTypes = <CryptoSecretType>[
  kSecretTypeSeedPhrase,
  kSecretTypePrivateKey,
  kSecretTypeRecoveryPhrase,
];


class CryptoAddSensitiveBackupDraft {
  final CryptoAsset? asset;
  final CryptoWalletLabel label;
  final CryptoSecretType secretType;
  final String secretValue;
  final String note;
  
  
  final bool warningConfirmed;
  const CryptoAddSensitiveBackupDraft({
    required this.asset,
    required this.label,
    required this.secretType,
    required this.secretValue,
    required this.note,
    required this.warningConfirmed,
  });
}


Future<CryptoAddSensitiveBackupDraft?> showAddSensitiveBackupDialog(
  BuildContext context, {
  required Future<void> Function(CryptoAddSensitiveBackupDraft draft)
      onSave,
}) {
  return showDialog<CryptoAddSensitiveBackupDraft>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => _AddSensitiveBackupDialog(onSave: onSave),
  );
}


class _AddSensitiveBackupDialog extends StatefulWidget {
  final Future<void> Function(CryptoAddSensitiveBackupDraft draft)
      onSave;
  const _AddSensitiveBackupDialog({required this.onSave});

  @override
  State<_AddSensitiveBackupDialog> createState() =>
      _AddSensitiveBackupDialogState();
}


class _AddSensitiveBackupDialogState
    extends State<_AddSensitiveBackupDialog> {
  CryptoAsset? _asset;
  CryptoWalletLabel? _label;
  CryptoSecretType? _secretType;
  late final TextEditingController _secretCtrl;
  late final TextEditingController _noteCtrl;
  String? _labelError;
  String? _typeError;
  String? _secretError;
  String? _saveError;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _secretCtrl = TextEditingController(text: '');
    _noteCtrl   = TextEditingController(text: '');
  }

  @override
  void dispose() {
    _secretCtrl.dispose();
    _noteCtrl.dispose();
    super.dispose();
  }

  Future<void> _onSave() async {
    if (_saving) return;
    setState(() {
      _labelError  = _label == null
          ? kCryptoSensitiveBackupValidationLabel : null;
      _typeError   = _secretType == null
          ? kCryptoSensitiveBackupValidationType : null;
      _secretError = _secretCtrl.text.trim().isEmpty
          ? kCryptoSensitiveBackupValidationValue : null;
      _saveError   = null;
    });
    if (_labelError != null
        || _typeError != null
        || _secretError != null) return;
    final draft = CryptoAddSensitiveBackupDraft(
      asset:            _asset,
      label:            _label!,
      secretType:       _secretType!,
      secretValue:      _secretCtrl.text.trim(),
      note:             _noteCtrl.text.trim(),
      warningConfirmed: true,
    );
    setState(() {
      _saving    = true;
      _saveError = null;
    });
    try {
      await widget.onSave(draft);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving    = false;
        _saveError = _AddCryptoWalletDialogState._formatSaveError(e);
      });
      return;
    }
    if (!mounted) return;
    Navigator.of(context).pop(draft);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const Key('crypto_lite_add_sensitive_backup_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      title: const Text(
        kCryptoSensitiveBackupDialogTitle,
        key: Key('crypto_lite_add_sensitive_backup_dialog_title'),
      ),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                key: const Key(
                  'crypto_lite_add_sensitive_backup_warning',
                ),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFF3A2E1F),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: const Color(0xFFFFB300).withValues(alpha: 0.45),
                  ),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    Icon(Icons.warning_amber_outlined,
                        size: 18, color: Color(0xFFFFB300)),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        kCryptoSensitiveBackupWarningCopy,
                        style: TextStyle(
                          color: Color(0xFFEEDDB4),
                          fontSize: 12.5, height: 1.4,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              DropdownButtonFormField<CryptoWalletLabel>(
                key: const Key(
                  'crypto_lite_add_sensitive_backup_label_dropdown',
                ),
                initialValue: _label,
                decoration: InputDecoration(
                  labelText: kCryptoSensitiveBackupLabelField,
                  errorText: _labelError,
                ),
                items: kCryptoWalletLabels.map((l) {
                  return DropdownMenuItem<CryptoWalletLabel>(
                    value: l,
                    child: Text(l.displayName),
                  );
                }).toList(growable: false),
                onChanged: (v) => setState(() {
                  _label = v;
                  _labelError = null;
                }),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<CryptoSecretType>(
                key: const Key(
                  'crypto_lite_add_sensitive_backup_type_dropdown',
                ),
                initialValue: _secretType,
                decoration: InputDecoration(
                  labelText: kCryptoSensitiveBackupTypeField,
                  errorText: _typeError,
                ),
                items: kCryptoSecretTypes.map((s) {
                  return DropdownMenuItem<CryptoSecretType>(
                    value: s,
                    child: Text(s.displayName),
                  );
                }).toList(growable: false),
                onChanged: (v) => setState(() {
                  _secretType = v;
                  _typeError  = null;
                }),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<CryptoAsset>(
                key: const Key(
                  'crypto_lite_add_sensitive_backup_asset_dropdown',
                ),
                initialValue: _asset,
                decoration: const InputDecoration(
                  labelText: kCryptoSensitiveBackupAssetField,
                ),
                items: kCryptoAssets.map((a) {
                  return DropdownMenuItem<CryptoAsset>(
                    value: a,
                    child: Text(a.displayName),
                  );
                }).toList(growable: false),
                onChanged: (v) => setState(() => _asset = v),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key(
                  'crypto_lite_add_sensitive_backup_value_field',
                ),
                controller: _secretCtrl,
                obscureText: true,
                maxLines: 1,
                style: const TextStyle(fontFamily: 'monospace'),
                decoration: InputDecoration(
                  labelText: kCryptoSensitiveBackupSecretField,
                  errorText: _secretError,
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key(
                  'crypto_lite_add_sensitive_backup_note_field',
                ),
                controller: _noteCtrl,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: kCryptoSensitiveBackupNoteField,
                ),
              ),
              if (_saveError != null) ...[
                const SizedBox(height: 12),
                Container(
                  key: const Key(
                    'crypto_lite_add_sensitive_backup_save_error',
                  ),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF3A1F1F),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: const Color(0xFFE57373),
                    ),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.error_outline,
                          size: 16, color: Color(0xFFE57373)),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _saveError!,
                          style: const TextStyle(
                            color: Color(0xFFE57373),
                            fontSize: 12.5, height: 1.4,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key(
            'crypto_lite_add_sensitive_backup_cancel_button',
          ),
          onPressed: _saving
              ? null
              : () => Navigator.of(context).pop(),
          child: const Text(kCryptoSensitiveBackupCancelLabel),
        ),
        ElevatedButton(
          key: const Key(
            'crypto_lite_add_sensitive_backup_save_button',
          ),
          onPressed: _saving ? null : _onSave,
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFFFFB300),
            foregroundColor: Colors.black,
          ),
          child: _saving
              ? const SizedBox(
                  height: 16, width: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.black,
                  ),
                )
              : const Text(kCryptoSensitiveBackupSaveLabel),
        ),
      ],
    );
  }
}


const String kCryptoAddNoteGeneralTitle      = 'Add crypto note';
const String kCryptoAddNoteTxTitle           = 'Add transaction note';
const String kCryptoAddNoteSaveLabel         = 'Save';
const String kCryptoAddNoteCancelLabel       = 'Cancel';
const String kCryptoAddNoteAssetFieldLabel   = 'Asset / network (optional)';
const String kCryptoAddNoteTitleFieldLabel   = 'Title';
const String kCryptoAddNoteBodyFieldLabel    = 'Note';
const String kCryptoAddNoteWalletFieldLabel  = 'Wallet label (optional)';
const String kCryptoAddNoteTxHashFieldLabel  = 'Transaction hash (optional)';
const String kCryptoAddNoteAmountFieldLabel  = 'Amount text (optional)';
const String kCryptoAddNoteDateFieldLabel    = 'Date text (optional)';
const String kCryptoAddNoteValidationTitle   = 'Title is required.';
const String kCryptoAddNoteValidationBody    = 'Note is required.';


const String kCryptoTxNoteManualSafetyCopy =
    'This is a manual note. VaultAI is not sending or verifying '
    'a blockchain transaction.';

const String kCryptoNotesSectionSafetyCopy =
    'Transaction notes are manual notes only. VaultAI is not '
    'sending, signing, broadcasting, or verifying blockchain '
    'transactions.';


class CryptoAddNoteDraft {
  final String noteType; 
  final String title;
  final String note;
  final CryptoAsset? asset;
  final CryptoWalletLabel? walletLabel;
  final String txHash;
  final String amountText;
  final String dateText;
  const CryptoAddNoteDraft({
    required this.noteType,
    required this.title,
    required this.note,
    this.asset,
    this.walletLabel,
    this.txHash    = '',
    this.amountText = '',
    this.dateText   = '',
  });
}


Future<CryptoAddNoteDraft?> showAddCryptoNoteDialog(
  BuildContext context, {
  required String noteType,
  required Future<void> Function(CryptoAddNoteDraft draft) onSave,
}) {
  return showDialog<CryptoAddNoteDraft>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => _AddCryptoNoteDialog(
      noteType: noteType,
      onSave:   onSave,
    ),
  );
}


class _AddCryptoNoteDialog extends StatefulWidget {
  final String noteType;
  final Future<void> Function(CryptoAddNoteDraft draft) onSave;
  const _AddCryptoNoteDialog({
    required this.noteType,
    required this.onSave,
  });
  @override
  State<_AddCryptoNoteDialog> createState() =>
      _AddCryptoNoteDialogState();
}


class _AddCryptoNoteDialogState
    extends State<_AddCryptoNoteDialog> {
  CryptoAsset? _asset;
  CryptoWalletLabel? _walletLabel;
  late final TextEditingController _titleCtrl;
  late final TextEditingController _bodyCtrl;
  late final TextEditingController _txHashCtrl;
  late final TextEditingController _amountCtrl;
  late final TextEditingController _dateCtrl;
  String? _titleError;
  String? _bodyError;
  String? _saveError;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _titleCtrl  = TextEditingController();
    _bodyCtrl   = TextEditingController();
    _txHashCtrl = TextEditingController();
    _amountCtrl = TextEditingController();
    _dateCtrl   = TextEditingController();
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    _bodyCtrl.dispose();
    _txHashCtrl.dispose();
    _amountCtrl.dispose();
    _dateCtrl.dispose();
    super.dispose();
  }

  bool get _isTx => widget.noteType == 'transaction_note';

  Future<void> _onSave() async {
    if (_saving) return;
    final title = _titleCtrl.text.trim();
    final body  = _bodyCtrl.text.trim();
    setState(() {
      _titleError = title.isEmpty
          ? kCryptoAddNoteValidationTitle : null;
      _bodyError  = body.isEmpty
          ? kCryptoAddNoteValidationBody : null;
      _saveError = null;
    });
    if (_titleError != null || _bodyError != null) return;
    final draft = CryptoAddNoteDraft(
      noteType:    widget.noteType,
      title:       title,
      note:        body,
      asset:       _asset,
      walletLabel: _walletLabel,
      txHash:      _txHashCtrl.text.trim(),
      amountText:  _amountCtrl.text.trim(),
      dateText:    _dateCtrl.text.trim(),
    );
    setState(() => _saving = true);
    try {
      await widget.onSave(draft);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving    = false;
        _saveError = _AddCryptoWalletDialogState._formatSaveError(e);
      });
      return;
    }
    if (!mounted) return;
    Navigator.of(context).pop(draft);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: Key(
        _isTx
            ? 'crypto_lite_add_tx_note_dialog'
            : 'crypto_lite_add_general_note_dialog',
      ),
      backgroundColor: const Color(0xFF1F1F1F),
      title: Text(
        _isTx
            ? kCryptoAddNoteTxTitle
            : kCryptoAddNoteGeneralTitle,
        key: Key(
          _isTx
              ? 'crypto_lite_add_tx_note_dialog_title'
              : 'crypto_lite_add_general_note_dialog_title',
        ),
      ),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_isTx) ...[
                Container(
                  key: const Key(
                    'crypto_lite_add_tx_note_safety_copy',
                  ),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF262626),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.white10),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Icon(Icons.info_outline,
                          size: 16, color: Color(0xFFB4B4B4)),
                      SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          kCryptoTxNoteManualSafetyCopy,
                          style: TextStyle(
                            color: Color(0xFFB4B4B4),
                            fontSize: 12.5, height: 1.4,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
              ],
              DropdownButtonFormField<CryptoAsset>(
                key: const Key(
                  'crypto_lite_add_note_asset_dropdown',
                ),
                initialValue: _asset,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: kCryptoAddNoteAssetFieldLabel,
                ),
                items: kCryptoAssets.map((a) {
                  return DropdownMenuItem<CryptoAsset>(
                    value: a,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(a.icon,
                            size: 16, color: Color(a.accentArgb)),
                        const SizedBox(width: 8),
                        Flexible(
                          child: Text(
                            a.displayName,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  );
                }).toList(growable: false),
                onChanged: (v) => setState(() => _asset = v),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('crypto_lite_add_note_title_field'),
                controller: _titleCtrl,
                decoration: InputDecoration(
                  labelText: kCryptoAddNoteTitleFieldLabel,
                  errorText: _titleError,
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('crypto_lite_add_note_body_field'),
                controller: _bodyCtrl,
                maxLines: 4,
                decoration: InputDecoration(
                  labelText: kCryptoAddNoteBodyFieldLabel,
                  errorText: _bodyError,
                ),
              ),
              if (_isTx) ...[
                const SizedBox(height: 12),
                DropdownButtonFormField<CryptoWalletLabel>(
                  key: const Key(
                    'crypto_lite_add_tx_note_wallet_dropdown',
                  ),
                  initialValue: _walletLabel,
                  isExpanded: true,
                  decoration: const InputDecoration(
                    labelText: kCryptoAddNoteWalletFieldLabel,
                  ),
                  items: kCryptoWalletLabels.map((l) {
                    return DropdownMenuItem<CryptoWalletLabel>(
                      value: l,
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(l.icon, size: 16,
                              color: const Color(0xFFB4B4B4)),
                          const SizedBox(width: 8),
                          Flexible(
                            child: Text(
                              l.displayName,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ),
                    );
                  }).toList(growable: false),
                  onChanged: (v) => setState(() => _walletLabel = v),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key(
                    'crypto_lite_add_tx_note_tx_hash_field',
                  ),
                  controller: _txHashCtrl,
                  style: const TextStyle(fontFamily: 'monospace'),
                  decoration: const InputDecoration(
                    labelText: kCryptoAddNoteTxHashFieldLabel,
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key(
                    'crypto_lite_add_tx_note_amount_field',
                  ),
                  controller: _amountCtrl,
                  decoration: const InputDecoration(
                    labelText: kCryptoAddNoteAmountFieldLabel,
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key(
                    'crypto_lite_add_tx_note_date_field',
                  ),
                  controller: _dateCtrl,
                  decoration: const InputDecoration(
                    labelText: kCryptoAddNoteDateFieldLabel,
                  ),
                ),
              ],
              if (_saveError != null) ...[
                const SizedBox(height: 12),
                Container(
                  key: const Key(
                    'crypto_lite_add_note_save_error',
                  ),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF3A1F1F),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: const Color(0xFFE57373),
                    ),
                  ),
                  child: Text(
                    _saveError!,
                    style: const TextStyle(
                      color: Color(0xFFE57373), fontSize: 12.5,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key('crypto_lite_add_note_cancel_button'),
          onPressed: _saving
              ? null
              : () => Navigator.of(context).pop(),
          child: const Text(kCryptoAddNoteCancelLabel),
        ),
        ElevatedButton(
          key: const Key('crypto_lite_add_note_save_button'),
          onPressed: _saving ? null : _onSave,
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF10A37F),
            foregroundColor: Colors.white,
          ),
          child: _saving
              ? const SizedBox(
                  height: 16, width: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2, color: Colors.white,
                  ),
                )
              : const Text(kCryptoAddNoteSaveLabel),
        ),
      ],
    );
  }
}


const String kCryptoWalletDetailTitle    = 'Wallet detail';
const String kCryptoBackupDetailTitle    = 'Backup detail';
const String kCryptoBackupRevealNotice   =
    'Sensitive value is saved encrypted. Reveal support will be '
    'added in a later security pass.';
const String kCryptoCopyAddressLabel     = 'Copy address';
const String kCryptoCopyAddressDoneToast = 'Address copied to clipboard';
const String kCryptoShowReceiveQRLabel   = 'Show receive QR';
const String kCryptoEditDetailLabel      = 'Edit';
const String kCryptoDeleteDetailLabel    = 'Delete';

const String kCryptoDeleteWalletTitle   = 'Delete this wallet from VaultAI?';
const String kCryptoDeleteWalletBody    =
    'This only removes the saved record from VaultAI. It does '
    'NOT affect the actual blockchain wallet — funds and the '
    'real address remain untouched.';
const String kCryptoDeleteWalletConfirm = 'Delete';
const String kCryptoDeleteWalletCancel  = 'Cancel';

const String kCryptoDeleteBackupTitle   =
    'Delete this encrypted backup from VaultAI?';
const String kCryptoDeleteBackupBody    =
    'This does not affect the original wallet. Make sure you '
    'still have another backup before deleting.';
const String kCryptoDeleteBackupConfirm = 'Delete backup';
const String kCryptoDeleteBackupCancel  = 'Cancel';


class CryptoBackupMetadataEdit {
  final CryptoAsset? asset;
  final CryptoWalletLabel label;
  final String note;
  const CryptoBackupMetadataEdit({
    required this.asset,
    required this.label,
    required this.note,
  });
}


class _CryptoWalletDetailData {
  final String title;
  final String walletAddress;
  final CryptoAsset? asset;
  final CryptoWalletLabel? label;
  final String network;
  final String note;
  const _CryptoWalletDetailData({
    required this.title,
    required this.walletAddress,
    required this.asset,
    required this.label,
    required this.network,
    required this.note,
  });

  factory _CryptoWalletDetailData.from(
    Map<String, dynamic> record,
    Map<String, dynamic>? detail,
  ) {
    String _readStr(Map? m, String k, [String fb = '']) {
      if (m == null) return fb;
      final raw = m[k];
      return raw is String ? raw : fb;
    }
    final fields = (detail?['fields'] is Map)
        ? detail!['fields'] as Map<String, dynamic>
        : <String, dynamic>{};
    final title = _readStr(detail, 'service')
        .isNotEmpty
        ? _readStr(detail, 'service')
        : _readStr(record, 'title', 'Crypto wallet');
    final address = _readStr(fields, 'wallet_address');
    final network = _readStr(fields, 'network');
    final assetCode = _readStr(fields, 'asset');
    final labelStr = _readStr(fields, 'wallet_label');
    final note = _readStr(detail, 'notes')
        .isNotEmpty
        ? _readStr(detail, 'notes')
        : _readStr(fields, 'note');
    
    CryptoAsset? asset;
    if (assetCode.isNotEmpty) {
      asset = cryptoAssetById(assetCode.toLowerCase())
          ?? cryptoAssetFromNetwork(assetCode);
    }
    asset ??= cryptoAssetFromNetwork(network);
    CryptoWalletLabel? label;
    if (labelStr.isNotEmpty) {
      final lower = labelStr.toLowerCase();
      for (final l in kCryptoWalletLabels) {
        if (l.displayName.toLowerCase() == lower
            || l.id == lower) {
          label = l;
          break;
        }
      }
    }
    return _CryptoWalletDetailData(
      title: title,
      walletAddress: address,
      asset: asset,
      label: label,
      network: network.isNotEmpty
          ? network
          : (asset?.networkLabel ?? ''),
      note: note,
    );
  }
}


Future<void> showCryptoWalletDetailDialog(
  BuildContext context, {
  required Map<String, dynamic> record,
  required Map<String, dynamic>? detail,
  void Function(Map<String, dynamic> record)? onCopyAddress,
  void Function(Map<String, dynamic> record)? onShowQR,
  Future<void> Function(
    Map<String, dynamic> record,
    CryptoAddWalletDraft edits,
  )? onUpdate,
  Future<void> Function(Map<String, dynamic> record)? onDelete,
}) async {
  final data = _CryptoWalletDetailData.from(record, detail);
  await showDialog<void>(
    context: context,
    builder: (ctx) => _CryptoWalletDetailDialog(
      record: record,
      data: data,
      onCopyAddress: onCopyAddress,
      onShowQR: onShowQR,
      onUpdate: onUpdate,
      onDelete: onDelete,
    ),
  );
}


class _CryptoWalletDetailDialog extends StatelessWidget {
  final Map<String, dynamic> record;
  final _CryptoWalletDetailData data;
  final void Function(Map<String, dynamic> record)? onCopyAddress;
  final void Function(Map<String, dynamic> record)? onShowQR;
  final Future<void> Function(
    Map<String, dynamic> record,
    CryptoAddWalletDraft edits,
  )? onUpdate;
  final Future<void> Function(Map<String, dynamic> record)? onDelete;
  const _CryptoWalletDetailDialog({
    required this.record,
    required this.data,
    this.onCopyAddress,
    this.onShowQR,
    this.onUpdate,
    this.onDelete,
  });

  Future<void> _copy(BuildContext context) async {
    
    
    await Clipboard.setData(ClipboardData(text: data.walletAddress));
    if (onCopyAddress != null) onCopyAddress!(record);
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      key: Key('crypto_wallet_detail_copy_toast'),
      content: Text(kCryptoCopyAddressDoneToast),
      duration: Duration(seconds: 2),
    ));
  }

  Future<void> _edit(BuildContext context) async {
    if (onUpdate == null) return;
    final initial = (data.asset != null && data.label != null)
        ? CryptoAddWalletDraft(
            asset:   data.asset!,
            label:   data.label!,
            address: data.walletAddress,
            note:    data.note,
          )
        : null;
    await showAddCryptoWalletDialog(
      context,
      preselectedAsset: data.asset,
      initialDraft: initial,
      titleOverride: 'Edit crypto wallet',
      onSave: (draft) => onUpdate!(record, draft),
    );
  }

  Future<void> _delete(BuildContext context) async {
    if (onDelete == null) return;
    final confirmed = await showCryptoDeleteWalletConfirmationDialog(
      context,
      onConfirm: () => onDelete!(record),
    );
    if (confirmed == true && context.mounted) {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const Key('crypto_wallet_detail_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      title: const Text(
        kCryptoWalletDetailTitle,
        key: Key('crypto_wallet_detail_dialog_title'),
      ),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                data.title,
                key: const Key('crypto_wallet_detail_title_text'),
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                ),
              ),
              if (data.asset != null || data.network.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    data.network.isNotEmpty
                        ? data.network
                        : (data.asset?.displayName ?? ''),
                    key: const Key(
                      'crypto_wallet_detail_network_text',
                    ),
                    style: const TextStyle(
                      color: Color(0xFFB4B4B4),
                      fontSize: 12,
                    ),
                  ),
                ),
              const SizedBox(height: 14),
              
              Container(
                key: const Key('crypto_wallet_detail_address_panel'),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF262626),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white12),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Public address',
                      style: TextStyle(
                        color: Color(0xFFB4B4B4),
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.6,
                      ),
                    ),
                    const SizedBox(height: 4),
                    SelectableText(
                      data.walletAddress.isEmpty
                          ? '(not available)'
                          : data.walletAddress,
                      key: const Key(
                        'crypto_wallet_detail_address_text',
                      ),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12.5,
                        fontFamily: 'monospace',
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              if (data.note.isNotEmpty) ...[
                const SizedBox(height: 12),
                Container(
                  key: const Key('crypto_wallet_detail_note_panel'),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF262626),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.white10),
                  ),
                  child: Text(
                    data.note,
                    style: const TextStyle(
                      color: Color(0xFFE0E0E0),
                      fontSize: 12.5,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 14),
              
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (data.walletAddress.isNotEmpty)
                    OutlinedButton.icon(
                      key: const Key(
                        'crypto_wallet_detail_copy_button',
                      ),
                      onPressed: () => _copy(context),
                      icon: const Icon(Icons.copy_outlined,
                          size: 16),
                      label: const Text(kCryptoCopyAddressLabel),
                    ),
                  if (onShowQR != null
                      && data.walletAddress.isNotEmpty)
                    OutlinedButton.icon(
                      key: const Key(
                        'crypto_wallet_detail_show_qr_button',
                      ),
                      onPressed: () {
                        onShowQR!(record);
                      },
                      icon: const Icon(Icons.qr_code_2, size: 16),
                      label: const Text(kCryptoShowReceiveQRLabel),
                    ),
                  if (onUpdate != null)
                    OutlinedButton.icon(
                      key: const Key(
                        'crypto_wallet_detail_edit_button',
                      ),
                      onPressed: () => _edit(context),
                      icon: const Icon(Icons.edit_outlined,
                          size: 16),
                      label: const Text(kCryptoEditDetailLabel),
                    ),
                  if (onDelete != null)
                    OutlinedButton.icon(
                      key: const Key(
                        'crypto_wallet_detail_delete_button',
                      ),
                      onPressed: () => _delete(context),
                      icon: const Icon(Icons.delete_outline,
                          size: 16,
                          color: Color(0xFFE57373)),
                      label: const Text(
                        kCryptoDeleteDetailLabel,
                        style: TextStyle(color: Color(0xFFE57373)),
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key('crypto_wallet_detail_close_button'),
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    );
  }
}


const String kCryptoBackupRevealPanelTitle = 'Encrypted backup saved';


const String kCryptoBackupRevealPanelBody =
    'Your seed phrase, private key, or recovery phrase is stored '
    'encrypted. Reveal only when you are in a private place.';


const String kCryptoRevealSecretButtonLabel = 'Reveal secret';


const String kCryptoRevealWarningTitle = 'Reveal sensitive backup';


const String kCryptoRevealWarningBodyA =
    'Anyone with this phrase or key can control the wallet.';
const String kCryptoRevealWarningBodyB =
    'Only reveal this in a private place. VaultAI will never use '
    'this secret to check balances or create transactions.';

const String kCryptoRevealWarningCancelLabel = 'Cancel';
const String kCryptoRevealWarningContinueLabel =
    'I understand — continue';


const String kCryptoRevealPinDialogTitle = 'Enter your PIN';
const String kCryptoRevealPinFieldLabel = 'PIN';
const String kCryptoRevealPinSubmitLabel = 'Reveal';
const String kCryptoRevealPinCancelLabel = 'Cancel';


const String kCryptoRevealedPanelHeader = 'Revealed secret';
const String kCryptoRevealedPanelWarning =
    'Anyone with this value can control the wallet. Hide it when '
    'you are done.';
const String kCryptoCopySecretButtonLabel = 'Copy secret';
const String kCryptoHideSecretButtonLabel = 'Hide';
const String kCryptoCopySecretConfirmTitle =
    'Copy this secret to clipboard?';
const String kCryptoCopySecretConfirmBody =
    'Anyone with clipboard access may be able to read it.';
const String kCryptoCopySecretConfirmCancel = 'Cancel';
const String kCryptoCopySecretConfirmCopy = 'Copy';
const String kCryptoCopySecretDoneToast =
    'Secret copied to clipboard';
const String kCryptoRevealPinFailedMessage =
    'PIN verification failed.';


Future<void> showCryptoSensitiveBackupDetailDialog(
  BuildContext context, {
  required Map<String, dynamic> record,
  required Map<String, dynamic>? detail,
  Future<void> Function(
    Map<String, dynamic> record,
    CryptoBackupMetadataEdit edits,
  )? onUpdateMetadata,
  Future<void> Function(Map<String, dynamic> record)? onDelete,
  Future<Map<String, dynamic>> Function(
    Map<String, dynamic> record,
    String pin,
  )? onReveal,
}) async {
  await showDialog<void>(
    context: context,
    barrierDismissible: onReveal == null,
    builder: (ctx) => _CryptoSensitiveBackupDetailDialog(
      record: record,
      detail: detail,
      onUpdateMetadata: onUpdateMetadata,
      onDelete: onDelete,
      onReveal: onReveal,
    ),
  );
}


class _CryptoSensitiveBackupDetailDialog extends StatefulWidget {
  final Map<String, dynamic> record;
  final Map<String, dynamic>? detail;
  final Future<void> Function(
    Map<String, dynamic> record,
    CryptoBackupMetadataEdit edits,
  )? onUpdateMetadata;
  final Future<void> Function(Map<String, dynamic> record)? onDelete;
  final Future<Map<String, dynamic>> Function(
    Map<String, dynamic> record,
    String pin,
  )? onReveal;
  const _CryptoSensitiveBackupDetailDialog({
    required this.record,
    required this.detail,
    this.onUpdateMetadata,
    this.onDelete,
    this.onReveal,
  });

  @override
  State<_CryptoSensitiveBackupDetailDialog> createState() =>
      _CryptoSensitiveBackupDetailDialogState();
}


class _CryptoSensitiveBackupDetailDialogState
    extends State<_CryptoSensitiveBackupDetailDialog> {
  
  
  String? _revealedSecret;
  String? _revealedSecretType;

  @override
  void dispose() {
    
    
    _revealedSecret     = null;
    _revealedSecretType = null;
    super.dispose();
  }

  String _str(Map? m, String k, [String fb = '']) {
    if (m == null) return fb;
    final raw = m[k];
    return raw is String ? raw : fb;
  }

  String _secretTypeLabel(String id) {
    for (final s in kCryptoSecretTypes) {
      if (s.id == id) return s.displayName;
    }
    return id.isEmpty ? '(unknown)' : id;
  }

  Future<void> _onRevealPressed(BuildContext context) async {
    if (widget.onReveal == null) return;
    
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        key: const Key('crypto_backup_reveal_warning_dialog'),
        backgroundColor: const Color(0xFF1F1F1F),
        title: const Text(
          kCryptoRevealWarningTitle,
          key: Key('crypto_backup_reveal_warning_title'),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: const [
            Text(
              kCryptoRevealWarningBodyA,
              key: Key('crypto_backup_reveal_warning_body_a'),
              style: TextStyle(
                color: Color(0xFFE0E0E0),
                fontSize: 13.5,
                height: 1.4,
                fontWeight: FontWeight.w600,
              ),
            ),
            SizedBox(height: 10),
            Text(
              kCryptoRevealWarningBodyB,
              key: Key('crypto_backup_reveal_warning_body_b'),
              style: TextStyle(
                color: Color(0xFFB4B4B4),
                fontSize: 12.5,
                height: 1.4,
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            key: const Key(
              'crypto_backup_reveal_warning_cancel',
            ),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text(kCryptoRevealWarningCancelLabel),
          ),
          ElevatedButton(
            key: const Key(
              'crypto_backup_reveal_warning_continue',
            ),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text(kCryptoRevealWarningContinueLabel),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    if (!context.mounted) return;

    
    final revealResult = await showDialog<Map<String, dynamic>>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => _CryptoRevealPinDialog(
        onSubmit: (pin) => widget.onReveal!(widget.record, pin),
      ),
    );
    if (revealResult == null) return;
    final secret = revealResult['secretValue'];
    final type   = revealResult['secretType'];
    if (secret is String && secret.isNotEmpty && type is String) {
      if (!mounted) return;
      setState(() {
        _revealedSecret     = secret;
        _revealedSecretType = type;
      });
    }
  }

  void _hide() {
    setState(() {
      _revealedSecret     = null;
      _revealedSecretType = null;
    });
  }

  Future<void> _copySecret(BuildContext context) async {
    final secret = _revealedSecret;
    if (secret == null || secret.isEmpty) return;
    
    final ok = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        key: const Key('crypto_backup_copy_secret_confirm_dialog'),
        backgroundColor: const Color(0xFF1F1F1F),
        title: const Text(
          kCryptoCopySecretConfirmTitle,
          key: Key('crypto_backup_copy_secret_confirm_title'),
        ),
        content: const Text(
          kCryptoCopySecretConfirmBody,
          key: Key('crypto_backup_copy_secret_confirm_body'),
          style: TextStyle(
            color: Color(0xFFB4B4B4),
            fontSize: 13,
            height: 1.4,
          ),
        ),
        actions: [
          TextButton(
            key: const Key(
              'crypto_backup_copy_secret_confirm_cancel',
            ),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text(kCryptoCopySecretConfirmCancel),
          ),
          ElevatedButton(
            key: const Key(
              'crypto_backup_copy_secret_confirm_copy',
            ),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text(kCryptoCopySecretConfirmCopy),
          ),
        ],
      ),
    );
    if (ok != true) return;
    
    await Clipboard.setData(ClipboardData(text: secret));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      key: Key('crypto_backup_copy_secret_toast'),
      content: Text(kCryptoCopySecretDoneToast),
      duration: Duration(seconds: 2),
    ));
  }

  Future<void> _edit(BuildContext context) async {
    if (widget.onUpdateMetadata == null) return;
    final fields = (widget.detail?['fields'] is Map)
        ? widget.detail!['fields'] as Map<String, dynamic>
        : <String, dynamic>{};
    CryptoAsset? asset;
    final assetCode = _str(fields, 'asset');
    if (assetCode.isNotEmpty) {
      asset = cryptoAssetById(assetCode.toLowerCase())
          ?? cryptoAssetFromNetwork(assetCode);
    }
    asset ??= cryptoAssetFromNetwork(_str(fields, 'network'));
    CryptoWalletLabel? initialLabel;
    final labelStr = _str(fields, 'wallet_label');
    for (final l in kCryptoWalletLabels) {
      if (l.displayName.toLowerCase() == labelStr.toLowerCase()) {
        initialLabel = l;
        break;
      }
    }
    final note = _str(widget.detail, 'notes').isNotEmpty
        ? _str(widget.detail, 'notes')
        : _str(fields, 'note');
    final result = await showDialog<CryptoBackupMetadataEdit>(
      context: context,
      builder: (ctx) => _EditBackupMetadataDialog(
        initialAsset: asset,
        initialLabel: initialLabel,
        initialNote: note,
        onSave: (edits) =>
            widget.onUpdateMetadata!(widget.record, edits),
      ),
    );
    if (result != null && context.mounted) {
      
      
      Navigator.of(context).pop();
    }
  }

  Future<void> _delete(BuildContext context) async {
    if (widget.onDelete == null) return;
    final confirmed = await showCryptoDeleteBackupConfirmationDialog(
      context,
      onConfirm: () => widget.onDelete!(widget.record),
    );
    if (confirmed == true && context.mounted) {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final fields = (widget.detail?['fields'] is Map)
        ? widget.detail!['fields'] as Map<String, dynamic>
        : <String, dynamic>{};
    final title = _str(widget.detail, 'service').isNotEmpty
        ? _str(widget.detail, 'service')
        : _str(widget.record, 'title', 'Sensitive backup');
    final walletLabel = _str(fields, 'wallet_label');
    final asset       = _str(fields, 'asset');
    final network     = _str(fields, 'network');
    final secretType  = _str(fields, 'secret_type');
    final note        = _str(widget.detail, 'notes').isNotEmpty
        ? _str(widget.detail, 'notes')
        : _str(fields, 'note');
    final revealEnabled = widget.onReveal != null;
    return AlertDialog(
      key: const Key('crypto_backup_detail_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      title: const Text(
        kCryptoBackupDetailTitle,
        key: Key('crypto_backup_detail_dialog_title'),
      ),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                key: const Key('crypto_backup_detail_title_text'),
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 4),
              
              _DetailMetadataRow(
                keyName: 'crypto_backup_detail_label',
                label:   'Wallet label',
                value:   walletLabel.isEmpty ? '(unknown)' : walletLabel,
              ),
              _DetailMetadataRow(
                keyName: 'crypto_backup_detail_asset',
                label:   'Asset / network',
                value:   (asset.isEmpty && network.isEmpty)
                    ? '(unknown)'
                    : [
                        if (asset.isNotEmpty) asset,
                        if (network.isNotEmpty) network,
                      ].join(' • '),
              ),
              _DetailMetadataRow(
                keyName: 'crypto_backup_detail_secret_type',
                label:   'Backup type',
                value:   _secretTypeLabel(secretType),
              ),
              if (note.isNotEmpty)
                _DetailMetadataRow(
                  keyName: 'crypto_backup_detail_note',
                  label:   'Note',
                  value:   note,
                ),
              const SizedBox(height: 14),
              
              if (_revealedSecret != null)
                _CryptoRevealedSecretPanel(
                  secret:     _revealedSecret!,
                  secretType: _revealedSecretType ?? secretType,
                  onCopy:     () => _copySecret(context),
                  onHide:     _hide,
                )
              else if (revealEnabled)
                _CryptoBackupRevealCTA(
                  onReveal: () => _onRevealPressed(context),
                )
              else
                Container(
                  key: const Key(
                    'crypto_backup_detail_reveal_notice',
                  ),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF262626),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.white10),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Icon(Icons.lock_outline,
                          size: 16, color: Color(0xFFB4B4B4)),
                      SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          kCryptoBackupRevealNotice,
                          style: TextStyle(
                            color: Color(0xFFB4B4B4),
                            fontSize: 12.5,
                            height: 1.4,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 14),
              
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (widget.onUpdateMetadata != null)
                    OutlinedButton.icon(
                      key: const Key(
                        'crypto_backup_detail_edit_button',
                      ),
                      onPressed: () => _edit(context),
                      icon: const Icon(Icons.edit_outlined,
                          size: 16),
                      label: Text(
                        AppLocalizations.of(context).cryptoLiteEditMetadata,
                      ),
                    ),
                  if (widget.onDelete != null)
                    OutlinedButton.icon(
                      key: const Key(
                        'crypto_backup_detail_delete_button',
                      ),
                      onPressed: () => _delete(context),
                      icon: const Icon(Icons.delete_outline,
                          size: 16,
                          color: Color(0xFFE57373)),
                      label: const Text(
                        'Delete backup',
                        style: TextStyle(color: Color(0xFFE57373)),
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key('crypto_backup_detail_close_button'),
          onPressed: () {
            
            
            _revealedSecret     = null;
            _revealedSecretType = null;
            Navigator.of(context).pop();
          },
          child: const Text('Close'),
        ),
      ],
    );
  }
}


class _CryptoBackupRevealCTA extends StatelessWidget {
  final VoidCallback onReveal;
  const _CryptoBackupRevealCTA({required this.onReveal});

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('crypto_backup_detail_reveal_cta'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: const [
              Icon(Icons.lock_outline,
                  size: 16, color: Color(0xFFB4B4B4)),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  kCryptoBackupRevealPanelTitle,
                  key: Key('crypto_backup_detail_reveal_cta_title'),
                  style: TextStyle(
                    color: Color(0xFFE0E0E0),
                    fontSize: 13.5,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            kCryptoBackupRevealPanelBody,
            key: Key('crypto_backup_detail_reveal_cta_body'),
            style: TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 12.5,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 10),
          ElevatedButton.icon(
            key: const Key('crypto_backup_detail_reveal_button'),
            onPressed: onReveal,
            icon: const Icon(Icons.visibility_outlined, size: 16),
            label: const Text(kCryptoRevealSecretButtonLabel),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFFFB300),
              foregroundColor: Colors.black,
            ),
          ),
        ],
      ),
    );
  }
}


class _CryptoRevealedSecretPanel extends StatelessWidget {
  final String secret;
  final String secretType;
  final VoidCallback onCopy;
  final VoidCallback onHide;
  const _CryptoRevealedSecretPanel({
    required this.secret,
    required this.secretType,
    required this.onCopy,
    required this.onHide,
  });

  String _secretTypeLabel() {
    for (final s in kCryptoSecretTypes) {
      if (s.id == secretType) return s.displayName;
    }
    return 'Secret';
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('crypto_backup_revealed_panel'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF2F2418),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: const Color(0xFFFFB300).withValues(alpha: 0.45),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.warning_amber_outlined,
                  size: 16, color: Color(0xFFFFB300)),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  '${_secretTypeLabel()} (${kCryptoRevealedPanelHeader})',
                  key: const Key(
                    'crypto_backup_revealed_panel_header_text',
                  ),
                  style: const TextStyle(
                    color: Color(0xFFEEDDB4),
                    fontSize: 12.5,
                    fontWeight: FontWeight.w800,
                  ),
                  softWrap: true,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            kCryptoRevealedPanelWarning,
            key: Key('crypto_backup_revealed_panel_warning_text'),
            style: TextStyle(
              color: Color(0xFFEEDDB4),
              fontSize: 12,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: const Color(0xFF1F1F1F),
              borderRadius: BorderRadius.circular(8),
            ),
            child: SelectableText(
              secret,
              key: const Key('crypto_backup_revealed_panel_secret_text'),
              style: const TextStyle(
                color: Colors.white,
                fontSize: 12.5,
                fontFamily: 'monospace',
                height: 1.45,
              ),
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                key: const Key(
                  'crypto_backup_revealed_panel_copy_button',
                ),
                onPressed: onCopy,
                icon: const Icon(Icons.copy_outlined, size: 16),
                label: const Text(kCryptoCopySecretButtonLabel),
              ),
              OutlinedButton.icon(
                key: const Key(
                  'crypto_backup_revealed_panel_hide_button',
                ),
                onPressed: onHide,
                icon: const Icon(Icons.visibility_off_outlined,
                    size: 16),
                label: const Text(kCryptoHideSecretButtonLabel),
              ),
            ],
          ),
        ],
      ),
    );
  }
}


class _CryptoRevealPinDialog extends StatefulWidget {
  final Future<Map<String, dynamic>> Function(String pin) onSubmit;
  const _CryptoRevealPinDialog({required this.onSubmit});

  @override
  State<_CryptoRevealPinDialog> createState() =>
      _CryptoRevealPinDialogState();
}


class _CryptoRevealPinDialogState
    extends State<_CryptoRevealPinDialog> {
  late final TextEditingController _pinCtrl;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _pinCtrl = TextEditingController();
  }

  @override
  void dispose() {
    
    _pinCtrl.text = '';
    _pinCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy) return;
    final pin = _pinCtrl.text;
    if (pin.isEmpty) return;
    setState(() {
      _busy  = true;
      _error = null;
    });
    Map<String, dynamic>? result;
    try {
      result = await widget.onSubmit(pin);
    } catch (_) {
      
      
      if (!mounted) return;
      setState(() {
        _busy  = false;
        _error = kCryptoRevealPinFailedMessage;
        
        
        _pinCtrl.text = '';
      });
      return;
    }
    if (!mounted) return;
    Navigator.of(context).pop(result);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const Key('crypto_backup_reveal_pin_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      title: const Text(
        kCryptoRevealPinDialogTitle,
        key: Key('crypto_backup_reveal_pin_dialog_title'),
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            key: const Key('crypto_backup_reveal_pin_field'),
            controller: _pinCtrl,
            obscureText: true,
            keyboardType: TextInputType.number,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: kCryptoRevealPinFieldLabel,
            ),
            onSubmitted: (_) => _submit(),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(
              _error!,
              key: const Key('crypto_backup_reveal_pin_error_text'),
              style: const TextStyle(
                color: Color(0xFFE57373),
                fontSize: 12.5,
              ),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          key: const Key('crypto_backup_reveal_pin_cancel_button'),
          onPressed: _busy ? null : () => Navigator.of(context).pop(),
          child: const Text(kCryptoRevealPinCancelLabel),
        ),
        ElevatedButton(
          key: const Key('crypto_backup_reveal_pin_submit_button'),
          onPressed: _busy ? null : _submit,
          child: _busy
              ? const SizedBox(
                  height: 16, width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text(kCryptoRevealPinSubmitLabel),
        ),
      ],
    );
  }
}


class _DetailMetadataRow extends StatelessWidget {
  final String keyName;
  final String label;
  final String value;
  const _DetailMetadataRow({
    required this.keyName,
    required this.label,
    required this.value,
  });
  @override
  Widget build(BuildContext context) {
    return Padding(
      key: Key(keyName),
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.6,
            ),
          ),
          Text(
            value,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }
}


Future<bool?> showCryptoDeleteWalletConfirmationDialog(
  BuildContext context, {
  required Future<void> Function() onConfirm,
}) {
  return showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => _CryptoDeleteConfirmationDialog(
      keyName:  'crypto_delete_wallet_confirm_dialog',
      title:    kCryptoDeleteWalletTitle,
      body:     kCryptoDeleteWalletBody,
      cancelLabel: kCryptoDeleteWalletCancel,
      confirmLabel: kCryptoDeleteWalletConfirm,
      onConfirm: onConfirm,
    ),
  );
}


Future<bool?> showCryptoDeleteBackupConfirmationDialog(
  BuildContext context, {
  required Future<void> Function() onConfirm,
}) {
  return showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => _CryptoDeleteConfirmationDialog(
      keyName:  'crypto_delete_backup_confirm_dialog',
      title:    kCryptoDeleteBackupTitle,
      body:     kCryptoDeleteBackupBody,
      cancelLabel: kCryptoDeleteBackupCancel,
      confirmLabel: kCryptoDeleteBackupConfirm,
      onConfirm: onConfirm,
    ),
  );
}


class _CryptoDeleteConfirmationDialog extends StatefulWidget {
  final String keyName;
  final String title;
  final String body;
  final String cancelLabel;
  final String confirmLabel;
  final Future<void> Function() onConfirm;
  const _CryptoDeleteConfirmationDialog({
    required this.keyName,
    required this.title,
    required this.body,
    required this.cancelLabel,
    required this.confirmLabel,
    required this.onConfirm,
  });

  @override
  State<_CryptoDeleteConfirmationDialog> createState() =>
      _CryptoDeleteConfirmationDialogState();
}


class _CryptoDeleteConfirmationDialogState
    extends State<_CryptoDeleteConfirmationDialog> {
  bool _deleting = false;
  String? _error;

  Future<void> _onConfirm() async {
    if (_deleting) return;
    setState(() {
      _deleting = true;
      _error    = null;
    });
    try {
      await widget.onConfirm();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _deleting = false;
        _error    = _AddCryptoWalletDialogState._formatSaveError(e);
      });
      return;
    }
    if (!mounted) return;
    Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: Key(widget.keyName),
      backgroundColor: const Color(0xFF1F1F1F),
      title: Text(
        widget.title,
        key: Key('${widget.keyName}_title'),
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            widget.body,
            key: Key('${widget.keyName}_body'),
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 13,
              height: 1.45,
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFF3A1F1F),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFE57373)),
              ),
              child: Text(
                _error!,
                style: const TextStyle(
                  color: Color(0xFFE57373), fontSize: 12.5,
                ),
              ),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          key: Key('${widget.keyName}_cancel'),
          onPressed: _deleting
              ? null
              : () => Navigator.of(context).pop(false),
          child: Text(widget.cancelLabel),
        ),
        ElevatedButton(
          key: Key('${widget.keyName}_confirm'),
          onPressed: _deleting ? null : _onConfirm,
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFFE57373),
            foregroundColor: Colors.white,
          ),
          child: _deleting
              ? const SizedBox(
                  height: 16, width: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2, color: Colors.white,
                  ),
                )
              : Text(widget.confirmLabel),
        ),
      ],
    );
  }
}


class _EditBackupMetadataDialog extends StatefulWidget {
  final CryptoAsset? initialAsset;
  final CryptoWalletLabel? initialLabel;
  final String initialNote;
  final Future<void> Function(CryptoBackupMetadataEdit edits) onSave;
  const _EditBackupMetadataDialog({
    required this.initialAsset,
    required this.initialLabel,
    required this.initialNote,
    required this.onSave,
  });
  @override
  State<_EditBackupMetadataDialog> createState() =>
      _EditBackupMetadataDialogState();
}


class _EditBackupMetadataDialogState
    extends State<_EditBackupMetadataDialog> {
  late CryptoAsset? _asset;
  late CryptoWalletLabel? _label;
  late final TextEditingController _noteCtrl;
  String? _labelError;
  String? _saveError;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _asset    = widget.initialAsset;
    _label    = widget.initialLabel;
    _noteCtrl = TextEditingController(text: widget.initialNote);
  }

  @override
  void dispose() {
    _noteCtrl.dispose();
    super.dispose();
  }

  Future<void> _onSave() async {
    if (_saving) return;
    setState(() {
      _labelError = _label == null
          ? kCryptoSensitiveBackupValidationLabel : null;
      _saveError = null;
    });
    if (_labelError != null) return;
    final edits = CryptoBackupMetadataEdit(
      asset: _asset,
      label: _label!,
      note: _noteCtrl.text.trim(),
    );
    setState(() => _saving = true);
    try {
      await widget.onSave(edits);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _saveError = _AddCryptoWalletDialogState._formatSaveError(e);
      });
      return;
    }
    if (!mounted) return;
    Navigator.of(context).pop(edits);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const Key('crypto_backup_edit_metadata_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      title: Text(
        AppLocalizations.of(context).cryptoLiteEditBackupMetadata,
      ),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DropdownButtonFormField<CryptoWalletLabel>(
                key: const Key(
                  'crypto_backup_edit_label_dropdown',
                ),
                initialValue: _label,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: kCryptoSensitiveBackupLabelField,
                  errorText: _labelError,
                ),
                items: kCryptoWalletLabels.map((l) {
                  return DropdownMenuItem<CryptoWalletLabel>(
                    value: l,
                    child: Text(l.displayName),
                  );
                }).toList(growable: false),
                onChanged: (v) => setState(() {
                  _label = v;
                  _labelError = null;
                }),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<CryptoAsset>(
                key: const Key(
                  'crypto_backup_edit_asset_dropdown',
                ),
                initialValue: _asset,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: kCryptoSensitiveBackupAssetField,
                ),
                items: kCryptoAssets.map((a) {
                  return DropdownMenuItem<CryptoAsset>(
                    value: a,
                    child: Text(a.displayName),
                  );
                }).toList(growable: false),
                onChanged: (v) => setState(() => _asset = v),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key(
                  'crypto_backup_edit_note_field',
                ),
                controller: _noteCtrl,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: kCryptoSensitiveBackupNoteField,
                ),
              ),
              if (_saveError != null) ...[
                const SizedBox(height: 12),
                Container(
                  key: const Key(
                    'crypto_backup_edit_save_error',
                  ),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF3A1F1F),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: const Color(0xFFE57373),
                    ),
                  ),
                  child: Text(
                    _saveError!,
                    style: const TextStyle(
                      color: Color(0xFFE57373), fontSize: 12.5,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key('crypto_backup_edit_cancel_button'),
          onPressed: _saving
              ? null
              : () => Navigator.of(context).pop(),
          child: Text(AppLocalizations.of(context).commonCancel),
        ),
        ElevatedButton(
          key: const Key('crypto_backup_edit_save_button'),
          onPressed: _saving ? null : _onSave,
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF10A37F),
            foregroundColor: Colors.white,
          ),
          child: _saving
              ? const SizedBox(
                  height: 16, width: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2, color: Colors.white,
                  ),
                )
              : const Text('Save'),
        ),
      ],
    );
  }
}


class _ActionButton extends StatelessWidget {
  const _ActionButton({
    required this.keyName,
    required this.icon,
    required this.label,
    required this.onPressed,
  });
  final String keyName;
  final IconData icon;
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return ElevatedButton.icon(
      key: Key(keyName),
      onPressed: onPressed,
      icon: Icon(icon, size: 18),
      label: Text(label),
      style: ElevatedButton.styleFrom(
        backgroundColor: const Color(0xFF10A37F),
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(
          horizontal: 16, vertical: 12,
        ),
      ),
    );
  }
}


class _SearchBar extends StatelessWidget {
  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  const _SearchBar({required this.controller, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white12),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          const Icon(
            Icons.search,
            size: 18,
            color: Color(0xFF8E8E8E),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              key: const Key('crypto_lite_search_field'),
              controller: controller,
              onChanged: onChanged,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
              ),
              decoration: const InputDecoration(
                hintText: kCryptoLiteSearchHint,
                hintStyle: TextStyle(
                  color: Color(0xFF8E8E8E),
                  fontSize: 13,
                ),
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
              ),
            ),
          ),
          if (controller.text.isNotEmpty)
            IconButton(
              key: const Key('crypto_lite_search_clear'),
              tooltip: 'Clear search',
              icon: const Icon(
                Icons.close,
                size: 16,
                color: Color(0xFF8E8E8E),
              ),
              onPressed: () {
                controller.clear();
                onChanged('');
              },
            ),
        ],
      ),
    );
  }
}


class _CryptoChipStrip extends StatelessWidget {
  final CryptoFilterChip active;
  final ValueChanged<CryptoFilterChip> onSelect;

  const _CryptoChipStrip({required this.active, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    return Wrap(
      key: const Key('crypto_lite_chip_strip'),
      spacing: 8,
      runSpacing: 8,
      children: kCryptoFilterChips.map((c) {
        final selected = c.id == active.id;
        return ChoiceChip(
          key: Key('crypto_lite_chip_${c.id}'),
          showCheckmark: false,
          avatar: Icon(
            c.icon,
            size: 16,
            color: selected
                ? const Color(0xFF10A37F)
                : const Color(0xFFB4B4B4),
          ),
          label: Text(c.label),
          labelStyle: TextStyle(
            color: selected
                ? const Color(0xFF10A37F)
                : const Color(0xFFB4B4B4),
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
          selected: selected,
          backgroundColor: const Color(0xFF1F1F1F),
          selectedColor: const Color(0xFF10A37F).withValues(alpha: 0.18),
          side: BorderSide(
            color: selected
                ? const Color(0xFF10A37F).withValues(alpha: 0.45)
                : Colors.white12,
          ),
          onSelected: (v) {
            if (v) onSelect(c);
          },
        );
      }).toList(growable: false),
    );
  }
}


class _CryptoFilterEmptyState extends StatelessWidget {
  final String query;
  final CryptoFilterChip chip;

  const _CryptoFilterEmptyState({required this.query, required this.chip});

  @override
  Widget build(BuildContext context) {
    final isAll = chip.id == kCryptoChipAll.id;
    final pieces = <String>[];
    if (query.trim().isNotEmpty) {
      pieces.add('"${query.trim()}"');
    }
    if (!isAll) {
      pieces.add(chip.label);
    }
    final scope = pieces.isEmpty ? 'in this view' : pieces.join(' • ');
    return Column(
      key: const Key('crypto_lite_filter_empty_state'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'No matching crypto records',
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            color: Colors.white,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          'Nothing matches $scope. Adjust the search or pick a '
          'different filter chip.',
          style: const TextStyle(
            color: Color(0xFFB4B4B4),
            fontSize: 13,
            height: 1.5,
          ),
        ),
      ],
    );
  }
}


class _CryptoRecordCard extends StatelessWidget {
  const _CryptoRecordCard({
    required this.record,
    this.onView,
    this.onEdit,
    this.onDelete,
    this.onCopyValue,
    this.onShowQR,
  });
  final Map<String, dynamic> record;
  final void Function(Map<String, dynamic> record)? onView;
  final void Function(Map<String, dynamic> record)? onEdit;
  final void Function(Map<String, dynamic> record)? onDelete;
  final void Function(Map<String, dynamic> record)? onCopyValue;
  final void Function(Map<String, dynamic> record)? onShowQR;

  String _str(String key, [String fallback = '']) {
    final raw = record[key];
    if (raw is String) return raw;
    if (raw is Map) {
      final inner = raw[key];
      if (inner is String) return inner;
    }
    return fallback;
  }

  String _typeKey() {
    final raw = record['type'] ?? record['item_type'];
    return raw is String ? raw : '';
  }

  String _idKey() {
    final raw = record['item_id'] ?? record['id'] ?? record['title'];
    return raw is String ? raw : '';
  }

  @override
  Widget build(BuildContext context) {
    final title         = _str('title', 'Saved crypto record');
    final categoryLabel = _str('category_label', 'Crypto record');
    final type          = _typeKey();
    final id            = _idKey();
    final preview = record['preview'];
    String? networkChip;
    String? maskedPreview;
    if (preview is Map) {
      networkChip = preview['network'] is String
          ? preview['network'] as String : null;
      for (final key in const [
        'wallet_address_mask',
        'seed_phrase_mask',
        'private_key_mask',
        'recovery_phrase_mask',
        'crypto_note_mask',
        'transaction_note_mask',
        'exchange_note_mask',
        'hardware_wallet_note_mask',
      ]) {
        if (preview[key] is String) {
          maskedPreview = preview[key] as String;
          break;
        }
      }
    }
    final keySuffix = id.isNotEmpty ? id : '${type}_$title';
    return Padding(
      key: Key('crypto_lite_card_$keySuffix'),
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(
                Icons.account_balance_wallet_outlined,
                size: 18, color: Color(0xFFB4B4B4),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontWeight: FontWeight.w700, fontSize: 14,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Wrap(
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 6,
                      runSpacing: 4,
                      children: [
                        Text(
                          categoryLabel,
                          style: const TextStyle(
                            color: Color(0xFF888888), fontSize: 12,
                          ),
                        ),
                        if (networkChip != null)
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 6, vertical: 1,
                            ),
                            decoration: BoxDecoration(
                              color: const Color(0xFF10A37F)
                                  .withValues(alpha: 0.16),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              networkChip,
                              style: const TextStyle(
                                color: Color(0xFF10A37F),
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                      ],
                    ),
                    if (maskedPreview != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        maskedPreview,
                        style: const TextStyle(
                          color: Color(0xFFB4B4B4), fontSize: 12,
                          fontFamily: 'monospace',
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          if (onView != null
              || onEdit != null
              || onDelete != null
              || onCopyValue != null
              || (onShowQR != null && type == 'crypto_wallet_address')) ...[
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.only(left: 28),
              child: Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  if (onView != null)
                    _CardActionButton(
                      keyName: 'crypto_card_view_$keySuffix',
                      label: 'View',
                      icon: Icons.visibility_outlined,
                      onPressed: () => onView!(record),
                    ),
                  
                  
                  if (onShowQR != null && type == 'crypto_wallet_address')
                    _CardActionButton(
                      keyName: 'crypto_card_show_qr_$keySuffix',
                      label: 'Show QR',
                      icon: Icons.qr_code_2,
                      onPressed: () => onShowQR!(record),
                    ),
                  if (onCopyValue != null)
                    _CardActionButton(
                      keyName: 'crypto_card_copy_$keySuffix',
                      label: 'Copy',
                      icon: Icons.copy_outlined,
                      onPressed: () => onCopyValue!(record),
                    ),
                  if (onEdit != null)
                    _CardActionButton(
                      keyName: 'crypto_card_edit_$keySuffix',
                      label: 'Edit',
                      icon: Icons.edit_outlined,
                      onPressed: () => onEdit!(record),
                    ),
                  if (onDelete != null)
                    _CardActionButton(
                      keyName: 'crypto_card_delete_$keySuffix',
                      label: 'Delete',
                      icon: Icons.delete_outline,
                      onPressed: () => onDelete!(record),
                      destructive: true,
                    ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}


class _CardActionButton extends StatelessWidget {
  const _CardActionButton({
    required this.keyName,
    required this.label,
    required this.icon,
    required this.onPressed,
    this.destructive = false,
  });

  final String keyName;
  final String label;
  final IconData icon;
  final VoidCallback onPressed;
  final bool destructive;

  @override
  Widget build(BuildContext context) {
    final fg = destructive
        ? const Color(0xFFE57373)
        : const Color(0xFFB4B4B4);
    return TextButton.icon(
      key: Key(keyName),
      onPressed: onPressed,
      icon: Icon(icon, size: 14, color: fg),
      label: Text(
        label,
        style: TextStyle(
          color: fg,
          fontSize: 12,
          fontWeight: FontWeight.w600,
        ),
      ),
      style: TextButton.styleFrom(
        padding: const EdgeInsets.symmetric(
          horizontal: 8, vertical: 4,
        ),
        minimumSize: const Size(0, 28),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
    );
  }
}


Future<bool?> showCryptoVaultStrongWarningDialog(
  BuildContext context, {
  String title = 'Strong warning',
  String? bodyExtra,
}) {
  return showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      key: const Key('crypto_vault_strong_warning_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      title: Text(
        title,
        key: const Key('crypto_vault_strong_warning_title'),
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            kCryptoVaultStrongWarning,
            key: Key('crypto_vault_strong_warning_body'),
          ),
          if (bodyExtra != null) ...[
            const SizedBox(height: 12),
            Text(bodyExtra),
          ],
        ],
      ),
      actions: [
        TextButton(
          key: const Key('crypto_vault_strong_warning_cancel'),
          onPressed: () => Navigator.of(ctx).pop(false),
          child: Text(AppLocalizations.of(ctx).commonCancel),
        ),
        ElevatedButton(
          key: const Key('crypto_vault_strong_warning_continue'),
          onPressed: () => Navigator.of(ctx).pop(true),
          child: const Text('I understand — continue'),
        ),
      ],
    ),
  );
}
