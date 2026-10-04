//! CapybaraGram-only transport. No filesystem, GUI, URL handler or external Worker.
//! Each instance owns an independent in-memory proxy secret and shutdown task.
use crate::{config::ListenConfig, mtproto, proxy};
use std::net::SocketAddr;
use std::sync::{atomic::Ordering, Arc};
use std::time::Duration;
use tokio::task::JoinHandle;

pub struct EmbeddedTunnel {
    address: SocketAddr,
    stats: Arc<proxy::Stats>,
    task: Option<JoinHandle<Result<(), String>>>,
}

impl EmbeddedTunnel {
    pub async fn start() -> Result<Self, String> {
        let stats = proxy::Stats::with_secret(mtproto::generate_secret());
        let listener = proxy::bind(ListenConfig::loopback(0).with_allow_direct(false)).await?;
        let address = listener.local_addr().map_err(|_| "Cannot inspect listener".to_owned())?;
        let task_stats = stats.clone();
        let task = tokio::spawn(async move { proxy::serve_mtproto_only(task_stats, listener).await });
        let mut engine = Self { address, stats, task: Some(task) };
        let ready = tokio::time::timeout(Duration::from_secs(2), async {
            while !engine.is_running() {
                if engine.task.as_ref().is_some_and(JoinHandle::is_finished) {
                    return Err("Transport stopped during startup".to_owned());
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
            Ok(())
        }).await;
        match ready {
            Ok(Ok(())) => Ok(engine),
            _ => {
                let _ = engine.stop().await;
                Err("Transport did not become ready".to_owned())
            }
        }
    }

    pub fn address(&self) -> SocketAddr { self.address }

    /// A local routing token, not a Telegram account/session credential.
    /// Caller must keep it in process memory and never print it in diagnostics.
    pub fn proxy_secret(&self) -> String { self.stats.telegram_secret() }

    pub fn is_running(&self) -> bool { self.stats.running.load(Ordering::SeqCst) }

    pub fn counters(&self) -> [u32; 5] {
        [
            self.stats.active.load(Ordering::Relaxed),
            self.stats.ws.load(Ordering::Relaxed),
            self.stats.ws_failures.load(Ordering::Relaxed),
            u32::from(self.stats.last_dc()),
            u32::from(self.stats.last_route()),
        ]
    }

    pub async fn stop(&mut self) -> Result<(), String> {
        self.stats.stop();
        if let Some(mut task) = self.task.take() {
            match tokio::time::timeout(Duration::from_secs(2), &mut task).await {
                Ok(Ok(result)) => result,
                Ok(Err(_)) => Err("Transport task failed".to_owned()),
                Err(_) => {
                    task.abort();
                    let _ = task.await;
                    Err("Transport shutdown deadline exceeded".to_owned())
                }
            }
        } else { Ok(()) }
    }
}

impl Drop for EmbeddedTunnel {
    fn drop(&mut self) {
        self.stats.stop();
        if let Some(task) = self.task.take() { task.abort(); }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpStream;

    async fn socks_is_refused(engine: &EmbeddedTunnel) {
        let mut client = TcpStream::connect(engine.address()).await.unwrap();
        client.write_all(&[5, 1, 0]).await.unwrap();
        let mut reply = Vec::new();
        let result = tokio::time::timeout(Duration::from_secs(2), client.read_to_end(&mut reply)).await;
        match result {
            Ok(Ok(_)) => assert!(reply.is_empty(), "must not negotiate no-auth SOCKS"),
            Ok(Err(error)) => assert!(matches!(error.kind(), std::io::ErrorKind::ConnectionReset | std::io::ErrorKind::UnexpectedEof)),
            Err(_) => panic!("disabled SOCKS must close within deadline"),
        }
    }

    #[tokio::test]
    async fn embedded_listener_is_loopback_and_refuses_socks() {
        let mut engine = EmbeddedTunnel::start().await.unwrap();
        assert!(engine.address().ip().is_loopback());
        assert_ne!(engine.address().port(), 0);
        assert!(engine.is_running());
        let secret = engine.proxy_secret();
        assert_eq!(secret.len(), 34);
        assert!(secret.starts_with("dd"));
        socks_is_refused(&engine).await;
        engine.stop().await.unwrap();
        assert!(!engine.is_running());
        assert_eq!(engine.stats.active.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn instances_keep_independent_listener_secret_and_shutdown() {
        let mut first = EmbeddedTunnel::start().await.unwrap();
        let mut second = EmbeddedTunnel::start().await.unwrap();
        assert_ne!(first.address(), second.address());
        assert_ne!(first.proxy_secret(), second.proxy_secret());
        first.stop().await.unwrap();
        assert!(second.is_running());
        socks_is_refused(&second).await;
        second.stop().await.unwrap();
    }

    #[tokio::test]
    async fn stop_cancels_incomplete_client_and_is_idempotent() {
        let mut engine = EmbeddedTunnel::start().await.unwrap();
        let mut client = TcpStream::connect(engine.address()).await.unwrap();
        client.write_all(&[7]).await.unwrap();
        tokio::time::timeout(Duration::from_secs(2), async {
            while engine.stats.active.load(Ordering::Relaxed) == 0 {
                tokio::task::yield_now().await;
            }
        }).await.unwrap();
        engine.stop().await.unwrap();
        engine.stop().await.unwrap();
        assert_eq!(engine.stats.active.load(Ordering::Relaxed), 0);
        let mut byte = [0];
        let read = tokio::time::timeout(Duration::from_secs(2), client.read(&mut byte)).await.unwrap();
        assert!(matches!(read, Ok(0) | Err(_)));
    }
}
