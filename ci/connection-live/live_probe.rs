// SPDX-License-Identifier: MIT
// Test-only client. One unauthenticated req_pq_multi per predefined case.
// No DH continuation, authorization key, account, API credential or profile.
use aes::Aes256;
use cipher::{KeyIvInit, StreamCipher};
use rand::{rngs::OsRng, RngCore};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tglock::embedded::EmbeddedTunnel;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;

type AesCtr = ctr::Ctr128BE<Aes256>;
const CASES: [(u16, bool); 8] = [
    (1, false), (2, false), (3, false), (4, false), (5, false),
    (203, false), (2, true), (4, true),
];
const MAX_RESPONSE: usize = 4096;

fn keyed(prekey: &[u8], secret: &[u8; 16]) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(prekey);
    hash.update(secret);
    hash.finalize().into()
}

fn client_init(secret: &[u8; 16], dc: i16) -> ([u8; 64], AesCtr, AesCtr) {
    loop {
        let mut init = [0u8; 64];
        OsRng.fill_bytes(&mut init);
        if init[0] == 0xef || &init[..4] == b"HEAD" || &init[..4] == b"POST"
            || &init[..4] == b"GET " || init[..4] == [0xee; 4] || init[..4] == [0xdd; 4]
            || init[..4] == [0x16, 0x03, 0x01, 0x02] || init[4..8] == [0; 4] {
            continue;
        }
        let key = keyed(&init[8..40], secret);
        let iv: [u8; 16] = init[40..56].try_into().expect("fixed IV range");
        let mut encrypt = AesCtr::new((&key).into(), (&iv).into());
        let reversed: Vec<u8> = init[8..56].iter().rev().copied().collect();
        let reverse_key = keyed(&reversed[..32], secret);
        let reverse_iv: [u8; 16] = reversed[32..].try_into().expect("fixed reverse IV range");
        let decrypt = AesCtr::new((&reverse_key).into(), (&reverse_iv).into());
        let mut wire = init;
        encrypt.apply_keystream(&mut wire); // Advance the outgoing stream by 64 bytes.
        let mut plain_tail = [0u8; 8];
        plain_tail[..4].fill(0xdd);
        plain_tail[4..6].copy_from_slice(&dc.to_le_bytes());
        OsRng.fill_bytes(&mut plain_tail[6..]);
        for i in 0..8 { init[56 + i] ^= plain_tail[i] ^ wire[56 + i]; }
        return (init, encrypt, decrypt);
    }
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, &'static str> {
    let part = bytes.get(offset..offset + 4).ok_or("Truncated integer")?;
    Ok(u32::from_le_bytes(part.try_into().map_err(|_| "Invalid integer")?))
}

fn validate_res_pq(packet: &[u8], nonce: &[u8; 16]) -> Result<usize, &'static str> {
    if packet.len() < 20 || packet.len() > MAX_RESPONSE || packet[..8] != [0; 8] {
        return Err("Invalid unauthenticated message envelope");
    }
    let message_id = u64::from_le_bytes(packet[8..16].try_into().map_err(|_| "Invalid message id")?);
    if message_id & 1 != 1 { return Err("Not a server message id"); }
    let body_size = read_u32(packet, 16)? as usize;
    if body_size < 56 || body_size % 4 != 0 || 20 + body_size > packet.len()
        || packet.len() - 20 - body_size > 15 {
        return Err("Invalid body length or transport padding");
    }
    let body = &packet[20..20 + body_size];
    if read_u32(body, 0)? != 0x0516_2463 || body.get(4..20) != Some(nonce.as_slice()) {
        return Err("Expected resPQ with this fresh request nonce");
    }
    if body[20..36] == [0; 16] { return Err("Missing server nonce"); }
    let pq_size = *body.get(36).ok_or("Missing PQ string")? as usize;
    if !(1..=8).contains(&pq_size) { return Err("Invalid bounded PQ string"); }
    let next = 36 + (1 + pq_size + 3) / 4 * 4;
    if read_u32(body, next)? != 0x1cb5_c415 { return Err("Missing fingerprint vector"); }
    let fingerprints = read_u32(body, next + 4)? as usize;
    if !(1..=32).contains(&fingerprints) || next + 8 + fingerprints * 8 != body.len() {
        return Err("Invalid bounded fingerprint vector");
    }
    Ok(fingerprints)
}

async fn round_trip(engine: &EmbeddedTunnel, dc: u16, media: bool) -> Result<usize, String> {
    let secret = tglock::mtproto::parse_secret(&engine.proxy_secret())
        .ok_or("Invalid in-memory routing token")?;
    let signed_dc = if media { -(dc as i16) } else { dc as i16 };
    let (init, mut encrypt, mut decrypt) = client_init(&secret, signed_dc);
    let mut nonce = [0u8; 16];
    OsRng.fill_bytes(&mut nonce);
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| "Clock unavailable")?;
    let fraction = ((u64::from(now.subsec_nanos()) << 32) / 1_000_000_000) & !3;
    let message_id = (now.as_secs() << 32) | fraction;
    let mut payload = Vec::with_capacity(40);
    payload.extend_from_slice(&[0; 8]);
    payload.extend_from_slice(&message_id.to_le_bytes());
    payload.extend_from_slice(&20u32.to_le_bytes());
    payload.extend_from_slice(&0xbe7e_8ef1u32.to_le_bytes());
    payload.extend_from_slice(&nonce);
    let mut packet = Vec::with_capacity(56);
    packet.extend_from_slice(&52u32.to_le_bytes()); // 40 message bytes + 12 random padding bytes.
    packet.extend_from_slice(&payload);
    let mut padding = [0u8; 12];
    OsRng.fill_bytes(&mut padding);
    packet.extend_from_slice(&padding);
    encrypt.apply_keystream(&mut packet);
    let mut client = TcpStream::connect(engine.address()).await.map_err(|e| e.to_string())?;
    client.write_all(&init).await.map_err(|e| e.to_string())?;
    client.write_all(&packet).await.map_err(|e| e.to_string())?;
    let mut size = [0u8; 4];
    client.read_exact(&mut size).await.map_err(|e| e.to_string())?;
    decrypt.apply_keystream(&mut size);
    let count = u32::from_le_bytes(size) as usize;
    if !(20..=MAX_RESPONSE).contains(&count) { return Err("Invalid bounded reply frame length".into()); }
    let mut response = vec![0u8; count];
    client.read_exact(&mut response).await.map_err(|e| e.to_string())?;
    decrypt.apply_keystream(&mut response);
    validate_res_pq(&response, &nonce).map_err(str::to_owned)
}

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    let mut engine = match EmbeddedTunnel::start().await {
        Ok(value) if value.address().ip().is_loopback() => value,
        _ => { eprintln!("Embedded loopback transport did not start"); std::process::exit(1); }
    };
    let mut records = Vec::new();
    let mut passed = true;
    for (dc, media) in CASES {
        let start = Instant::now();
        let result = tokio::time::timeout(Duration::from_secs(60), round_trip(&engine, dc, media)).await;
        let (ok, fingerprints, error) = match result {
            Ok(Ok(count)) => (true, Some(count), None),
            Ok(Err(reason)) => (false, None, Some(tglock::diagnostic::single_line(&reason).chars().take(300).collect::<String>())),
            Err(_) => (false, None, Some("Case deadline exceeded".to_owned())),
        };
        passed &= ok;
        let counters = engine.counters();
        let record = json!({"requested_dc": dc, "media_route": media,
            "fresh_nonce_res_pq_verified": ok, "fingerprint_count": fingerprints,
            "round_trip_milliseconds": start.elapsed().as_millis(),
            "route_code": if ok { Some(counters[4]) } else { None }, "error": error});
        println!("CAPY_LIVE_OBSERVATION={record}");
        records.push(record);
    }
    let stopped = engine.stop().await.is_ok() && !engine.is_running();
    passed &= stopped;
    println!("CAPY_LIVE_RESULT={}", json!({"result": if passed { "PASS" } else { "FAIL" },
        "observations": records, "embedded_transport_stopped": stopped,
        "telegram_account_used": false, "authorization_key_created": false,
        "external_proxy_or_worker_configured": false, "tls_validation_disabled": false,
        "vpn_transition_tested": false, "native_client_ui_tested": false,
        "scope": "Unauthenticated req_pq_multi/resPQ through the real frozen embedded transport from this CI network only."}));
    if !passed { std::process::exit(1); }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn reference(nonce: &[u8; 16]) -> Vec<u8> {
        let mut packet = vec![0; 8];
        packet.extend_from_slice(&1u64.to_le_bytes());
        packet.extend_from_slice(&64u32.to_le_bytes());
        packet.extend_from_slice(&0x0516_2463u32.to_le_bytes());
        packet.extend_from_slice(nonce);
        packet.extend_from_slice(&[4; 16]);
        packet.extend_from_slice(&[8, 1, 2, 3, 4, 5, 6, 7, 8, 0, 0, 0]);
        packet.extend_from_slice(&0x1cb5_c415u32.to_le_bytes());
        packet.extend_from_slice(&1u32.to_le_bytes());
        packet.extend_from_slice(&7u64.to_le_bytes());
        packet
    }

    #[test]
    fn response_parser_rejects_wrong_nonce_and_malformed_lengths() {
        let nonce = [9; 16];
        let valid = reference(&nonce);
        assert_eq!(validate_res_pq(&valid, &nonce), Ok(1));
        assert!(validate_res_pq(&valid, &[8; 16]).is_err());
        for size in 0..valid.len() { assert!(validate_res_pq(&valid[..size], &nonce).is_err()); }
        for offset in [0, 8, 16, 20, 56, 68, 72] {
            let mut broken = valid.clone(); broken[offset] ^= 0xff;
            assert!(validate_res_pq(&broken, &nonce).is_err());
        }
        let mut padded = valid.clone(); padded.extend_from_slice(&[0; 15]);
        assert_eq!(validate_res_pq(&padded, &nonce), Ok(1));
        padded.push(0); assert!(validate_res_pq(&padded, &nonce).is_err());
    }

    #[test]
    fn test_client_init_matches_production_parser_and_streams() {
        let secret = [23; 16];
        for (dc, media) in CASES {
            let signed = if media { -(dc as i16) } else { dc as i16 };
            let (init, mut encrypt, _) = client_init(&secret, signed);
            let mut parsed = tglock::mtproto::parse_client_init(&init, &secret).expect("production parser");
            assert_eq!(parsed.dc, dc); assert_eq!(parsed.media, media);
            let plain = b"synthetic framing regression, not a Telegram response";
            let mut encoded = plain.to_vec(); encrypt.apply_keystream(&mut encoded);
            parsed.crypto.client_to_telegram(&mut encoded);
            let key: [u8; 32] = parsed.relay_init[8..40].try_into().unwrap();
            let iv: [u8; 16] = parsed.relay_init[40..56].try_into().unwrap();
            let mut relay_decrypt = AesCtr::new((&key).into(), (&iv).into());
            relay_decrypt.apply_keystream(&mut [0; 64]); relay_decrypt.apply_keystream(&mut encoded);
            assert_eq!(encoded, plain);
        }
    }
}
