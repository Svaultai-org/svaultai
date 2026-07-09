

import 'dart:typed_data';

import 'package:crypto/crypto.dart';


String computeContentSha256(Uint8List bytes) {
  final digest = sha256.convert(bytes);
  return digest.toString();
}


String shortHashForLog(String? contentSha256) {
  if (contentSha256 == null || contentSha256.isEmpty) return '-';
  return contentSha256.length <= 8
      ? contentSha256
      : contentSha256.substring(0, 8);
}


enum DuplicateAction {
  
  
  prompt,

  
  skip,

  
  keepBoth,

  
  replace;

  String get wireValue {
    switch (this) {
      case DuplicateAction.prompt:
        return 'prompt';
      case DuplicateAction.skip:
        return 'skip';
      case DuplicateAction.keepBoth:
        return 'keep_both';
      case DuplicateAction.replace:
        return 'replace';
    }
  }
}


class DuplicateFoundDetail {
  
  
  final String existingFileId;

  
  final String? existingFileName;

  
  final String? existingSavedName;

  
  final String? existingRelativePath;

  
  final String? existingUploadedAt;

  
  final String incomingFileName;
  final int incomingSize;

  
  final String message;

  const DuplicateFoundDetail({
    required this.existingFileId,
    required this.incomingFileName,
    required this.incomingSize,
    required this.message,
    this.existingFileName,
    this.existingSavedName,
    this.existingRelativePath,
    this.existingUploadedAt,
  });

  factory DuplicateFoundDetail.fromJson(Map<String, dynamic> json) {
    return DuplicateFoundDetail(
      existingFileId: (json['existing_file_id'] as String?) ?? '',
      existingFileName: json['existing_file_name'] as String?,
      existingSavedName: json['existing_saved_name'] as String?,
      existingRelativePath: json['existing_relative_path'] as String?,
      existingUploadedAt: json['existing_uploaded_at'] as String?,
      incomingFileName:
          (json['incoming_file_name'] as String?) ?? 'file',
      incomingSize: (json['incoming_size'] is int)
          ? json['incoming_size'] as int
          : 0,
      message: (json['message'] as String?) ?? 'This file already exists.',
    );
  }
}


class DuplicateFoundException implements Exception {
  final DuplicateFoundDetail detail;
  const DuplicateFoundException(this.detail);

  @override
  String toString() =>
      'DuplicateFoundException(existing=${detail.existingFileId})';
}


class NameConflictDetail {
  
  final String existingFileId;

  
  final String? existingFileName;

  
  final String? existingSavedName;

  
  final String? existingRelativePath;

  
  final String? existingUploadedAt;

  
  final String incomingFileName;
  final int incomingSize;

  
  final String? proposedVersionedName;

  
  final String message;

  const NameConflictDetail({
    required this.existingFileId,
    required this.incomingFileName,
    required this.incomingSize,
    required this.message,
    this.existingFileName,
    this.existingSavedName,
    this.existingRelativePath,
    this.existingUploadedAt,
    this.proposedVersionedName,
  });

  factory NameConflictDetail.fromJson(Map<String, dynamic> json) {
    return NameConflictDetail(
      existingFileId: (json['existing_file_id'] as String?) ?? '',
      existingFileName: json['existing_file_name'] as String?,
      existingSavedName: json['existing_saved_name'] as String?,
      existingRelativePath: json['existing_relative_path'] as String?,
      existingUploadedAt: json['existing_uploaded_at'] as String?,
      incomingFileName:
          (json['incoming_file_name'] as String?) ?? 'file',
      incomingSize: (json['incoming_size'] is int)
          ? json['incoming_size'] as int
          : 0,
      proposedVersionedName:
          json['proposed_versioned_name'] as String?,
      message: (json['message'] as String?) ??
          'A file with this name already exists in this folder, but '
              'the content is different.',
    );
  }
}
