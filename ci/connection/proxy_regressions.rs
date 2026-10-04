// Included inside upstream proxy.rs's test module after guarded preparation.

#[tokio::test(start_paused = true)]
async fn capy_socks_dc_preface_expires_and_releases_connection() {
    let stats = Stats::new();
    let (port, server) = start_proxy(stats.clone(), false).await;
    let mut client = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
    client.write_all(&[5, 1, 0]).await.unwrap();
    let mut greeting = [0; 2];
    client.read_exact(&mut greeting).await.unwrap();
    assert_eq!(greeting, [5, 0]);
    client.write_all(&[5, 1, 0, 1, 149, 154, 167, 51, 1, 187]).await.unwrap();
    let mut success = [0; 10];
    client.read_exact(&mut success).await.unwrap();
    assert_eq!(success[1], 0);
    tokio::time::advance(IO_TIMEOUT + Duration::from_secs(1)).await;
    let mut byte = [0];
    assert_eq!(client.read(&mut byte).await.unwrap(), 0);
    wait_until("expired init releases task", || stats.active.load(Ordering::Relaxed) == 0).await;
    stats.stop();
    server.await.unwrap().unwrap();
}

#[tokio::test]
async fn capy_client_limit_rejects_overflow_and_recovers_capacity() {
    let stats = Stats::new();
    let (port, server) = start_proxy(stats.clone(), false).await;
    let mut held = Vec::new();
    for _ in 0..MAX_CLIENTS {
        held.push(TcpStream::connect(("127.0.0.1", port)).await.unwrap());
    }
    wait_until("capacity reached", || stats.active.load(Ordering::Relaxed) == MAX_CLIENTS as u32).await;
    let mut overflow = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
    let mut byte = [0];
    let closed = tokio::time::timeout(Duration::from_secs(2), overflow.read(&mut byte)).await.unwrap();
    assert!(matches!(closed, Ok(0) | Err(_)));
    assert_eq!(stats.active.load(Ordering::Relaxed), MAX_CLIENTS as u32);
    held.pop();
    wait_until("capacity freed", || stats.active.load(Ordering::Relaxed) == (MAX_CLIENTS - 1) as u32).await;
    held.push(TcpStream::connect(("127.0.0.1", port)).await.unwrap());
    wait_until("new client admitted", || stats.active.load(Ordering::Relaxed) == MAX_CLIENTS as u32).await;
    stats.stop();
    server.await.unwrap().unwrap();
    assert_eq!(stats.active.load(Ordering::Relaxed), 0);
    drop(held);
}

#[tokio::test]
async fn capy_socks_domain_controls_are_rejected_before_outbound_connection() {
    let stats = Stats::new();
    let (port, server) = start_proxy(stats.clone(), false).await;
    let mut client = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
    client.write_all(&[5, 1, 0]).await.unwrap();
    client.read_exact(&mut [0; 2]).await.unwrap();
    let domain = b"example\nFORGED\x1b[2J";
    let mut request = vec![5, 1, 0, 3, domain.len() as u8];
    request.extend_from_slice(domain);
    request.extend_from_slice(&443u16.to_be_bytes());
    client.write_all(&request).await.unwrap();
    let mut byte = [0];
    let result = tokio::time::timeout(Duration::from_secs(2), client.read(&mut byte)).await.unwrap();
    assert!(matches!(result, Ok(0) | Err(_)));
    wait_until("invalid request released", || stats.unknown_clients.load(Ordering::Relaxed) > 0).await;
    let events = stats.drain_events();
    assert!(!events.is_empty());
    assert!(events.iter().all(|s| !s.chars().any(char::is_control)));
    assert!(events.iter().all(|s| !s.contains("FORGED")));
    stats.stop();
    server.await.unwrap().unwrap();
}

#[test]
fn capy_event_boundary_escapes_controls_even_from_other_producers() {
    let stats = Stats::new();
    stats.note("host\nFORGED\r\u{1b}[2J");
    let events = stats.drain_events();
    assert_eq!(events.len(), 1);
    assert!(events[0].contains("\\nFORGED\\r"));
    assert!(!events[0].chars().any(char::is_control));
}

#[test]
fn capy_unicode_secret_input_returns_error_instead_of_panicking() {
    // 32 bytes, with a three-byte character crossing a hexadecimal slice boundary.
    let malformed = "€".repeat(10) + "aa";
    assert_eq!(malformed.len(), 32);
    assert!(crate::mtproto::parse_secret(&malformed).is_none());
    assert!(crate::mtproto::parse_secret(&("dd".to_owned() + &malformed)).is_none());
}
