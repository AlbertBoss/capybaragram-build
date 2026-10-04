# SPDX-License-Identifier: MIT
"""Separate Android TLS variant; keep the previously proven Windows core intact."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / 'connection'


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Android TLS transformation anchor differs: ' + old[:80])
    return text.replace(old, new, 1)


def plan(bootstrap=False):
    pins = json.loads((HERE / 'source-provenance.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(CORE).as_posix(): digest(p.read_bytes())
              for p in CORE.rglob('*') if p.is_file() and '__pycache__' not in p.parts
              and 'test-results' not in p.parts}
    if actual != pins['core_source_sha256']:
        raise ValueError('Previously verified base core differs')
    for name, expected in pins['payload_sha256'].items():
        path = HERE / name
        if path.is_symlink() or digest(path.read_bytes()) != expected:
            raise ValueError('Android TLS payload differs: ' + name)
    spec = importlib.util.spec_from_file_location('capy_android_base', CORE / 'prepare_core.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='capy-android-source-') as temporary:
        stage = Path(temporary) / 'source'
        base = module.prepare(stage)
        if base != pins['prepared_base']:
            raise ValueError('Prepared base core differs')
        source = {name: (stage / name).read_bytes() for name in base['prepared_sha256']}
    source['Cargo.toml'] = (HERE / 'Cargo.android.toml').read_bytes().replace(b'\r\n', b'\n')
    # The explicitly named bootstrap workflow generates a reviewable lock only.
    # Production preparation refuses to resolve or fetch new dependency versions.
    if bootstrap:
        source.pop('Cargo.lock')
    else:
        lock = HERE / 'Cargo.lock'
        if not pins.get('cargo_lock_sha256') or lock.is_symlink() or digest(lock.read_bytes()) != pins['cargo_lock_sha256']:
            raise ValueError('Reviewed Android Cargo.lock is required')
        source['Cargo.lock'] = lock.read_bytes().replace(b'\r\n', b'\n')
    source['.cargo/config.toml'] = b'[resolver]\nincompatible-rust-versions = "fallback"\n'
    source['src/lib.rs'] += b'\npub(crate) mod android_tls;\n'
    source['src/android_tls.rs'] = (HERE / 'android_tls.rs').read_bytes().replace(b'\r\n', b'\n')
    source['src/capy_tls_regressions.rs'] = (HERE / 'tls_regressions.rs').read_bytes().replace(b'\r\n', b'\n')
    transport = source['src/transport.rs'].decode('utf-8')
    old = 'async fn connect_route(route: &Route) -> Result<TelegramWebSocket, String> {\n'
    transport = once(transport, old, old +
        '    connect_route_with_tls(route, crate::android_tls::configuration()?).await\n}\n\n'
        'async fn connect_route_with_tls(\n    route: &Route,\n'
        '    tls: std::sync::Arc<rustls::ClientConfig>,\n) -> Result<TelegramWebSocket, String> {\n')
    transport = once(transport,
        "    // The URI host remains the real Telegram hostname even when the TCP socket\n"
        "    // is opened to a pinned IP. Native TLS therefore validates Telegram's\n"
        "    // certificate and sends the correct SNI.\n"
        '    let tls = native_tls::TlsConnector::new().map_err(|error| format!("TLS setup: {error}"))?;\n'
        '    let connector = tokio_tungstenite::Connector::NativeTls(tls);\n',
        "    // Preserve the Telegram URI hostname/SNI when dialing a pinned IP.\n"
        "    // Rustls verifies both the chain and the hostname using public roots.\n"
        '    let connector = tokio_tungstenite::Connector::Rustls(tls);\n')
    if not transport.endswith('}\n') or transport.count('mod tests {') != 1:
        raise ValueError('Unexpected transport test module')
    transport = transport[:-2] + '    include!("capy_tls_regressions.rs");\n}\n'
    source['src/transport.rs'] = transport.encode('utf-8')
    return source, base


def prepare(destination, bootstrap=False):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
        raise ValueError('Destination exists or has symlink ancestry')
    if destination.resolve().is_relative_to(HERE.parent):
        raise ValueError('Prepared copy must be outside the published CI source')
    source, base = plan(bootstrap)
    # All source/payload/anchor checks run before writing any destination file.
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in source.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {'prepared_sha256': {n: digest(d) for n, d in source.items()},
                'base_revision': base['upstream_revision'], 'android_tls': 'Rustls 0.23.45 / ring 0.17.14',
                'reviewed_lock': not bootstrap, 'live_telegram_tested': False}
    (destination / 'capy-android-source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--bootstrap-lock-only', action='store_true')
    args = parser.parse_args()
    manifest = prepare(args.destination, args.bootstrap_lock_only)
    print('CAPY_ANDROID_CONNECTION_PREPARED=' + str(len(manifest['prepared_sha256'])))
