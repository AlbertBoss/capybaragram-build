# SPDX-License-Identifier: MIT
"""Prepare a bounded, headless copy; never modify the pinned upstream snapshot."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "upstream"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise ValueError("Pinned transformation anchor differs: " + label)
    return text.replace(old, new, 1)


def prepare(destination):
    pins = json.loads((HERE / "source-pins.json").read_text(encoding="utf-8"))
    if pins["revision"] != "8617d25f3ae9bddb158a6703d1d02e453ebd39ba":
        raise ValueError("Unreviewed upstream revision")
    actual = set()
    for item in VENDOR.rglob("*"):
        if item.is_symlink():
            raise ValueError("Symlink in source snapshot")
        if item.is_file():
            actual.add(item.relative_to(VENDOR).as_posix())
    if actual != set(pins["source_files"]):
        raise ValueError("Pinned source inventory differs")
    source = {}
    for name, expected in pins["source_files"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("Unsafe source name")
        data = (VENDOR / name).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if digest(data) != expected["sha256"] or blob != expected["git_blob"]:
            raise ValueError("Pinned source bytes differ: " + name)
        source[name] = data

    # Validate all anchors in memory before creating the output directory.
    cargo = source["Cargo.toml"].decode("utf-8")
    cargo = replace_once(cargo, 'path = "src/lib.rs"\n',
                         'path = "src/lib.rs"\ncrate-type = ["rlib", "staticlib"]\n', "static library")
    source["Cargo.toml"] = cargo.encode("utf-8")
    source["src/lib.rs"] += b"\npub mod diagnostic;\npub mod embedded;\npub mod native_api;\n"

    proxy = source["src/proxy.rs"].decode("utf-8")
    proxy = replace_once(proxy, "const INIT_LEN: usize = 64;\n",
                         "const INIT_LEN: usize = 64;\nconst MAX_CLIENTS: usize = 128;\n", "client cap")
    proxy = replace_once(proxy, "        let message = message.into();\n",
                         "        let message = crate::diagnostic::single_line(&message.into());\n", "event boundary")
    serve_old = '''pub async fn serve(
    stats: Arc<Stats>,
    listener: TcpListener,
    allow_direct: bool,
) -> Result<(), String> {
    stats.running.store(true, Ordering::SeqCst);
    let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);
    *stats.shutdown.lock().unwrap() = Some(shutdown_tx);
    let mut tasks = tokio::task::JoinSet::new();
'''
    serve_new = '''pub async fn serve(
    stats: Arc<Stats>,
    listener: TcpListener,
    allow_direct: bool,
) -> Result<(), String> {
    serve_policy(stats, listener, allow_direct, true).await
}

/// Embedded clients never expose unauthenticated SOCKS or arbitrary forwarding.
pub async fn serve_mtproto_only(stats: Arc<Stats>, listener: TcpListener) -> Result<(), String> {
    serve_policy(stats, listener, false, false).await
}

struct ClientLease {
    stats: Arc<Stats>,
    _permit: tokio::sync::OwnedSemaphorePermit,
}

impl Drop for ClientLease {
    fn drop(&mut self) {
        self.stats.active.fetch_sub(1, Ordering::Relaxed);
    }
}

async fn serve_policy(
    stats: Arc<Stats>,
    listener: TcpListener,
    allow_direct: bool,
    allow_socks: bool,
) -> Result<(), String> {
    let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);
    *stats.shutdown.lock().unwrap() = Some(shutdown_tx);
    // Publish readiness only after shutdown is available.
    stats.running.store(true, Ordering::SeqCst);
    let admission = Arc::new(tokio::sync::Semaphore::new(MAX_CLIENTS));
    let mut tasks = tokio::task::JoinSet::new();
'''
    proxy = replace_once(proxy, serve_old, serve_new, "server policy and readiness")
    accept_old = '''                        let s = stats.clone();
                        s.note_peer(peer);
                        s.active.fetch_add(1, Ordering::Relaxed);
                        s.total.fetch_add(1, Ordering::Relaxed);
                        tasks.spawn(async move {
                            let _ = handle(stream, &s, allow_direct).await;
                            s.active.fetch_sub(1, Ordering::Relaxed);
                        });'''
    accept_new = '''                        let Ok(permit) = admission.clone().try_acquire_owned() else {
                            stats.note("Connection capacity reached; client closed");
                            drop(stream);
                            continue;
                        };
                        let s = stats.clone();
                        s.note_peer(peer);
                        s.active.fetch_add(1, Ordering::Relaxed);
                        s.total.fetch_add(1, Ordering::Relaxed);
                        // Own the lease before scheduling, including abort-before-first-poll.
                        let lease = ClientLease { stats: s.clone(), _permit: permit };
                        tasks.spawn(async move {
                            let _lease = lease;
                            let _ = handle(stream, &s, allow_direct, allow_socks).await;
                        });'''
    proxy = replace_once(proxy, accept_old, accept_new, "bounded admission and cancellation lease")
    proxy = replace_once(proxy, '''                    Err(error) => {
                        stats.running.store(false, Ordering::SeqCst);
                        return Err(format!("Accept failed: {}", error));
                    }''', '''                    Err(_) => {
                        stats.note("Listener temporarily unavailable; retrying");
                        tokio::select! {
                            _ = tokio::time::sleep(Duration::from_millis(250)) => {},
                            _ = shutdown_rx.changed() => break,
                        }
                    }''', "bounded accept retry")
    proxy = replace_once(proxy, '''    s: TcpStream,
    stats: &Stats,
    allow_direct: bool,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    match detect_protocol(&s, stats).await? {
        Protocol::Socks5 => handle_socks5(s, stats, allow_direct).await,''', '''    s: TcpStream,
    stats: &Stats,
    allow_direct: bool,
    allow_socks: bool,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    match detect_protocol(&s, stats).await? {
        Protocol::Socks5 if allow_socks => handle_socks5(s, stats, allow_direct).await,
        Protocol::Socks5 => Err("SOCKS is disabled for embedded transport".into()),''', "embedded protocol policy")
    proxy = replace_once(proxy, '''        let mut init = [0u8; 64];
        s.read_exact(&mut init).await?;''', '''        let mut init = [0u8; 64];
        match tokio::time::timeout(IO_TIMEOUT, s.read_exact(&mut init)).await {
            Ok(result) => { result?; }
            Err(_) => {
                stats.note_silent_client(peer, "не прислал MTProto-init после SOCKS5");
                return Err("SOCKS5 MTProto init timeout".into());
            }
        }''', "post-SOCKS init deadline")
    proxy = replace_once(proxy, "            String::from_utf8(domain)?\n", '''            let domain = String::from_utf8(domain)?;
            if !valid_socks_domain(&domain) {
                return Err("invalid SOCKS5 domain syntax".into());
            }
            domain
''', "untrusted domain validation")
    proxy = replace_once(proxy, "async fn read_socks5_request<S>(\n", '''fn valid_socks_domain(domain: &str) -> bool {
    let hostname = domain.strip_suffix('.').unwrap_or(domain);
    !hostname.is_empty() && hostname.len() <= 253 && hostname.is_ascii()
        && hostname.split('.').all(|label| {
            !label.is_empty() && label.len() <= 63
                && !label.starts_with('-') && !label.ends_with('-')
                && label.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        })
}

async fn read_socks5_request<S>(
''', "domain validator")
    if not proxy.endswith("}\n") or proxy.count("mod tests {") != 1:
        raise ValueError("Unexpected upstream test module")
    proxy = proxy[:-2] + '    include!("capy_proxy_regressions.rs");\n}\n'
    source["src/proxy.rs"] = proxy.encode("utf-8")

    mtproto = source["src/mtproto.rs"].decode("utf-8")
    mtproto = replace_once(mtproto, "    if value.len() != 32 {\n",
                           "    if value.len() != 32 || !value.bytes().all(|b| b.is_ascii_hexdigit()) {\n", "UTF-8 safe secret parser")
    source["src/mtproto.rs"] = mtproto.encode("utf-8")
    cli = source["src/bin/cli.rs"].decode("utf-8")
    cli = replace_once(cli, "    let mut out = std::io::stdout().lock();\n",
                       "    let text = tglock::diagnostic::single_line(text);\n    let mut out = std::io::stdout().lock();\n", "CLI diagnostics")
    source["src/bin/cli.rs"] = cli.encode("utf-8")
    additions = {
        "diagnostic.rs": "src/diagnostic.rs",
        "embedded.rs": "src/embedded.rs",
        "native_api.rs": "src/native_api.rs",
        "proxy_regressions.rs": "src/capy_proxy_regressions.rs",
    }
    for name, target in additions.items():
        path = HERE / name
        if path.is_symlink():
            raise ValueError("Symlink in own source")
        source[target] = path.read_bytes()

    destination = Path(destination)
    # An existing directory is never deleted, reused or overwritten.
    if destination.exists() or destination.is_symlink():
        raise ValueError("Prepared destination already exists")
    if any(parent.is_symlink() for parent in destination.parents):
        raise ValueError("Symlink in destination ancestry")
    if destination.resolve().is_relative_to(HERE):
        raise ValueError("Prepared copy must be outside the published source package")
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in source.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        "upstream_repository": pins["repository"],
        "upstream_revision": pins["revision"],
        "upstream_sha256": {name: value["sha256"] for name, value in pins["source_files"].items()},
        "prepared_sha256": {name: digest(data) for name, data in source.items()},
        "cargo_lock_unchanged": source["Cargo.lock"] == (VENDOR / "Cargo.lock").read_bytes(),
        "gui_enabled": False,
        "telegram_account_integration": False,
    }
    (destination / "capy-source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    result = prepare(arguments.destination)
    print("CAPY_CONNECTION_PREPARED=" + str(len(result["prepared_sha256"])) + " PINNED_LOCK=UNCHANGED")
