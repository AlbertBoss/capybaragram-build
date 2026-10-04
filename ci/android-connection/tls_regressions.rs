// SPDX-License-Identifier: MIT
// Included inside the preserved transport test module: exercises the actual
// production WebSocket connection path, not a mock verifier.
async fn capy_tls_fixture(hostname: &str, trust_test_certificate: bool) -> bool {
    use futures_util::{SinkExt, StreamExt};
    use rustls::pki_types::{PrivateKeyDer, PrivatePkcs8KeyDer};
    use rustls::{RootCertStore, ServerConfig};
    use std::sync::Arc;
    use tokio::net::TcpListener;
    use tokio_tungstenite::tungstenite::Message;

    let certified = rcgen::generate_simple_self_signed(vec!["capy-test.invalid".to_owned()])
        .expect("test certificate");
    let certificate = certified.cert.der().clone();
    let private_key = PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(
        certified.signing_key.serialize_der(),
    ));
    let server_config = ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .expect("server TLS versions")
    .with_no_client_auth()
    .with_single_cert(vec![certificate.clone()], private_key)
    .expect("server certificate");
    let acceptor = tokio_rustls::TlsAcceptor::from(Arc::new(server_config));
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("test listener");
    let port = listener.local_addr().expect("test address").port();
    let server = tokio::spawn(async move {
        let (socket, _) = listener.accept().await.expect("test TCP accept");
        let Ok(tls) = acceptor.accept(socket).await else { return false; };
        let Ok(mut websocket) = tokio_tungstenite::accept_hdr_async(tls,
            |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
             mut response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                assert_eq!(request.headers().get("Sec-WebSocket-Protocol").expect("binary request"), "binary");
                response.headers_mut().insert("Sec-WebSocket-Protocol", "binary".parse().expect("binary header"));
                Ok(response)
            },
        ).await else { return false; };
        websocket.send(Message::Binary(vec![7, 11, 19])).await.is_ok()
    });
    let client_config = if trust_test_certificate {
        let mut roots = RootCertStore::empty();
        roots.add(certificate).expect("synthetic trust anchor");
        crate::android_tls::test_configuration(roots)
    } else {
        crate::android_tls::configuration().expect("production root store")
    };
    let route = Route {
        connect_host: "127.0.0.1".to_owned(),
        websocket_host: format!("{hostname}:{port}"),
        path: "/apiws".to_owned(),
        kind: RouteKind::TelegramIp,
        port,
        secure: true,
    };
    let connected = match connect_route_with_tls(&route, client_config).await {
        Ok(mut websocket) => {
            let received = tokio::time::timeout(Duration::from_secs(2), websocket.next())
                .await.expect("synthetic payload timeout")
                .expect("synthetic payload present").expect("synthetic payload valid");
            assert_eq!(received, Message::Binary(vec![7, 11, 19]));
            true
        }
        Err(_) => false,
    };
    let server_accepted = tokio::time::timeout(Duration::from_secs(5), server)
        .await.expect("test server stopped").expect("test server did not panic");
    assert_eq!(server_accepted, connected);
    connected
}

#[tokio::test]
async fn capy_android_tls_valid_hostname_and_trusted_certificate() {
    assert!(capy_tls_fixture("capy-test.invalid", true).await);
}

#[tokio::test]
async fn capy_android_tls_wrong_hostname_is_rejected() {
    assert!(!capy_tls_fixture("different-test.invalid", true).await);
}

#[tokio::test]
async fn capy_android_tls_production_roots_reject_self_signed_peer() {
    assert!(!capy_tls_fixture("capy-test.invalid", false).await);
}
