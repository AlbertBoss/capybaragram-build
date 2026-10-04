// SPDX-License-Identifier: MIT
package org.capybaragram.connection;

import java.util.Arrays;

/** One native worker, one pending command and one coalesced UI delivery. */
public final class ConnectionController implements AutoCloseable {
    public interface Engine {
        long start(byte[] endpoint);
        boolean status(long handle, int[] status);
        int stop(long handle);
    }
    public interface Dispatcher { void post(Runnable runnable); }
    public interface Listener { void accept(Update update); }
    public enum Phase { DISABLED, READY, FAILED }
    public static final class Update implements AutoCloseable {
        public final long revision;
        public final Phase phase;
        // Callback-scoped only: wiped immediately after delivery or revocation.
        public final byte[] endpoint;
        public final int[] status;
        private Update(long revision, Phase phase, byte[] endpoint, int[] status) {
            this.revision=revision;this.phase=phase;this.endpoint=endpoint;this.status=status;
        }
        @Override public void close() {
            if (endpoint!=null) Arrays.fill(endpoint,(byte)0);
            if (status!=null) Arrays.fill(status,0);
        }
    }
    private static final class Command {
        final long revision;
        final boolean enabled;
        Command(long revision,boolean enabled) { this.revision=revision;this.enabled=enabled; }
    }
    private final Object lock=new Object();
    private final Engine engine;
    private final Dispatcher dispatcher;
    private final Listener listener;
    private Command pending;
    private Update delivery;
    private long revision;
    private boolean scheduled,closed;
    private volatile boolean terminated;

    public ConnectionController(Engine engine,Dispatcher dispatcher,Listener listener) {
        if (engine==null || dispatcher==null || listener==null) throw new NullPointerException("controller dependency");
        this.engine=engine;this.dispatcher=dispatcher;this.listener=listener;
        Thread thread=new Thread(this::work,"capy-connection-control");
        thread.setDaemon(true);thread.start();
    }
    /** Returns the revision to compare with UI state; never waits for native work. */
    public long setEnabled(boolean enabled) {
        synchronized (lock) {
            if (closed) return -1;
            if (revision==Long.MAX_VALUE) throw new IllegalStateException("controller revision exhausted");
            long next=++revision;
            pending=new Command(next,enabled);
            if (delivery!=null) { delivery.close();delivery=null; }
            lock.notifyAll();return next;
        }
    }
    private boolean current(Command command) {
        synchronized (lock) { return !closed && command.revision==revision; }
    }
    private void post(Update update) {
        boolean enqueue;
        synchronized (lock) {
            if (closed || update.revision!=revision) { update.close();return; }
            if (delivery!=null) delivery.close();
            delivery=update;enqueue=!scheduled;scheduled=true;
        }
        if (enqueue) {
            try { dispatcher.post(this::deliver); }
            catch (RuntimeException failure) { close(); }
        }
    }
    private void deliver() {
        synchronized (lock) {
            Update update=delivery;delivery=null;scheduled=false;
            if (update==null) return;
            try {
                // Serialize final acceptance against commands from other threads.
                // The UI listener must not wait for this worker or block on I/O.
                if (!closed && update.revision==revision) listener.accept(update);
            } finally { update.close(); }
        }
    }
    private void work() {
        long handle=0;
        try {
            while (true) {
                Command command;
                synchronized (lock) {
                    while (!closed && pending==null) {
                        try { lock.wait(); }
                        catch (InterruptedException interrupted) {
                            Thread.currentThread().interrupt();closed=true;
                        }
                    }
                    if (closed) break;
                    command=pending;pending=null;
                }
                byte[] endpoint=null;
                try {
                    if (handle!=0) {
                        if (engine.stop(handle)<0) throw new IllegalStateException("native stop failed");
                        handle=0;
                    }
                    if (!current(command)) continue;
                    if (!command.enabled) {
                        post(new Update(command.revision,Phase.DISABLED,null,null));continue;
                    }
                    endpoint=new byte[36];
                    handle=engine.start(endpoint);
                    if (handle<=0) { handle=0;throw new IllegalStateException("native start failed"); }
                    if (!current(command)) continue;
                    int[] status=new int[7];
                    if (!engine.status(handle,status) || status[0]!=1 || status[1]!=1
                            || status[2]<0 || status[2]>128 || status[5]<0 || status[5]>65535
                            || status[6]<0 || status[6]>4 || !validEndpoint(endpoint)) {
                        throw new IllegalStateException("native readiness invalid");
                    }
                    post(new Update(command.revision,Phase.READY,endpoint,status));
                    endpoint=null; // Update owns and wipes its callback-scoped token.
                } catch (RuntimeException | LinkageError failure) {
                    if (handle!=0) {
                        try { if (engine.stop(handle)>=0) handle=0; }
                        catch (RuntimeException | LinkageError ignored) { }
                    }
                    post(new Update(command.revision,Phase.FAILED,null,null));
                } finally {
                    if (endpoint!=null) Arrays.fill(endpoint,(byte)0);
                }
            }
        } finally {
            if (handle!=0) {
                try { engine.stop(handle); }
                catch (RuntimeException | LinkageError ignored) { }
            }
            synchronized (lock) {
                closed=true;pending=null;
                if (delivery!=null) { delivery.close();delivery=null; }
            }
            terminated=true;
        }
    }
    private static boolean validEndpoint(byte[] endpoint) {
        if (((endpoint[0]&255)|((endpoint[1]&255)<<8))==0 || endpoint[2]!='d' || endpoint[3]!='d') return false;
        for (int i=4;i<36;i++) {
            int value=endpoint[i]&255;
            if (!((value>='0' && value<='9') || (value>='a' && value<='f'))) return false;
        }
        return true;
    }
    @Override public void close() {
        synchronized (lock) {
            closed=true;pending=null;
            if (delivery!=null) { delivery.close();delivery=null; }
            lock.notifyAll();
        }
    }
    public boolean isTerminated() { return terminated; }
}
