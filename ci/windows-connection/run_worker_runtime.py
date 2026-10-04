# SPDX-License-Identifier: MIT
"""Compile actual native controller against the previously verified transport."""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "connection"
WORK = Path(os.environ["RUNNER_TEMP"]) / "capy-native-connection-worker"
REPORT = HERE / "test-results"
RUST = "1.88.0"


def run(name, arguments, timeout=600):
    process = subprocess.run(arguments, cwd=WORK, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    text = process.stdout + process.stderr
    (REPORT / (name + ".txt")).write_text(text, encoding="utf-8")
    if process.returncode:
        print(text[-16000:], flush=True)
        raise RuntimeError("Native connection worker failed: " + name)
    print("CAPY_CONNECTION_WORKER_" + name.upper() + "=PASS", flush=True)
    return text


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    pins = json.loads((HERE / "core-provenance.json").read_text(encoding="utf-8"))
    files = {path.relative_to(CORE).as_posix(): hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
             for path in CORE.rglob("*") if path.is_file() and "__pycache__" not in path.parts and "test-results" not in path.parts}
    if files != pins["core_source_sha256"]:
        raise ValueError("Transport source differs from verified Windows/Linux revision")
    spec = importlib.util.spec_from_file_location("capy_connection_prepare", CORE / "prepare_core.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = module.prepare(WORK)
    if manifest != pins["prepared_source"]:
        raise ValueError("Prepared transport differs from verified revision")
    REPORT.mkdir(exist_ok=False)
    result = {"result": "INCOMPLETE", "platform": sys.platform, "transport_proof_run": pins["proof_run"],
              "telegram_client_compiled": False, "telegram_account_tested": False,
              "our_source_sha256": {path.name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                                    for path in HERE.iterdir() if path.is_file()}}
    try:
        version = run("toolchain", ["rustc", "+" + RUST, "--version"], 30).strip()
        if not version.startswith("rustc " + RUST + " "):
            raise ValueError("Unexpected Rust compiler")
        run("transport_compile", ["cargo", "+" + RUST, "build", "--release", "--locked", "--no-default-features", "--lib"])
        library = WORK / "target/release" / ("tglock.lib" if os.name == "nt" else "libtglock.a")
        native = WORK.parent / "capy-native-connection-worker-build"
        run("configure", ["cmake", "-S", str(HERE), "-B", str(native), "-DCMAKE_BUILD_TYPE=Release",
                          "-DCAPY_CONNECTION_LIBRARY=" + str(library), "-DCAPY_CONNECTION_HEADER_DIR=" + str(CORE)], 120)
        run("compile", ["cmake", "--build", str(native), "--config", "Release", "--parallel", "2"], 120)
        names = list(native.rglob("capy_connection_worker_probe.exe" if os.name == "nt" else "capy_connection_worker_probe"))
        if len(names) != 1:
            raise ValueError("Native worker executable missing or ambiguous")
        runtime = run("runtime", [str(names[0])], 30)
        if not re.search(r"CAPY_CONNECTION_WORKER=PASS 13 assertions; 2000 rapid requests; bounded UI queue", runtime):
            raise ValueError("Worker acceptance marker missing")
        result.update(result="PASS", assertions=13, rapid_requests=2000, stale_ui_callback_rejected=True,
                      pending_commands_bounded=True, pending_ui_dispatch_bounded=True, destructor_cancels_ui_delivery=True)
    finally:
        (REPORT / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
