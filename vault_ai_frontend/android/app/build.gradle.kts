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
// gitignored - this file is NEVER checked in. See
// android/key.properties.example for the expected schema.
//
// If key.properties is missing or incomplete, release builds fail
// closed. Debug builds still use the normal debug signing config.
// ---------------------------------------------------------------
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties()
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}
val releaseSigningProperties = listOf(
    "storeFile",
    "storePassword",
    "keyAlias",
    "keyPassword",
)
val missingReleaseSigningProperties = releaseSigningProperties.filter {
    keystoreProperties.getProperty(it).isNullOrBlank()
}
val hasReleaseSigning = keystorePropertiesFile.exists() &&
    missingReleaseSigningProperties.isEmpty()
val releaseSigningFailureMessage =
    "[vaultai-release] Release signing config is missing or incomplete. " +
    "Create android/key.properties with storeFile, storePassword, " +
    "keyAlias, and keyPassword for the Google Play upload key. " +
    "Release APK/AAB builds must never fall back to debug signing."
if (!hasReleaseSigning) {
    val missing = if (!keystorePropertiesFile.exists()) {
        "key.properties"
    } else {
        missingReleaseSigningProperties.joinToString(", ")
    }
    logger.warn("$releaseSigningFailureMessage Missing: $missing")
}

gradle.taskGraph.whenReady {
    val releaseBuildRequested = allTasks.any { task ->
        val name = task.name.lowercase()
        name.contains("release") &&
            (name.contains("assemble") ||
                name.contains("bundle") ||
                name.contains("package") ||
                name.contains("sign"))
    }
    if (releaseBuildRequested && !hasReleaseSigning) {
        throw GradleException(releaseSigningFailureMessage)
    }
}

android {
    namespace = "com.svaultai.app"
    compileSdk = 36
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
        minSdk = 24
        targetSdk = 36
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
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
        }
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
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
            // R8 code shrink + resource stripping. Play install size
            // savings ~30-50% vs unminified. Flutter engine keeps its
            // own -keep rules under $flutter_root/packages/...
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
