# SPDX-License-Identifier: MIT
"""Native bounded-tunnel regression suite; no Telegram account or owner secrets."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from prepare_core import prepare

HERE = Path(__file__).resolve().parent
RUST = "1.88.0"
REPORT = HERE / "test-results"
WORK = Path(os.environ["RUNNER_TEMP"]) / "capy-connection-core"


def run(name, arguments, timeout=600):
    process = subprocess.run(arguments, cwd=WORK, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout)
    text = process.stdout + process.stderr
    (REPORT / (name + ".txt")).write_text(text, encoding="utf-8")
    if process.returncode != 0:
        # Only synthetic test fixtures are used. No Telegram API keys or account data exist here.
        print(text[-18000:], flush=True)
        raise RuntimeError("Connection check failed: " + name)
    print("CAPY_CONNECTION_" + name.upper() + "=PASS", flush=True)
    return text


def main():
    REPORT.mkdir(exist_ok=False)
    manifest = prepare(WORK)
    result = {
        "result": "INCOMPLETE",
        "platform": sys.platform,
        "source": manifest,
        "our_source_sha256": {},
        "telegram_account_integration": False,
        "live_telegram_connection_tested": False,
        "vpn_on_off_transition_tested": False,
        "android_abi_compiled": False,
        "external_cloudflare_worker_enabled": False,
        "tls_certificate_validation_disabled": False,
    }
    for path in HERE.rglob("*"):
        if path.is_file() and not path.is_relative_to(REPORT) and "__pycache__" not in path.parts:
            result["our_source_sha256"][path.relative_to(HERE).as_posix()] = hashlib.sha256(
                path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    try:
        version = run("toolchain", ["rustc", "+" + RUST, "--version"], 30).strip()
        if not version.startswith("rustc " + RUST + " "):
            raise ValueError("Unexpected Rust compiler")
        result["rustc"] = version
        common = ["cargo", "+" + RUST]
        test = run("runtime", common + ["test", "--locked", "--no-default-features", "--features", "cli", "--lib", "--bins"])
        suites = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored", test)
        if not suites or any(int(failed) or int(ignored) for _, failed, ignored in suites):
            raise ValueError("Missing, failed or ignored runtime suite")
        result["tests_passed"] = sum(int(passed) for passed, _, _ in suites)
        required = [
            "capy_socks_dc_preface_expires_and_releases_connection",
            "capy_client_limit_rejects_overflow_and_recovers_capacity",
            "capy_socks_domain_controls_are_rejected_before_outbound_connection",
            "capy_event_boundary_escapes_controls_even_from_other_producers",
            "capy_unicode_secret_input_returns_error_instead_of_panicking",
            "embedded_listener_is_loopback_and_refuses_socks",
            "instances_keep_independent_listener_secret_and_shutdown",
            "stop_cancels_incomplete_client_and_is_idempotent",
            "rejected_network_text_cannot_create_terminal_lines_or_escapes",
            "ordinary_russian_diagnostic_is_preserved",
            "capy_native_api_owns_endpoint_and_rejects_revoked_handle",
            "capy_native_api_rejects_null_outputs_and_unknown_handle",
        ]
        for name in required:
            if not re.search(r"::" + re.escape(name) + r" \.\.\. ok", test):
                raise ValueError("Required regression was not executed: " + name)
        result["required_regressions"] = required
        run("clippy", common + ["clippy", "--locked", "--no-default-features", "--features", "cli", "--all-targets", "--", "-D", "warnings"])
        run("staticlib", common + ["build", "--release", "--locked", "--no-default-features", "--lib"])
        library = WORK / "target/release" / ("tglock.lib" if os.name == "nt" else "libtglock.a")
        data = library.read_bytes()
        if not data or len(data) > 512 * 1024 * 1024:
            raise ValueError("Invalid static library output")
        result["static_library"] = {"file": library.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        native_build = WORK.parent / "capy-connection-native-probe"
        run("native_configure", ["cmake", "-S", str(HERE), "-B", str(native_build), "-DCMAKE_BUILD_TYPE=Release",
                                 "-DCAPY_CONNECTION_LIBRARY=" + str(library)], 120)
        run("native_compile", ["cmake", "--build", str(native_build), "--config", "Release", "--parallel", "2"], 120)
        executables = list(native_build.rglob("capy_connection_native_probe.exe" if os.name == "nt" else "capy_connection_native_probe"))
        if len(executables) != 1:
            raise ValueError("Native C++ probe executable missing or ambiguous")
        native = run("native_runtime", [str(executables[0])], 120)
        matched = re.search(r"CAPY_NATIVE_CONNECTION_ABI=PASS (\d+) assertions", native)
        if not matched:
            raise ValueError("Native C++ ABI acceptance marker missing")
        result["cpp_abi_assertions"] = int(matched.group(1))
        for name, expected in manifest["prepared_sha256"].items():
            if hashlib.sha256((WORK / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Prepared source mutated during build: " + name)
        result["prepared_sources_unchanged_after_build"] = True
        result["result"] = "PASS"
    finally:
        (REPORT / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
