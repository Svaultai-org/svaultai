// 2026-07-13: Pure-Dart parser for a scanned "recipient address" QR
// code, per network.
//
// The Send flow is authoritative about which network the user is
// sending on. The parser accepts a raw string decoded from a QR
// code plus the expected network context, and returns either:
//
//   * `RecipientQrParseResult.ok(address)` — the extracted, validated
//     recipient address for that network. Populate the destination
//     text field with this and continue through the existing
//     validation/review/sign/broadcast pipeline.
//
//   * `RecipientQrParseResult.reject(reason, message)` — the QR is
//     not usable as a recipient for the selected asset/network.
//     Reasons are enumerated for tests + operator log auditability;
//     `message` is the concise user-facing string the sheet shows.
//
// Deliberate safety choices for the initial rollout:
//
//   * We NEVER treat an ERC-20 token contract address as the
//     recipient. On plain-ETH screens we reject any URI that carries
//     `pay-`, `data=`, or `/transfer?address=` (EIP-681 token-
//     transfer or arbitrary contract-call payloads) — those are the
//     shapes that historically trick wallets into sending funds to
//     a token contract or an attacker-provided address.
//
//   * We reject anything that even LOOKS LIKE a seed phrase (spaces
//     between alphabetic tokens) or a private key (0x + 64 hex).
//     A QR code that contains a seed phrase or private key must NOT
//     silently populate a recipient field.
//
//   * The parser is strictly one-network-at-a-time. An Ethereum
//     screen rejects Solana / TRON QRs and vice versa. No cross-
//     network guessing.
//
// This module is pure Dart (no Flutter import) so it can be unit-
// tested exhaustively without a widget tree.

import '../services/solana_wallet.dart' show isValidSolanaAddress;
import '../services/tron_wallet.dart' show isValidTronAddress;

enum RecipientNetwork {
  ethereum,
  solana,
  tron,
}

/// Reason codes for a rejected QR. Stable strings — tests match on
/// these. Not user-facing (the [RecipientQrParseResult.rejectMessage]
/// carries the localized user-facing copy).
class RecipientQrRejectReason {
  static const String empty = 'empty';
  static const String seedPhraseRejected = 'seed_phrase_rejected';
  static const String privateKeyRejected = 'private_key_rejected';
  static const String invalidEthereumAddress = 'invalid_ethereum_address';
  static const String invalidSolanaAddress = 'invalid_solana_address';
  static const String invalidTronAddress = 'invalid_tron_address';
  static const String crossNetwork = 'cross_network';
  static const String wrongChainId = 'wrong_chain_id';
  static const String unsupportedPayload = 'unsupported_payload';
  static const String ambiguousToken = 'ambiguous_token';
}

class RecipientQrParseResult {
  final String? address;
  final String? rejectReason;
  final String? rejectMessage;

  const RecipientQrParseResult._({
    this.address,
    this.rejectReason,
    this.rejectMessage,
  });

  factory RecipientQrParseResult.ok(String address) {
    return RecipientQrParseResult._(address: address);
  }

  factory RecipientQrParseResult.reject(String reason, String message) {
    return RecipientQrParseResult._(
      rejectReason: reason,
      rejectMessage: message,
    );
  }

  bool get ok => address != null;
}

class RecipientQrParser {
  // Regex for a bare Ethereum-style address.
  static final RegExp _ethAddrRe =
      RegExp(r'^0x[0-9a-fA-F]{40}$');

  // Regex for a raw private key (32 bytes as hex). A QR encoding a
  // 32-byte private key is `0x` + 64 hex chars. A QR encoding a raw
  // 32-byte private key WITHOUT the `0x` prefix is 64 hex chars.
  static final RegExp _ethPrivKeyRe =
      RegExp(r'^(0x)?[0-9a-fA-F]{64}$');

  // Any string with a space between two runs of letters is treated
  // as a possible mnemonic / seed phrase / recovery phrase. An
  // address never contains spaces on any of the supported networks.
  static final RegExp _looksLikeMnemonicRe =
      RegExp(r'^\s*[A-Za-z]+(\s+[A-Za-z]+){2,}\s*$');

  /// Parse a scanned QR payload assuming the user is sending on
  /// [network].
  ///
  /// [expectedChainId] is required for Ethereum. Currently supported
  /// values in the app are 1 (mainnet) and 11155111 (Sepolia).
  static RecipientQrParseResult parse({
    required String raw,
    required RecipientNetwork network,
    int? expectedChainId,
  }) {
    final trimmed = raw.trim();
    if (trimmed.isEmpty) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.empty,
        'The scanned QR was empty.',
      );
    }
    // Universal seed-phrase rejection: applies on every network.
    if (_looksLikeMnemonicRe.hasMatch(trimmed)) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.seedPhraseRejected,
        'This QR looks like a recovery phrase, not a recipient '
        'address. Never share your seed phrase.',
      );
    }
    switch (network) {
      case RecipientNetwork.ethereum:
        return _parseEthereum(trimmed, expectedChainId);
      case RecipientNetwork.solana:
        return _parseSolana(trimmed);
      case RecipientNetwork.tron:
        return _parseTron(trimmed);
    }
  }

  // ── Ethereum ────────────────────────────────────────────────────

  static RecipientQrParseResult _parseEthereum(
    String raw,
    int? expectedChainId,
  ) {
    // Reject cross-network payloads FIRST. A "solana:..." or "tron:..."
    // URI is not accidentally an Ethereum address.
    if (raw.startsWith('solana:') ||
        raw.startsWith('sol:')) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.crossNetwork,
        'This QR code is for a Solana address. This is an '
        'Ethereum Send screen.',
      );
    }
    if (raw.startsWith('tron:') ||
        raw.startsWith('trx:') ||
        (raw.length == 34 && raw.startsWith('T'))) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.crossNetwork,
        'This QR code is for a TRON address. This is an '
        'Ethereum Send screen.',
      );
    }
    // Reject private key.
    if (_ethPrivKeyRe.hasMatch(raw)) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.privateKeyRejected,
        'This QR looks like a private key, not a recipient '
        'address. Never share your private key.',
      );
    }
    // Plain address.
    if (_ethAddrRe.hasMatch(raw)) {
      return RecipientQrParseResult.ok(raw);
    }
    // Ethereum URI. Deliberately conservative EIP-681 subset:
    //   ethereum:0xADDRESS[@CHAIN][?value=...&gas=...]
    // Rejected:
    //   ethereum:pay-<contract>/transfer?address=<recipient>...
    //   ethereum:0xADDR/<function>?...
    //   ethereum:<0xADDR>?data=0x...
    // Those are token-transfer or arbitrary contract-call payloads
    // that require a per-token security review before we accept
    // them into the recipient field.
    if (raw.startsWith('ethereum:')) {
      var payload = raw.substring('ethereum:'.length);
      if (payload.startsWith('pay-')) {
        return RecipientQrParseResult.reject(
          RecipientQrRejectReason.ambiguousToken,
          'This QR is a token-payment request. This Send screen '
          'does not yet accept token payment URIs. Enter the '
          'recipient address directly.',
        );
      }
      // Split off query string.
      String? query;
      final qIdx = payload.indexOf('?');
      if (qIdx >= 0) {
        query = payload.substring(qIdx + 1);
        payload = payload.substring(0, qIdx);
      }
      // A "/" after the address means a function call — reject.
      if (payload.contains('/')) {
        return RecipientQrParseResult.reject(
          RecipientQrRejectReason.unsupportedPayload,
          'This QR embeds a contract call. This Send screen only '
          'accepts a plain recipient address.',
        );
      }
      // Optional chain ID hint after "@".
      String addressPart = payload;
      int? uriChainId;
      final atIdx = payload.indexOf('@');
      if (atIdx >= 0) {
        addressPart = payload.substring(0, atIdx);
        final chainStr = payload.substring(atIdx + 1);
        uriChainId = int.tryParse(chainStr);
        if (uriChainId == null) {
          return RecipientQrParseResult.reject(
            RecipientQrRejectReason.unsupportedPayload,
            'This QR has an unrecognised chain hint.',
          );
        }
      }
      if (!_ethAddrRe.hasMatch(addressPart)) {
        return RecipientQrParseResult.reject(
          RecipientQrRejectReason.invalidEthereumAddress,
          'This QR code is not a valid Ethereum address.',
        );
      }
      if (uriChainId != null &&
          expectedChainId != null &&
          uriChainId != expectedChainId) {
        return RecipientQrParseResult.reject(
          RecipientQrRejectReason.wrongChainId,
          'This QR is for chain $uriChainId. This Send screen is '
          'sending on chain $expectedChainId.',
        );
      }
      // Reject `data=` (arbitrary contract-call payload) — safety.
      if (query != null) {
        final params = _parseQueryParams(query);
        if (params.containsKey('data')) {
          return RecipientQrParseResult.reject(
            RecipientQrRejectReason.unsupportedPayload,
            'This QR embeds contract call data. This Send screen '
            'only accepts a plain recipient address.',
          );
        }
        // `value=` and `gas=` are optional and ignored by design —
        // the user enters the amount manually so a malicious QR
        // cannot silently change the amount they intended to send.
      }
      return RecipientQrParseResult.ok(addressPart);
    }
    // Anything else on the Ethereum screen is not a valid address.
    return RecipientQrParseResult.reject(
      RecipientQrRejectReason.invalidEthereumAddress,
      'This QR code is not a valid Ethereum address.',
    );
  }

  // ── Solana ──────────────────────────────────────────────────────

  static RecipientQrParseResult _parseSolana(String raw) {
    // Cross-network rejection.
    if (raw.startsWith('ethereum:') ||
        raw.startsWith('0x') ||
        raw.startsWith('tron:') ||
        raw.startsWith('trx:') ||
        (raw.length == 34 && raw.startsWith('T'))) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.crossNetwork,
        'This QR is not a valid Solana address (looks like a '
        'different network).',
      );
    }
    var candidate = raw;
    if (candidate.startsWith('solana:')) {
      candidate = candidate.substring('solana:'.length);
      // Solana Pay: strip query params — we don't override amount.
      final qIdx = candidate.indexOf('?');
      if (qIdx >= 0) {
        candidate = candidate.substring(0, qIdx);
      }
      // Reject in-path function calls.
      if (candidate.contains('/')) {
        return RecipientQrParseResult.reject(
          RecipientQrRejectReason.unsupportedPayload,
          'This QR embeds a program call. This Send screen only '
          'accepts a plain recipient address.',
        );
      }
    }
    // A Solana private key exported as base58 is ~87–88 chars long.
    // Reject anything longer than a public key.
    if (candidate.length > 44) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.privateKeyRejected,
        'This QR is not a Solana address (too long — looks like '
        'a private key or seed).',
      );
    }
    if (!isValidSolanaAddress(candidate)) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.invalidSolanaAddress,
        'This QR code is not a valid Solana address.',
      );
    }
    return RecipientQrParseResult.ok(candidate);
  }

  // ── TRON ────────────────────────────────────────────────────────

  static RecipientQrParseResult _parseTron(String raw) {
    if (raw.startsWith('ethereum:') ||
        raw.startsWith('0x') ||
        raw.startsWith('solana:') ||
        raw.startsWith('sol:')) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.crossNetwork,
        'This QR is not a valid TRON address (looks like a '
        'different network).',
      );
    }
    var candidate = raw;
    if (candidate.startsWith('tron:')) {
      candidate = candidate.substring('tron:'.length);
      final qIdx = candidate.indexOf('?');
      if (qIdx >= 0) {
        candidate = candidate.substring(0, qIdx);
      }
      if (candidate.contains('/')) {
        return RecipientQrParseResult.reject(
          RecipientQrRejectReason.unsupportedPayload,
          'This QR embeds a contract call. This Send screen only '
          'accepts a plain recipient address.',
        );
      }
    } else if (candidate.startsWith('trx:')) {
      candidate = candidate.substring('trx:'.length);
      final qIdx = candidate.indexOf('?');
      if (qIdx >= 0) {
        candidate = candidate.substring(0, qIdx);
      }
    }
    if (!isValidTronAddress(candidate)) {
      return RecipientQrParseResult.reject(
        RecipientQrRejectReason.invalidTronAddress,
        'This QR code is not a valid TRON address.',
      );
    }
    return RecipientQrParseResult.ok(candidate);
  }

  static Map<String, String> _parseQueryParams(String query) {
    final map = <String, String>{};
    for (final part in query.split('&')) {
      if (part.isEmpty) continue;
      final eqIdx = part.indexOf('=');
      if (eqIdx < 0) {
        map[part] = '';
      } else {
        map[part.substring(0, eqIdx)] = part.substring(eqIdx + 1);
      }
    }
    return map;
  }
}
