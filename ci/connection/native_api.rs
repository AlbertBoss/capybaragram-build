//! Versioned C interface for a native client. Start/stop belong on a worker thread.
//! Opaque handles are never reused; no raw Rust object is exposed to C++/JNI.
use crate::embedded::EmbeddedTunnel;
use std::collections::HashMap;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Mutex, OnceLock};
use tokio::runtime::{Builder, Runtime};

const ABI_VERSION: u32 = 1;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct CapyConnectionEndpoint {
    pub abi_version: u32,
    pub port: u16,
    pub reserved: u16,
    pub secret: [u8; 35],
}

impl Default for CapyConnectionEndpoint {
    fn default() -> Self {
        Self { abi_version: 0, port: 0, reserved: 0, secret: [0; 35] }
    }
}

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct CapyConnectionStatus {
    pub abi_version: u32,
    pub running: u32,
    pub active: u32,
    pub established: u32,
    pub failed_tunnels: u32,
    pub data_centre: u32,
    pub route: u32,
}

struct Registry {
    next: u64,
    tunnels: HashMap<u64, EmbeddedTunnel>,
}

static RUNTIME: OnceLock<Option<Runtime>> = OnceLock::new();
static REGISTRY: OnceLock<Mutex<Registry>> = OnceLock::new();

fn runtime() -> Option<&'static Runtime> {
    RUNTIME.get_or_init(|| {
        Builder::new_multi_thread()
            .worker_threads(2)
            .thread_name("capy-route")
            .enable_all()
            .build()
            .ok()
    }).as_ref()
}

fn registry() -> &'static Mutex<Registry> {
    REGISTRY.get_or_init(|| Mutex::new(Registry { next: 1, tunnels: HashMap::new() }))
}

/// Starts a loopback MTProto-only transport. Returns zero on failure.
/// Keep the returned token in memory; do not log or persist the endpoint.
///
/// # Safety
/// `output` must point to one writable, aligned endpoint with no concurrent accesses.
/// Do not call from inside a Tokio async task; invoke on a native worker thread.
#[no_mangle]
pub unsafe extern "C" fn capy_connection_start(output: *mut CapyConnectionEndpoint) -> u64 {
    if output.is_null() { return 0; }
    unsafe { output.write(CapyConnectionEndpoint::default()); }
    catch_unwind(AssertUnwindSafe(|| {
        let engine = runtime()?;
        let mut tunnel = engine.block_on(EmbeddedTunnel::start()).ok()?;
        let mut endpoint = CapyConnectionEndpoint {
            abi_version: ABI_VERSION, port: tunnel.address().port(), ..Default::default()
        };
        let mut token = tunnel.proxy_secret().into_bytes();
        if token.len() != 34 {
            token.fill(0);
            let _ = engine.block_on(tunnel.stop());
            return None;
        }
        endpoint.secret[..34].copy_from_slice(&token);
        token.fill(0);
        let handle = {
            let mut state = registry().lock().ok()?;
            if state.next == u64::MAX || state.tunnels.len() >= 16 {
                drop(state);
                let _ = engine.block_on(tunnel.stop());
                return None;
            }
            let handle = state.next;
            state.next += 1;
            state.tunnels.insert(handle, tunnel);
            handle
        };
        unsafe { output.write(endpoint); }
        endpoint.secret.fill(0);
        Some(handle)
    })).ok().flatten().unwrap_or(0)
}

/// Reads counters without returning any session or local proxy token.
///
/// # Safety
/// `output` must point to one writable, aligned status with no concurrent accesses.
#[no_mangle]
pub unsafe extern "C" fn capy_connection_status(handle: u64, output: *mut CapyConnectionStatus) -> i32 {
    if output.is_null() { return 0; }
    unsafe { output.write(CapyConnectionStatus::default()); }
    catch_unwind(AssertUnwindSafe(|| {
        let state = registry().lock().ok()?;
        let tunnel = state.tunnels.get(&handle)?;
        let counters = tunnel.counters();
        let value = CapyConnectionStatus {
            abi_version: ABI_VERSION,
            running: u32::from(tunnel.is_running()),
            active: counters[0], established: counters[1], failed_tunnels: counters[2],
            data_centre: counters[3], route: counters[4],
        };
        unsafe { output.write(value); }
        Some(1)
    })).ok().flatten().unwrap_or(0)
}

/// Revokes the handle before shutting down the listener. Returns 1 for clean stop,
/// 0 for an unknown/revoked handle, or -1 for a shutdown error. No C++ UI calls here.
#[no_mangle]
pub extern "C" fn capy_connection_stop(handle: u64) -> i32 {
    catch_unwind(AssertUnwindSafe(|| {
        let mut tunnel = match registry().lock().ok().and_then(|mut s| s.tunnels.remove(&handle)) {
            Some(tunnel) => tunnel,
            None => return 0,
        };
        match runtime().map(|engine| engine.block_on(tunnel.stop())) {
            Some(Ok(())) => 1,
            _ => -1,
        }
    })).unwrap_or(-1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capy_native_api_owns_endpoint_and_rejects_revoked_handle() {
        let mut endpoint = CapyConnectionEndpoint::default();
        let handle = unsafe { capy_connection_start(&mut endpoint) };
        assert_ne!(handle, 0);
        assert_eq!(endpoint.abi_version, ABI_VERSION);
        assert_ne!(endpoint.port, 0);
        assert_eq!(endpoint.secret[34], 0);
        assert!(endpoint.secret[..34].iter().all(u8::is_ascii_hexdigit));
        let mut status = CapyConnectionStatus::default();
        assert_eq!(unsafe { capy_connection_status(handle, &mut status) }, 1);
        assert_eq!(status.running, 1);
        assert_eq!(capy_connection_stop(handle), 1);
        assert_eq!(unsafe { capy_connection_status(handle, &mut status) }, 0);
        assert_eq!(status.abi_version, 0);
        assert_eq!(capy_connection_stop(handle), 0);
        endpoint.secret.fill(0);
    }

    #[test]
    fn capy_native_api_rejects_null_outputs_and_unknown_handle() {
        assert_eq!(unsafe { capy_connection_start(std::ptr::null_mut()) }, 0);
        assert_eq!(unsafe { capy_connection_status(0, std::ptr::null_mut()) }, 0);
        assert_eq!(capy_connection_stop(0), 0);
        assert_eq!(std::mem::size_of::<CapyConnectionEndpoint>(), 44);
        assert_eq!(std::mem::size_of::<CapyConnectionStatus>(), 28);
    }
}
