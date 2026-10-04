// SPDX-License-Identifier: MIT
//! Android TLS uses bundled public roots, verified hostnames and an explicit
//! crypto provider. No system OpenSSL, custom verifier or accept-all mode.
use rustls::{ClientConfig, RootCertStore};
use std::sync::{Arc, OnceLock};

fn with_roots(roots: RootCertStore) -> Result<Arc<ClientConfig>, String> {
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let configuration = ClientConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .map_err(|error| format!("TLS configuration: {error}"))?
        .with_root_certificates(roots)
        .with_no_client_auth();
    Ok(Arc::new(configuration))
}

pub(crate) fn configuration() -> Result<Arc<ClientConfig>, String> {
    static CONFIGURATION: OnceLock<Result<Arc<ClientConfig>, String>> = OnceLock::new();
    CONFIGURATION
        .get_or_init(|| {
            let roots = RootCertStore {
                roots: webpki_roots::TLS_SERVER_ROOTS.to_vec(),
            };
            with_roots(roots)
        })
        .clone()
}

#[cfg(test)]
pub(crate) fn test_configuration(roots: RootCertStore) -> Arc<ClientConfig> {
    with_roots(roots).expect("synthetic certificate configuration")
}
