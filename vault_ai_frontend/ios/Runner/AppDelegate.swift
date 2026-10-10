import Flutter
import UIKit
import StoreKit

@main
@objc class AppDelegate: FlutterAppDelegate {
  private var storefrontChannel: FlutterMethodChannel?
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // Retain the statically linked Rust archive so Dart FFI can resolve its
    // exported OPAQUE/PBKDF2 symbols through DynamicLibrary.process().
    _ = vaultai_opaque_client_link_anchor()
    GeneratedPluginRegistrant.register(with: self)
    if let registrar = registrar(forPlugin: "SVaultNativeStoreExperience") {
      let channel = FlutterMethodChannel(name: "com.svaultai.app/storefront",
                                         binaryMessenger: registrar.messenger())
      storefrontChannel = channel
      channel.setMethodCallHandler { call, result in
        guard call.method == "info" else {
          result(FlutterMethodNotImplemented)
          return
        }
        let systemVersion = UIDevice.current.systemVersion
        #if targetEnvironment(simulator)
        let production = false
        #else
        let receipt = Bundle.main.appStoreReceiptURL
        let production = receipt?.lastPathComponent == "receipt" &&
                         receipt.map { FileManager.default.fileExists(atPath: $0.path) } == true
        #endif
        guard production else {
          result(["country": "", "systemVersion": systemVersion,
                  "productionReceipt": false])
          return
        }
        // This synchronous StoreKit property can block. Never read it on the
        // launch/UI thread. Country is the Apple Account storefront, not locale.
        DispatchQueue.global(qos: .utility).async {
          let country: String
          if #available(iOS 13.0, *), let storefront = SKPaymentQueue.default().storefront {
            // Foundation/ICU maps ISO alpha-3 storefront codes to alpha-2.
            country = Locale(identifier: "und_" + storefront.countryCode).regionCode ?? ""
          } else {
            country = ""
          }
          DispatchQueue.main.async {
            result(["country": country, "systemVersion": systemVersion,
                    "productionReceipt": true])
          }
        }
      }
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
