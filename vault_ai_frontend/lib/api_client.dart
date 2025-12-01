import 'dart:convert';
import 'package:http/http.dart' as http;

class VaultAIClient {
  final String baseUrl;

  VaultAIClient({this.baseUrl = "http://127.0.0.1:8000"});

  Stream<String> chatStream({
    required String userId,
    required String message,
    required bool unlocked,
    required bool videoVerified,
  }) async* {
    final url = Uri.parse("$baseUrl/chat");

    final body = jsonEncode({
      "user_id": userId,
      "message": message,
      "session_unlocked": unlocked,
      "video_verified": videoVerified,
    });

    final request = http.Request("POST", url)
      ..headers["Content-Type"] = "application/json"
      ..body = body;

    final streamed = await request.send();

    await for (final chunk in streamed.stream.transform(utf8.decoder)) {
      yield chunk;
    }
  }
}
