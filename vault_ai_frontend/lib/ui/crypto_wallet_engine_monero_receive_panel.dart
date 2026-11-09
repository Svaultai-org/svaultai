import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../api_client.dart';
import '../services/crypto_wallet_features.dart';
import '../services/monero_wallet.dart';
import '../services/wallet_v2_active_client.dart';
import 'crypto_wallet_engine_design.dart';

const String kMoneroReceivePanelTitle = 'Receive Monero';
const String kMoneroReceiveNetworkBadge = 'Monero';
const String kMoneroReceiveCopyButtonLabel = 'Copy address';
const String kMoneroReceiveCopyDoneSnackbar = 'Address copied to clipboard';
const String kMoneroReceiveNonCustodialAttestation =
    'Non-custodial: Svaultai never sees your Monero spend or view key. '
    'Your wallet is encrypted with your PIN and stored as ciphertext '
    'only.';
const String kMoneroReceivePrivateAttestation =
    'Non-custodial: Svaultai never sees your Monero spend or view key. '
    'Your wallet backup is encrypted with your private vault key.';
const String kMoneroReceiveBackupMigrationMessage =
    'This existing Monero wallet needs private backup migration before '
    'the new private vault can use it.';
const String kMoneroReceiveAssetWarning =
    'Only send XMR on Monero to this address.';
const String kMoneroReceivePrivacyNote =
    'Monero balance and activity require wallet scanning. Scanning is '
    'not enabled yet.';
const String kMoneroReceiveDisabledMessage =
    'Monero privacy wallet support is planned.';
const String kMoneroReceiveGenerationPendingMessage =
    'Monero wallet setup is pending. Wallet creation requires special '
    'privacy-preserving curve arithmetic that ships in a follow-up '
    'slice. Until then, XMR receive is prepared but no wallet can be '
    'created from this device.';
const String kMoneroReceiveLoadingLabel = 'Loading Monero wallet…';

const String kMoneroReceivePanelKey = 'monero_receive_panel';
const String kMoneroReceivePanelQrKey = 'monero_receive_panel_qr';
const String kMoneroReceivePanelAddressTextKey =
    'monero_receive_panel_address_text';
const String kMoneroReceivePanelCopyBtnKey = 'monero_receive_panel_copy_btn';
const String kMoneroReceivePanelWarningKey = 'monero_receive_panel_warning';
const String kMoneroReceivePanelPrivacyNoteKey =
    'monero_receive_panel_privacy_note';
const String kMoneroReceivePanelDisabledKey = 'monero_receive_panel_disabled';
const String kMoneroReceivePanelMigrationRequiredKey =
    'monero_receive_panel_migration_required';
const String kMoneroReceivePanelGenerationPendingKey =
    'monero_receive_panel_generation_pending';
const String kMoneroReceivePanelRestoreHeightKey =
    'monero_receive_panel_restore_height';
const String kMoneroReceivePanelCreateBtnKey =
    'monero_receive_panel_create_btn';
const String kMoneroReceivePanelCreateFailedKey =
    'monero_receive_panel_create_failed';
const String kMoneroReceivePanelCreateProgressKey =
    'monero_receive_panel_create_progress';
const String kMoneroReceiveCreateButtonLabel = 'Create Monero wallet';
const String kMoneroReceiveCreateBusyLabel =
    'Generating locally on this device…';
const String kMoneroReceiveCreateVaultKeyMissingMessage =
    'Unlock your vault before creating a Monero wallet — the wallet '
    'secret is encrypted with your vault key.';
const String kMoneroReceiveCreateFallbackErrorMessage =
    'Monero wallet creation failed. No wallet was saved.';
const int kMoneroReceiveDefaultRestoreHeight = 3230000;

class CryptoWalletEngineMoneroReceivePanel extends StatefulWidget {
  final String authToken;
  final VaultAIClient client;
  final CryptoWalletFeatures? features;
  final MoneroWalletAdapter walletAdapter;
  final WalletV2ActiveClient? walletV2;
  final Future<String> Function(String plaintext)? encryptForVault;
  final bool Function()? isVaultKeyAvailable;
  final int restoreHeight;

  const CryptoWalletEngineMoneroReceivePanel({
    super.key,
    required this.authToken,
    required this.client,
    this.features,
    this.walletAdapter = const NullMoneroWalletAdapter(),
    this.walletV2,
    this.encryptForVault,
    this.isVaultKeyAvailable,
    this.restoreHeight = kMoneroReceiveDefaultRestoreHeight,
  });

  @override
  State<CryptoWalletEngineMoneroReceivePanel> createState() =>
      _CryptoWalletEngineMoneroReceivePanelState();
}

class _CryptoWalletEngineMoneroReceivePanelState
    extends State<CryptoWalletEngineMoneroReceivePanel> {
  static const _slot = WalletV2AccountSlot('monero', 'monero_mainnet', 'XMR');
  Map<String, dynamic>? _state;
  bool _loading = true;
  bool _creating = false;
  String? _error;
  String? _createFailureMessage;

  @override
  void initState() {
    super.initState();
    _load();
  }

  bool get _xmrEnabled => widget.features?.xmrEnabled ?? true;

  Future<void> _load() async {
    if (!_xmrEnabled) {
      setState(() {
        _state = {'wallet_engine': 'xmr_privacy_wallet_later'};
        _loading = false;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final body = await widget.client.getCryptoWalletReceiveNetwork(
        network: kMoneroNetworkId,
        asset: kMoneroAssetTicker,
        authToken: widget.authToken,
      );
      var resolved = body;
      final walletV2 = widget.walletV2;
      final status = body['wallet_engine'];
      if (walletV2 != null &&
          const {
            'no_account',
            'create_xmr_wallet_first',
            'receive_ready',
          }.contains(status)) {
        final identity = await walletV2.findVerified(_slot);
        int? verifiedRestoreHeight;
        if (identity != null) {
          // A verified list row alone cannot prove the encrypted backup can
          // still be opened or belongs to the displayed receive address.
          final secret = await walletV2.readSigningSecret(identity);
          final parsed = jsonDecode(secret);
          final height =
              parsed is Map<String, dynamic> ? parsed['restoreHeight'] : null;
          if (height is! int || height < 0) {
            throw const FormatException('Invalid Monero restore height');
          }
          verifiedRestoreHeight = height;
        }
        if (status == 'receive_ready') {
          final shownAddress = body['publicAddress']?.toString();
          if (identity == null) {
            if (body['backupStatus'] == 'wallet_v2_encrypted') {
              throw const FormatException('Wallet account verification failed');
            }
            resolved = {...body, 'requiresWalletMigration': true};
          } else if (shownAddress != identity.publicAddress ||
              body['backupStatus'] != 'wallet_v2_encrypted' ||
              body['walletRecordId'] != identity.recordId) {
            throw const FormatException('Conflicting Monero wallet sources');
          } else {
            resolved = {
              ...body,
              'walletRecordId': identity.recordId,
              'backupStatus': 'wallet_v2_encrypted',
              'restoreHeight': verifiedRestoreHeight,
            };
          }
        } else if (identity != null) {
          resolved = {
            'wallet_engine': 'receive_ready',
            'publicAddress': identity.publicAddress,
            'walletLabel': identity.label,
            'walletRecordId': identity.recordId,
            'backupStatus': 'wallet_v2_encrypted',
            'restoreHeight': verifiedRestoreHeight,
            'warning': kMoneroReceiveAssetWarning,
            'privacyNote': kMoneroReceivePrivacyNote,
          };
        }
      }
      if (!mounted ||
          (walletV2 != null && !walletV2.accessIsCurrent())) return;
      setState(() {
        _state = resolved;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _copyAddress(String address) async {
    await Clipboard.setData(ClipboardData(text: address));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text(kMoneroReceiveCopyDoneSnackbar)),
    );
  }

  Future<void> _createWallet() async {
    if (_creating || !widget.walletAdapter.isAvailable) return;
    final walletV2 = widget.walletV2;
    if (walletV2 != null && !walletV2.creationEnabled) {
      setState(() {
        _createFailureMessage = 'Private wallet creation is unavailable.';
      });
      return;
    }
    final encryptForVault = widget.encryptForVault;
    if (walletV2 == null && encryptForVault == null) {
      setState(() {
        _createFailureMessage = kMoneroReceiveCreateVaultKeyMissingMessage;
      });
      return;
    }
    if (widget.isVaultKeyAvailable != null && !widget.isVaultKeyAvailable!()) {
      setState(() {
        _createFailureMessage = kMoneroReceiveCreateVaultKeyMissingMessage;
      });
      return;
    }
    setState(() {
      _creating = true;
      _createFailureMessage = null;
    });
    try {
      if (walletV2 != null) {
        final recovered = await walletV2.recoverPendingNew(_slot);
        if (recovered != null) {
          if (!mounted) return;
          setState(() => _creating = false);
          await _load();
          return;
        }
        // The V2 list cannot prove that an older wallet does not exist.
        // Recheck the legacy receive view before generating a new key.
        final latest = await widget.client.getCryptoWalletReceiveNetwork(
          network: kMoneroNetworkId,
          asset: kMoneroAssetTicker,
          authToken: widget.authToken,
        );
        if (latest['wallet_engine'] == 'receive_ready') {
          throw StateError('An existing Monero wallet needs migration.');
        }
        if (!const {
          'no_account',
          'create_xmr_wallet_first',
        }.contains(latest['wallet_engine'])) {
          throw StateError('Monero wallet status changed.');
        }
        if (!mounted || !walletV2.accessIsCurrent()) {
          throw StateError('Wallet access changed.');
        }
        final generated = await widget.walletAdapter.generatePrivate(
          restoreHeight: widget.restoreHeight,
        );
        if (!mounted || !walletV2.accessIsCurrent()) {
          throw StateError('Wallet access changed.');
        }
        await walletV2.createNew(
          slot: _slot,
          publicAddress: generated.publicAddress,
          label: 'Monero',
          secret: generated.secret,
        );
        if (!mounted) return;
        setState(() => _creating = false);
        await _load();
        return;
      }
      final generated = await widget.walletAdapter.generate(
        restoreHeight: widget.restoreHeight,
        encryptForVault: encryptForVault!,
      );
      await widget.client.createCryptoWalletAccountNetwork(
        network: kMoneroNetworkId,
        asset: kMoneroAssetTicker,
        authToken: widget.authToken,
        walletLabel: 'Monero',
        publicAddress: generated.publicAddress,
        encryptedWalletSecret: generated.encryptedWalletSecretPayload,
        restoreHeight: generated.restoreHeight,
        scannerMode: 'none',
      );
      if (!mounted) return;
      setState(() {
        _creating = false;
      });
      await _load();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _createFailureMessage = kMoneroReceiveCreateFallbackErrorMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return WalletDarkPanelScope(
      child: SingleChildScrollView(
        key: const Key(kMoneroReceivePanelKey),
        child: _buildBody(context),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_loading) {
      return Padding(
        padding: EdgeInsets.all(
          MediaQuery.of(context).size.width < 600 ? 16 : 24,
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(kWalletAccentPrimary),
              ),
            ),
            SizedBox(width: 12),
            Text(
              kMoneroReceiveLoadingLabel,
              style: TextStyle(color: kWalletTextPrimary),
            ),
          ],
        ),
      );
    }
    if (_error != null) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          _error!,
          style: const TextStyle(color: kWalletAccentDanger),
        ),
      );
    }
    final body = _state ?? const <String, dynamic>{};
    final status = (body['wallet_engine'] ?? '').toString();

    if (status == 'xmr_privacy_wallet_later') {
      return _buildDisabledBanner();
    }
    if (status == 'create_xmr_wallet_first' || status == 'no_account') {
      return _buildGenerationPending();
    }
    if (status == 'receive_ready' && body['requiresWalletMigration'] == true) {
      return _buildMigrationRequired();
    }
    if (status == 'receive_ready') {
      return _buildReadyState(context, body);
    }
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Text('Unexpected Monero wallet status: $status'),
    );
  }

  Widget _buildDisabledBanner() {
    return Padding(
      key: const Key(kMoneroReceivePanelDisabledKey),
      padding: const EdgeInsets.all(18),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: walletWarningPanel(),
        child: const Row(
          children: [
            Icon(
              Icons.hourglass_bottom_rounded,
              size: 18,
              color: kWalletAccentWarning,
            ),
            SizedBox(width: 10),
            Expanded(
              child: Text(
                kMoneroReceiveDisabledMessage,
                style: TextStyle(
                  color: kWalletAccentWarning,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
                maxLines: 3,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMigrationRequired() {
    return Padding(
      key: const Key(kMoneroReceivePanelMigrationRequiredKey),
      padding: const EdgeInsets.all(18),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: walletWarningPanel(),
        child: const Text(
          kMoneroReceiveBackupMigrationMessage,
          style: TextStyle(color: kWalletAccentWarning),
        ),
      ),
    );
  }

  Widget _buildGenerationPending() {
    final adapterAvailable = widget.walletAdapter.isAvailable;
    return Padding(
      key: const Key(kMoneroReceivePanelGenerationPendingKey),
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kMoneroReceivePanelTitle,
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 8),
          const Text(kMoneroReceiveNetworkBadge, style: kWalletBodyStyle),
          const SizedBox(height: 14),
          if (!adapterAvailable)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: walletWarningPanel(),
              child: const Row(
                children: [
                  Icon(
                    Icons.hourglass_bottom_rounded,
                    size: 16,
                    color: kWalletAccentWarning,
                  ),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      kMoneroReceiveGenerationPendingMessage,
                      style: TextStyle(
                        color: kWalletAccentWarning,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ),
            )
          else if (_creating)
            Row(
              key: const Key(kMoneroReceivePanelCreateProgressKey),
              children: const [
                SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation<Color>(
                      kWalletAccentPrimary,
                    ),
                  ),
                ),
                SizedBox(width: 12),
                Text(kMoneroReceiveCreateBusyLabel, style: kWalletBodyStyle),
              ],
            )
          else
            ElevatedButton.icon(
              key: const Key(kMoneroReceivePanelCreateBtnKey),
              onPressed: _createWallet,
              icon: const Icon(Icons.add_circle_outline_rounded, size: 16),
              label: const Text(kMoneroReceiveCreateButtonLabel),
              style: walletPrimaryButtonStyle(),
            ),
          if (_createFailureMessage != null) ...[
            const SizedBox(height: 10),
            Container(
              key: const Key(kMoneroReceivePanelCreateFailedKey),
              padding: const EdgeInsets.all(12),
              decoration: walletWarningPanel(),
              child: Row(
                children: [
                  const Icon(
                    Icons.error_outline_rounded,
                    size: 16,
                    color: kWalletAccentDanger,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _createFailureMessage!,
                      style: const TextStyle(
                        color: kWalletAccentDanger,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
          if (widget.walletV2 == null) ...[
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: walletSuccessPanel(),
              child: const Row(
                children: [
                  Icon(
                    Icons.shield_outlined,
                    size: 16,
                    color: kWalletAccentSuccess,
                  ),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      kMoneroReceiveNonCustodialAttestation,
                      style: TextStyle(
                        color: kWalletAccentSuccess,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildReadyState(BuildContext ctx, Map<String, dynamic> body) {
    final addr = (body['publicAddress'] ?? '').toString();
    final label = (body['walletLabel'] ?? '').toString();
    final restoreHeight = body['restoreHeight'];
    return Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kMoneroReceivePanelTitle,
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 4),
          Text(label, style: kWalletBodyStyle),
          const SizedBox(height: 2),
          const Text(kMoneroReceiveNetworkBadge, style: kWalletMutedStyle),
          const SizedBox(height: 14),
          Center(
            child: addr.isNotEmpty
                ? Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: kWalletBorderStrong),
                    ),
                    child: QrImageView(
                      key: const Key(kMoneroReceivePanelQrKey),
                      data: addr,
                      version: QrVersions.auto,
                      size: 220,
                      backgroundColor: Colors.white,
                    ),
                  )
                : const SizedBox.shrink(),
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: kWalletBgBase,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: kWalletBorder),
            ),
            child: SelectableText(
              addr,
              key: const Key(kMoneroReceivePanelAddressTextKey),
              style: kWalletMonoStyle,
            ),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const Key(kMoneroReceivePanelCopyBtnKey),
            onPressed: () => _copyAddress(addr),
            icon: const Icon(Icons.copy_rounded, size: 16),
            label: const Text(kMoneroReceiveCopyButtonLabel),
            style: walletGhostButtonStyle(),
          ),
          if (restoreHeight != null) ...[
            const SizedBox(height: 12),
            Container(
              key: const Key(kMoneroReceivePanelRestoreHeightKey),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: kWalletBgBase,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: kWalletBorder),
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.history_toggle_off,
                    size: 16,
                    color: kWalletTextSecondary,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Restore height: $restoreHeight',
                      style: kWalletMutedStyle,
                    ),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: walletWarningPanel(),
            child: Row(
              children: [
                const Icon(
                  Icons.warning_amber_rounded,
                  size: 16,
                  color: kWalletAccentWarning,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    (body['warning'] ?? kMoneroReceiveAssetWarning).toString(),
                    key: const Key(kMoneroReceivePanelWarningKey),
                    style: const TextStyle(
                      color: kWalletAccentWarning,
                      fontSize: 13,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: kWalletBgBase,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: kWalletBorder),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.privacy_tip_outlined,
                  size: 16,
                  color: kWalletTextSecondary,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    (body['privacyNote'] ?? kMoneroReceivePrivacyNote)
                        .toString(),
                    key: const Key(kMoneroReceivePanelPrivacyNoteKey),
                    style: kWalletMutedStyle,
                  ),
                ),
              ],
            ),
          ),
          if (widget.walletV2 != null &&
              body['backupStatus'] == 'wallet_v2_encrypted') ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: walletSuccessPanel(),
              child: const Row(
                children: [
                  Icon(
                    Icons.shield_outlined,
                    size: 16,
                    color: kWalletAccentSuccess,
                  ),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      kMoneroReceivePrivateAttestation,
                      style: TextStyle(
                        color: kWalletAccentSuccess,
                        fontSize: 13,
                      ),
                    ),
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
