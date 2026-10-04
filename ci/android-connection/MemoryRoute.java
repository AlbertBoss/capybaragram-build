// SPDX-License-Identifier: MIT
package org.capybaragram.connection;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Serializes native routing only; never calls a worker, account factory or preference writer. */
public final class MemoryRoute {
    public interface Target {
        void apply(int account, boolean enabled, String address, int port,
                   String username, String password, String secret);
    }
    public enum Phase { DISABLED, STARTING, LOCAL_READY, FAILED }
    public static final class Proxy {
        public final boolean enabled;
        public final String address, username, password, secret;
        public final int port;
        public Proxy(boolean enabled, String address, int port, String username, String password, String secret) {
            this.enabled=enabled && address!=null && !address.isEmpty();
            this.address=address==null ? "" : address;
            this.port=port;
            this.username=username==null ? "" : username;
            this.password=password==null ? "" : password;
            this.secret=secret==null ? "" : secret;
        }
    }
    public static final class Snapshot {
        public final long generation;
        public final Phase phase;
        public final boolean requested;
        private Snapshot(long generation, Phase phase, boolean requested) {
            this.generation=generation;this.phase=phase;this.requested=requested;
        }
    }
    private final Target target;
    private final boolean[] initialized;
    private Proxy manual;
    private byte[] endpoint;
    private long generation;
    private boolean requested;
    private Phase phase=Phase.DISABLED;

    public MemoryRoute(int accounts, Target target) {
        if (accounts<=0 || accounts>100 || target==null) throw new IllegalArgumentException("route dependencies");
        initialized=new boolean[accounts];this.target=target;
    }
    private long advance() {
        if (generation==Long.MAX_VALUE) throw new IllegalStateException("route generation exhausted");
        return ++generation;
    }
    private void clearEndpoint() {
        if (endpoint!=null) { Arrays.fill(endpoint,(byte)0);endpoint=null; }
    }
    private void apply(int account) {
        if (endpoint!=null && requested) {
            // JNI requires a String. Retain only the wipeable byte token in this coordinator.
            target.apply(account,true,"127.0.0.1",(endpoint[0]&255)|((endpoint[1]&255)<<8),"","",
                         new String(endpoint,2,34,StandardCharsets.US_ASCII));
        } else if (manual!=null && manual.enabled) {
            target.apply(account,true,manual.address,manual.port,manual.username,manual.password,manual.secret);
        } else {
            target.apply(account,false,"",1080,"","","");
        }
    }
    private void applyInitialized() {
        for (int account=0;account<initialized.length;account++) if (initialized[account]) apply(account);
    }
    private void account(int account) {
        if (account<0 || account>=initialized.length) throw new IllegalArgumentException("route account");
    }
    public synchronized void beforeInitialize(int account, Proxy saved) {
        account(account);
        if (manual==null) {
            if (saved==null) throw new NullPointerException("saved proxy");
            manual=saved;
        }
        apply(account);
    }
    public synchronized void afterInitialize(int account) {
        account(account);initialized[account]=true;
        // Reapply the current route: a manual switch can happen during native_init.
        apply(account);
    }
    public synchronized long begin(boolean enabled, Proxy saved) {
        long next=advance();
        if (manual==null) {
            if (saved==null) throw new NullPointerException("saved proxy");
            manual=saved;
        }
        requested=enabled;phase=enabled ? Phase.STARTING : Phase.DISABLED;
        clearEndpoint();applyInitialized();return next;
    }
    /** Immediate revocation; caller schedules worker cancellation after this method returns. */
    public synchronized long manualSelected(Proxy selected) {
        if (selected==null) throw new NullPointerException("manual proxy");
        long next=advance();manual=selected;requested=false;phase=Phase.DISABLED;
        clearEndpoint();applyInitialized();return next;
    }
    public synchronized boolean ready(long expected, byte[] token) {
        if (generation!=expected || !requested || !valid(token)) return false;
        clearEndpoint();endpoint=token.clone();phase=Phase.LOCAL_READY;
        applyInitialized();return true;
    }
    public synchronized boolean failed(long expected) {
        if (generation!=expected || !requested) return false;
        requested=false;phase=Phase.FAILED;clearEndpoint();applyInitialized();return true;
    }
    public synchronized Snapshot snapshot() { return new Snapshot(generation,phase,requested); }
    private static boolean valid(byte[] token) {
        if (token==null || token.length!=36 || ((token[0]&255)|((token[1]&255)<<8))==0
                || token[2]!='d' || token[3]!='d') return false;
        for (int i=4;i<36;i++) {
            int value=token[i]&255;
            if (!((value>='0' && value<='9') || (value>='a' && value<='f'))) return false;
        }
        return true;
    }
}
