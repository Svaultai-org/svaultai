

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart' as cg;

import 'solana_wallet.dart';


const int kSolanaLamportsPerSol = 1000000000;
final Uint8List kSolanaSystemProgramId = Uint8List(32);


class SolanaTransferParams {
  final Uint8List fromPubkey;
  final Uint8List toPubkey;
  final int lamports;
  final Uint8List recentBlockhash;

  SolanaTransferParams({
    required this.fromPubkey,
    required this.toPubkey,
    required this.lamports,
    required this.recentBlockhash,
  }) {
    if (fromPubkey.length != 32) {
      throw ArgumentError('fromPubkey must be 32 bytes.');
    }
    if (toPubkey.length != 32) {
      throw ArgumentError('toPubkey must be 32 bytes.');
    }
    if (lamports <= 0) {
      throw ArgumentError('lamports must be positive.');
    }
    if (recentBlockhash.length != 32) {
      throw ArgumentError('recentBlockhash must be 32 bytes.');
    }
  }
}


class SolanaWireTransaction {
  final Uint8List bytes;
  const SolanaWireTransaction(this.bytes);
  String get base64 => base64Encode(bytes);
}


class SolanaSigningError implements Exception {
  final String message;
  const SolanaSigningError(this.message);
  @override
  String toString() => 'SolanaSigningError: $message';
}


int _compactU16Length(int n) {
  if (n < 0 || n > 0xffff) {
    throw ArgumentError('compact-u16 must be in [0, 65535]');
  }
  if (n < 0x80) return 1;
  if (n < 0x4000) return 2;
  return 3;
}


void _writeCompactU16(BytesBuilder out, int n) {
  if (n < 0 || n > 0xffff) {
    throw ArgumentError('compact-u16 must be in [0, 65535]');
  }
  var value = n;
  while (true) {
    var byte = value & 0x7f;
    value >>= 7;
    if (value == 0) {
      out.addByte(byte);
      return;
    }
    out.addByte(byte | 0x80);
  }
}


void _writeUint64LittleEndian(BytesBuilder out, int value) {
  if (value < 0) {
    throw ArgumentError('u64 must be non-negative');
  }
  var v = value;
  for (var i = 0; i < 8; i++) {
    out.addByte(v & 0xff);
    v >>= 8;
  }
}


Uint8List buildSolanaTransferInstructionData(int lamports) {
  final builder = BytesBuilder();
  builder.addByte(2);
  builder.addByte(0);
  builder.addByte(0);
  builder.addByte(0);
  _writeUint64LittleEndian(builder, lamports);
  return builder.toBytes();
}


Uint8List buildSolanaTransferMessage(SolanaTransferParams params) {
  final builder = BytesBuilder();
  builder.addByte(1);
  builder.addByte(0);
  builder.addByte(1);


  _writeCompactU16(builder, 3);
  builder.add(params.fromPubkey);
  builder.add(params.toPubkey);
  builder.add(kSolanaSystemProgramId);


  builder.add(params.recentBlockhash);


  _writeCompactU16(builder, 1);
  builder.addByte(2);
  _writeCompactU16(builder, 2);
  builder.addByte(0);
  builder.addByte(1);
  final data = buildSolanaTransferInstructionData(params.lamports);
  _writeCompactU16(builder, data.length);
  builder.add(data);

  return builder.toBytes();
}


Future<Uint8List> signSolanaMessageBytes({
  required Uint8List messageBytes,
  required Uint8List ed25519Seed32,
}) async {
  if (ed25519Seed32.length != 32) {
    throw const SolanaSigningError(
      'Ed25519 seed must be exactly 32 bytes.',
    );
  }
  final algorithm = cg.Ed25519();
  final keyPair = await algorithm.newKeyPairFromSeed(ed25519Seed32);
  final signature = await algorithm.sign(
    messageBytes, keyPair: keyPair,
  );
  final sigBytes = Uint8List.fromList(signature.bytes);
  if (sigBytes.length != 64) {
    throw const SolanaSigningError(
      'Ed25519 signature must be 64 bytes.',
    );
  }
  return sigBytes;
}


SolanaWireTransaction assembleSolanaWireTransaction({
  required Uint8List signature,
  required Uint8List messageBytes,
}) {
  if (signature.length != 64) {
    throw const SolanaSigningError('Signature must be 64 bytes.');
  }
  final builder = BytesBuilder();
  _writeCompactU16(builder, 1);
  builder.add(signature);
  builder.add(messageBytes);
  return SolanaWireTransaction(builder.toBytes());
}


class SolanaSignedTransfer {
  final SolanaWireTransaction wireTransaction;
  final SolanaTransferParams params;
  const SolanaSignedTransfer({
    required this.wireTransaction,
    required this.params,
  });
}


Future<SolanaSignedTransfer> signSolanaTransfer({
  required String fromAddressBase58,
  required String destinationAddressBase58,
  required int lamports,
  required String recentBlockhashBase58,
  required Uint8List ed25519Seed32,
}) async {
  final fromBytes = base58Decode(fromAddressBase58);
  if (fromBytes == null || fromBytes.length != 32) {
    throw const SolanaSigningError('fromAddress is not a valid Solana address.');
  }
  final toBytes = base58Decode(destinationAddressBase58);
  if (toBytes == null || toBytes.length != 32) {
    throw const SolanaSigningError(
      'destinationAddress is not a valid Solana address.',
    );
  }
  final blockhashBytes = base58Decode(recentBlockhashBase58);
  if (blockhashBytes == null || blockhashBytes.length != 32) {
    throw const SolanaSigningError(
      'recentBlockhash is not a valid 32-byte base58 value.',
    );
  }

  final params = SolanaTransferParams(
    fromPubkey: fromBytes,
    toPubkey: toBytes,
    lamports: lamports,
    recentBlockhash: blockhashBytes,
  );
  final message = buildSolanaTransferMessage(params);
  final signature = await signSolanaMessageBytes(
    messageBytes: message,
    ed25519Seed32: ed25519Seed32,
  );
  final wire = assembleSolanaWireTransaction(
    signature: signature,
    messageBytes: message,
  );
  return SolanaSignedTransfer(
    wireTransaction: wire,
    params: params,
  );
}


int parseSolAmountToLamports(String amount) {
  final s = amount.trim();
  if (s.isEmpty) {
    throw const SolanaSigningError('Amount must not be empty.');
  }
  final match = RegExp(r'^\d+(?:\.\d+)?$').matchAsPrefix(s);
  if (match == null || match.end != s.length) {
    throw const SolanaSigningError(
      'Amount must be a non-negative decimal like 0.1 or 5.',
    );
  }
  final dotIndex = s.indexOf('.');
  final whole = dotIndex < 0 ? s : s.substring(0, dotIndex);
  final frac = dotIndex < 0 ? '' : s.substring(dotIndex + 1);
  if (frac.length > 9) {
    throw const SolanaSigningError(
      'Solana amounts support at most 9 decimal places.',
    );
  }
  final fracPadded = frac.padRight(9, '0');
  final lamports = int.parse(whole) * kSolanaLamportsPerSol
      + (fracPadded.isEmpty ? 0 : int.parse(fracPadded));
  if (lamports <= 0) {
    throw const SolanaSigningError(
      'Amount must be greater than zero.',
    );
  }
  return lamports;
}
