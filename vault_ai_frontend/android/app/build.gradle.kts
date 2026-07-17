import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// ---------------------------------------------------------------
// Upload-key material. Loaded from android/key.properties which is
// gitignored — this file is NEVER checked in. See
// android/key.properties.example for the expected schema.
//
// If key.properties is missing (developer laptop, CI without signing
// creds), the release build falls back to the DEBUG keystore so
// `flutter build appbundle --release` still succeeds locally for
// validation. That fallback is intentional and loud: Gradle prints
// a WARN line at configuration time so no one accidentally ships a
// debug-signed bundle to Play. Production CI must always provide
// key.properties.
// ---------------------------------------------------------------
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties()
val hasReleaseSigning = keystorePropertiesFile.exists()
if (hasReleaseSigning) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
} else {
    logger.warn(
        "[vaultai-release] android/key.properties not found — release " +
        "builds will be DEBUG-SIGNED. This is fine for local " +
        "validation. Production CI MUST provide key.properties " +
        "before uploading to Play Console."
    )
}

android {
    namespace = "com.svaultai.app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        applicationId = "com.svaultai.app"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName

        // ---------------------------------------------------------------
        // Production API host resolution: the Dart-level default in
        // lib/main.dart resolves `backendBaseUrl` to
        // https://api.svaultai.com whenever kReleaseMode && !kIsWeb,
        // so a plain `flutter build appbundle --release` cannot ship
        // a build that silently talks to localhost. Passing
        //   --dart-define=BACKEND_BASE_URL=<url>
        // at the flutter build command line still overrides it for
        // staging or per-tester deploys.
        // ---------------------------------------------------------------
    }

    signingConfigs {
        create("release") {
            if (hasReleaseSigning) {
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
                storeFile = keystoreProperties
                    .getProperty("storeFile")?.let { file(it) }
                storePassword = keystoreProperties.getProperty("storePassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (hasReleaseSigning) {
                signingConfigs.getByName("release")
            } else {
                // Local-dev fallback — see keystoreProperties block
                // above. Play Console rejects debug-signed bundles.
                signingConfigs.getByName("debug")
            }
            // R8 code shrink + resource stripping. Play install size
            // savings ~30-50% vs unminified. Flutter engine keeps its
            // own -keep rules under $flutter_root/packages/…
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
}

flutter {
    source = "../.."
}
