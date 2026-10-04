// SPDX-License-Identifier: MIT
package org.capybaragram.connection;

import android.os.Looper;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.tgnet.ConnectionsManager;

/** Process-local opt-in mode. Controls stay on the UI thread; native start/stop do not. */
public final class CapyConnectionService {
    private static volatile CapyConnectionService instance;
    private final ConnectionController controller;
    private final AtomicLong manualGeneration=new AtomicLong();
    private final AtomicBoolean cancellationPosted=new AtomicBoolean();
    private long generation, revision;

    private CapyConnectionService() {
        controller=new ConnectionController(new ConnectionController.Engine() {
            @Override public long start(byte[] endpoint) { return NativeTunnel.start(endpoint); }
            @Override public boolean status(long handle,int[] status) { return NativeTunnel.status(handle,status); }
            @Override public int stop(long handle) { return NativeTunnel.stop(handle); }
        },runnable -> AndroidUtilities.runOnUIThread(runnable),this::accept);
    }
    private static void requireUi() {
        if (Looper.myLooper()!=Looper.getMainLooper()) throw new IllegalStateException("connection control requires UI thread");
    }
    private static CapyConnectionService get() {
        requireUi();
        if (instance==null) instance=new CapyConnectionService();
        return instance;
    }
    public static void setEnabled(boolean enabled) {
        requireUi();get().change(enabled);
    }
    private void change(boolean enabled) {
        generation=ConnectionsManager.capyBeginConnection(enabled);
        // No route lock is held while taking the controller lock.
        revision=controller.setEnabled(enabled);
    }
    private void accept(ConnectionController.Update update) {
        requireUi();
        if (update.revision!=revision) return;
        if (update.phase==ConnectionController.Phase.READY) {
            ConnectionsManager.capyAcceptConnection(generation,update.endpoint);
        } else if (update.phase==ConnectionController.Phase.FAILED) {
            ConnectionsManager.capyFailConnection(generation);
        }
        // LOCAL_READY confirms the loopback listener only. Telegram's own connection indicator
        // remains authoritative for authentication and end-to-end network reachability.
    }
    public static MemoryRoute.Snapshot snapshot() { return ConnectionsManager.capyConnectionSnapshot(); }
    public static void manualSelected(long revokedGeneration) {
        CapyConnectionService current=instance;
        if (current==null) return;
        long previous;
        do { previous=current.manualGeneration.get(); }
        while (revokedGeneration>previous && !current.manualGeneration.compareAndSet(previous,revokedGeneration));
        current.scheduleCancellation();
    }
    private void scheduleCancellation() {
        if (!cancellationPosted.compareAndSet(false,true)) return;
        AndroidUtilities.runOnUIThread(() -> {
            long revoked=manualGeneration.getAndSet(0);
            cancellationPosted.set(false);
            MemoryRoute.Snapshot current=ConnectionsManager.capyConnectionSnapshot();
            // A delayed manual-proxy cancellation cannot stop a newer user activation.
            if (revoked>0 && current.generation==revoked && !current.requested) {
                generation=revoked;revision=controller.setEnabled(false);
            }
            if (manualGeneration.get()!=0) scheduleCancellation();
        });
    }
}
