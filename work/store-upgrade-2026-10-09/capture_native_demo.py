"""Capture real native pixels at safe synthetic-demo test checkpoints.

Only dedicated SVaultAI QA simulators/emulators are eligible. This helper
never logs into an account, signs a wallet transaction or contacts production.
It invokes the integration test whose strict in-process transport intercepts
all app HTTP. Captures are not proof of real billing, transfers or storefront
eligible-install prompts. No screenshots are fabricated, resized or edited.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import threading
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "vault_ai_frontend"
OUTPUT = Path(__file__).resolve().parent
IPHONE_QA = "6ED5BC7E-4CA7-4965-A72E-886577659524"
IPHONE_LARGE_QA = "626C14EC-E852-475D-B857-60A56A66F9D9"
CHECKPOINT = re.compile(r"SVAULTAI_DEMO_SCREENSHOT_READY:([a-z0-9-]+)")


def run(command: list[str], **kwargs):
    return subprocess.run(command, check=True, capture_output=True, **kwargs)


def verify_device(args):
    if args.kind == "ios":
        rows = json.loads(run(["xcrun", "simctl", "list", "devices", "--json"], text=True).stdout)
        matches = [d for devices in rows["devices"].values() for d in devices if d["udid"] == args.device]
        if len(matches) != 1:
            raise SystemExit("Exact iOS Simulator device was not found")
        device = matches[0]
        # The parent explicitly assigned this QA iPhone or a dedicated new
        # SVaultAI QA iPad. A normal personal/user iPhone is never eligible.
        dedicated_ipad = "ipad" in device["name"].lower() and "svaultai" in device["name"].lower() and "qa" in device["name"].lower()
        if args.device not in {IPHONE_QA, IPHONE_LARGE_QA} and not dedicated_ipad:
            raise SystemExit("Refusing a non-dedicated iOS QA device")
        if device.get("state") != "Booted":
            raise SystemExit("Boot the dedicated QA device before capture")
        return {"name": device["name"], "device": args.device, "kind": "ios"}
    if not re.fullmatch(r"emulator-\d+", args.device):
        raise SystemExit("Only an Android emulator is eligible")
    avd = run([args.adb, "-s", args.device, "emu", "avd", "name"], text=True).stdout.splitlines()[0].strip()
    if avd != "SvaultAI_API_36":
        raise SystemExit("Refusing any Android emulator other than SvaultAI_API_36")
    display = run([args.adb, "-s", args.device, "shell", "wm", "size"], text=True).stdout.strip()
    physical = re.search(r"Physical size: (\d+x\d+)", display)
    override = re.search(r"Override size: (\d+x\d+)", display)
    if not physical:
        raise SystemExit("Cannot verify exact QA Android display size")
    return {"name": avd, "device": args.device, "kind": "android",
            "original_display_size": physical[1],
            "original_override_size": override[1] if override else None}


def png_info(path: Path):
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise RuntimeError("Native screenshot is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return {"file": str(path), "width": width, "height": height,
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--flutter", required=True)
    parser.add_argument("--kind", choices=["ios", "android"], required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--label", choices=["iphone", "ipad", "android"], required=True)
    parser.add_argument("--run", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--adb", default="/Users/chosenbrain/Library/Android/sdk/platform-tools/adb")
    parser.add_argument("--pod", default="/Users/chosenbrain/.gem/ruby/2.6.0/bin/pod")
    parser.add_argument("--android-viewport", default="1080x1920")
    args = parser.parse_args()
    if not Path(args.flutter).is_file():
        raise SystemExit("Exact Flutter executable does not exist")
    if not re.fullmatch(r"[A-Za-z0-9-]+", args.run):
        raise SystemExit("Run label must contain only letters, numbers and hyphens")
    device = verify_device(args)
    target = OUTPUT / args.label / args.run
    if target.exists():
        raise SystemExit("Capture directory already exists; retain it and use an explicitly new run label")
    target.mkdir(parents=True)
    report = target / "integration-report.json"
    environment = os.environ.copy()
    if args.kind == "ios":
        if not Path(args.pod).is_file():
            raise SystemExit("Exact CocoaPods executable does not exist")
        run([args.pod, "--version"], text=True)
        environment["PATH"] = str(Path(args.pod).parent) + os.pathsep + environment.get("PATH", "")
        environment["GEM_HOME"] = str(Path(args.pod).parent.parent)
    environment["SVAULTAI_DEMO_REPORT"] = str(report)
    command = [args.flutter, "drive", "--debug", "--no-pub",
               "--driver", "test_driver/store_upgrade_screenshots_2026_10_09_driver.dart",
               "--target", "integration_test/store_upgrade_screenshots_2026_10_09_test.dart",
               "--dart-define-from-file=config/release-contract.production.json",
               "-d", args.device, "--dart-define=SVAULTAI_SCREENSHOT_DEMO=true",
               "--dart-define=BACKEND_BASE_URL=http://127.0.0.1:18082",
               "--dart-define=CRYPTO_WALLET_DEFAULT_NETWORK=ethereum_mainnet",
               "--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_RECEIVE_ENABLED=true",
               "--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_ERC20_RECEIVE_ENABLED=true",
               "--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=true",
               "--dart-define=SVAULTAI_DEMO_CAPTURE_HOLD_MS=3500"]
    restore_display = None
    if args.kind == "android":
        match = re.fullmatch(r"(\d+)x(\d+)", args.android_viewport)
        if not match:
            raise SystemExit("Invalid QA Android viewport")
        width, height = map(int, match.groups())
        if min(width, height) < 320 or max(width, height) > 3840 or max(width, height) > 2 * min(width, height):
            raise SystemExit("QA Android viewport is not Play screenshot compliant")
        restored = False

        def restore_display():
            nonlocal restored
            if restored:
                return
            original = device["original_override_size"] or "reset"
            run([args.adb, "-s", args.device, "shell", "wm", "size", original])
            current = run([args.adb, "-s", args.device, "shell", "wm", "size"], text=True).stdout
            current_override = re.search(r"Override size: (\d+x\d+)", current)
            if (current_override[1] if current_override else None) != device["original_override_size"]:
                raise RuntimeError("QA Android display restore was not verified")
            restored = True
            device["display_restore_verified"] = True

        atexit.register(restore_display)
        run([args.adb, "-s", args.device, "shell", "wm", "size", args.android_viewport])
        device["capture_viewport"] = args.android_viewport
    try:
        process = subprocess.Popen(command, cwd=FRONTEND, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
    except BaseException:
        if restore_display:
            restore_display()
        raise
    screenshots = []
    failures = []
    captured = set()
    timer = threading.Timer(25 * 60, process.terminate)
    timer.start()
    try:
        with (target / "native-run.log").open("w", encoding="utf-8") as log:
            for line in process.stdout:
                log.write(line)
                log.flush()
                # Flutter drive can keep looking for an unrelated VM service
                # after a failed install. Never attach or capture that app.
                if "Application failed to start" in line or "CocoaPods not installed or not in valid state" in line:
                    failures.append({"checkpoint": "native-launch", "error_type": "NativeLaunchFailed"})
                    process.terminate()
                    break
                match = CHECKPOINT.search(line)
                if not match or match[1] in captured:
                    continue
                name = match[1]
                captured.add(name)
                path = target / f"{name}.png"
                try:
                    if args.kind == "ios":
                        run(["xcrun", "simctl", "io", args.device, "screenshot", str(path)])
                    else:
                        pixels = run([args.adb, "-s", args.device, "exec-out", "screencap", "-p"]).stdout
                        path.write_bytes(pixels)
                    metadata = png_info(path)
                    if args.kind == "android" and (
                        min(metadata["width"], metadata["height"]) < 320
                        or max(metadata["width"], metadata["height"]) > 3840
                        or max(metadata["width"], metadata["height"]) > 2 * min(metadata["width"], metadata["height"])
                    ):
                        raise RuntimeError("Captured Android pixels are not Play screenshot compliant")
                    screenshots.append({"checkpoint": name, **metadata})
                    print(f"Captured real {args.label} pixels: {name}", flush=True)
                except Exception as error:
                    failures.append({"checkpoint": name, "error_type": type(error).__name__})
                    process.terminate()
            result = process.wait()
    finally:
        timer.cancel()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
        if restore_display:
            restore_display()
    manifest = {"scope": "real-native-pixels-synthetic-demo-only", "device": device,
                "exit_code": result, "screenshots": screenshots, "capture_failures": failures,
                "production_requests": 0, "account_auth_verified": False,
                "live_holdings_or_transfers_verified": False, "storefront_prompt_verified": False,
                "release_contract": "config/release-contract.production.json",
                "crypto_network": "ethereum_mainnet",
                "mainnet_receive_erc20_receive_send_flags": True,
                "pixel_transformations": "none"}
    (target / "capture-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"exit_code": result, "captured": len(screenshots), "failures": failures,
                      "manifest": str(target / "capture-manifest.json")}), flush=True)
    return result if result else (1 if failures or not screenshots else 0)


if __name__ == "__main__":
    sys.exit(main())
