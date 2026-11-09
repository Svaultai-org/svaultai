/// Preserve a private V2 upload's key and vault binding across queue setup.
library;

import 'package:cryptography/cryptography.dart';

SecretKey? selectV2UploadKey({
  required SecretKey? activeMvk,
  required String? activeVaultId,
  required bool writerEnabled,
  required bool readerEnabled,
  SecretKey? requiredPrivateMvk,
  String? requiredPrivateVaultId,
}) {
  if (requiredPrivateMvk == null && requiredPrivateVaultId != null) {
    throw StateError('Private upload binding is incomplete');
  }
  if (requiredPrivateMvk != null) {
    if (!writerEnabled ||
        !readerEnabled ||
        requiredPrivateVaultId == null ||
        requiredPrivateVaultId.isEmpty ||
        activeVaultId != requiredPrivateVaultId ||
        !identical(activeMvk, requiredPrivateMvk)) {
      throw StateError('Private upload access changed. Unlock and retry.');
    }
    return requiredPrivateMvk;
  }
  return writerEnabled ? activeMvk : null;
}

String? uploadAccompanyingText({
  required String? text,
  required SecretKey? requiredPrivateMvk,
}) =>
    requiredPrivateMvk == null ? text : null;
