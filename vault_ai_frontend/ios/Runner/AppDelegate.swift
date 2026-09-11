import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Retain the statically linked Rust archive so Dart FFI can resolve its
    // exported OPAQUE/PBKDF2 symbols through DynamicLibrary.process().
    _ = vaultai_opaque_client_link_anchor()
    GeneratedPluginRegistrant.register(with: self)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
