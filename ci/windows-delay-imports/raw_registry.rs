// SPDX-License-Identifier: MIT
#![no_std]
use core::ffi::c_void;

#[link(name = "advapi32", kind = "raw-dylib")]
extern "system" {
    fn RegCloseKey(key: *mut c_void) -> i32;
}

#[no_mangle]
pub unsafe extern "C" fn capy_probe_close_registry_key(key: *mut c_void) -> i32 {
    RegCloseKey(key)
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    loop { core::hint::spin_loop(); }
}
