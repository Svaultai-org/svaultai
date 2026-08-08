import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;

const _enabled = bool.fromEnvironment('QA_TRUST_LOCAL_CA', defaultValue: false);
const _caB64 = String.fromEnvironment('QA_CA_B64', defaultValue: '');

Future<void> configureQaHttpTrust() async {
  print('[qa-tls] enabled=$_enabled ca_present=${_caB64.isNotEmpty}');
  if (!_enabled) return;
  if (_caB64.isEmpty) {
    throw StateError('qa_ca_unavailable');
  }
  final bytes = base64Decode(_caB64);
  print('[qa-tls] decode_success=true decoded_len_gt_zero=${bytes.isNotEmpty}');
  final context = SecurityContext(withTrustedRoots: true);
  print('[qa-tls] security_context_created=true with_trusted_roots=true');
  context.setTrustedCertificatesBytes(bytes);
  print('[qa-tls] set_trusted_certificates_succeeded=true');
  final client = HttpClient(context: context);
  HttpOverrides.global = _QaOverrides(client);
  try {
    final response = await http.get(Uri.parse('https://10.0.2.2:8444/health'));
    print('[qa-tls] custom_health_status=${response.statusCode}');
  } catch (error) {
    print('[qa-tls] custom_health_error=${error.runtimeType}');
    rethrow;
  }
}

class _QaOverrides extends HttpOverrides {
  final HttpClient client;
  _QaOverrides(this.client);

  @override
  HttpClient createHttpClient(SecurityContext? _) => client;
}
