/// Read a released owner's V2 file on the beneficiary's device only.
///
/// The server supplies ciphertext after checking the released link. Its
/// response is scoped to the same owner/link as the MVK envelope before any
/// encrypted manifest or chunk is accepted. This does not import the file.
library;

import 'package:cryptography/cryptography.dart';

import 'file_v2_reader.dart';
import 'inheritance_mvk_v2.dart';

typedef FetchInheritedFileCiphertext = Future<Map<String, dynamic>> Function(
  String path,
);

Future<FileV2Download> readReleasedV2File({
  required int linkId,
  required String fileId,
  required SecretKey beneficiaryPrivateKey,
  required Map<String, dynamic> releasedPackage,
  required FetchInheritedFileCiphertext fetch,
  required bool Function() accessIsCurrent,
}) async {
  if (!RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(fileId)) {
    throw const FormatException('Invalid inherited file identity');
  }
  void checkAccess() {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
  }

  checkAccess();
  final inherited = await decryptInheritanceMvk(
    expectedLinkId: linkId,
    beneficiaryPrivateKey: beneficiaryPrivateKey,
    rawPackage: releasedPackage,
  );
  checkAccess();

  final expectedPrefix = '/vault/file-v2/$fileId/';
  final reader = FileV2Reader(
    mvk: inherited.ownerMvk,
    get: (path) async {
      checkAccess();
      if (!path.startsWith(expectedPrefix)) {
        throw const FormatException('Invalid inherited file path');
      }
      final suffix = path.substring(expectedPrefix.length);
      if (suffix != 'manifest' &&
          !RegExp(r'^chunk/(0|[1-9][0-9]*)$').hasMatch(suffix)) {
        throw const FormatException('Invalid inherited file request');
      }
      final response = await fetch(
        '/inheritance/v2/$linkId/files/$fileId/$suffix',
      );
      checkAccess();
      if (response['beneficiary_link_id'] != linkId ||
          response['owner_vault_id'] != inherited.ownerVaultId) {
        throw const FormatException('Inherited file context mismatch');
      }
      return response;
    },
  );
  final result = await reader.download(fileId, requireReady: true);
  checkAccess();
  return result;
}
