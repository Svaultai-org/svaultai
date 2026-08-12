import 'dart:convert';
import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// PBKDF2 through the browser's native Web Crypto implementation. This keeps
/// the exact SHA-256 algorithm, salt, iteration count, and 256-bit output used
/// by the server while avoiding a long pure-Dart loop on the UI isolate.
Future<Uint8List?> deriveWebPbkdf2HmacSha256({
  required String password,
  required Uint8List salt,
  required int iterations,
}) async {
  final subtle = web.window.crypto.subtle;
  final baseKey = await subtle
      .importKey(
        'raw',
        Uint8List.fromList(utf8.encode(password)).toJS,
        'PBKDF2'.toJS,
        false,
        <JSString>['deriveBits'.toJS].toJS,
      )
      .toDart;
  final parameters = <String, Object?>{
    'name': 'PBKDF2',
    'salt': salt.toJS,
    'iterations': iterations,
    'hash': 'SHA-256',
  }.jsify()!;
  final bits = await subtle.deriveBits(parameters, baseKey, 256).toDart;
  return Uint8List.view(bits.toDart);
}
