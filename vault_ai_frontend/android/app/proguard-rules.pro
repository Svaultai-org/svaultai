# VaultAI ProGuard / R8 rules.
#
# Applied on release builds (see android/app/build.gradle.kts
# `release { isMinifyEnabled = true }`). Flutter engine's own
# -keep rules ship inside the Flutter Gradle plugin — this file
# only adds project-specific keeps.
#
# When to add here:
#   * A native plugin that fails at runtime with
#     ClassNotFoundException / NoSuchMethodError only in release.
#   * A reflection-heavy dependency (e.g. json_serializable code
#     that reads Type names at runtime).
#
# When NOT to add here:
#   * Anything you can express as an @Keep annotation in the
#     plugin source instead.

# --- Flutter engine (defensive; the plugin already keeps these) ---
-keep class io.flutter.embedding.** { *; }
-keep class io.flutter.plugin.** { *; }
-keep class io.flutter.plugins.** { *; }

# --- flutter_secure_storage relies on androidx.security.crypto ---
-keep class androidx.security.crypto.** { *; }

# --- Google Play Core (needed for split installs / deferred components,
#     Flutter references it defensively even when not used) ---
-dontwarn com.google.android.play.core.**
