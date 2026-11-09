import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:vault_ai_frontend/services/zk_local_photo_description.dart';

Uint8List _jpeg({String? description}) {
  final image = img.Image(width: 8, height: 8);
  if (description != null) {
    image.exif.imageIfd.imageDescription = description;
  }
  return Uint8List.fromList(img.encodeJpg(image));
}

void main() {
  test('reads only the bounded creator-authored JPEG description locally', () {
    final bytes = _jpeg(description: '  Red shirt  and black shoes  ');
    expect(
      readEmbeddedJpegDescription(bytes, accessIsCurrent: () => true),
      'Red shirt and black shoes',
    );
    expect(
      readEmbeddedJpegDescription(_jpeg(), accessIsCurrent: () => true),
      isNull,
    );
  });

  test('rejects overlong metadata and non-JPEG bytes as evidence', () {
    expect(
      readEmbeddedJpegDescription(
        _jpeg(description: List<String>.filled(200, 'shirt').join(' ')),
        accessIsCurrent: () => true,
      ),
      isNull,
    );
    expect(
      readEmbeddedJpegDescription(
        Uint8List.fromList(<int>[1, 2, 3, 4]),
        accessIsCurrent: () => true,
      ),
      isNull,
    );
    expect(
      () => readEmbeddedJpegDescription(
        Uint8List(maxLocalPhotoDescriptionBytes + 1),
        accessIsCurrent: () => true,
      ),
      throwsFormatException,
    );
  });

  test('session loss cannot yield a photo description', () {
    expect(
      () => readEmbeddedJpegDescription(
        _jpeg(description: 'private beach'),
        accessIsCurrent: () => false,
      ),
      throwsStateError,
    );
  });
}
