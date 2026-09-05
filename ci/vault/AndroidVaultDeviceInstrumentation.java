// SPDX-License-Identifier: MIT
package org.capybaragram.local;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteException;
import android.os.Bundle;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.GeneralSecurityException;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLongArray;
import java.util.concurrent.atomic.AtomicReference;
import javax.crypto.SecretKey;

/** Standalone synthetic Android runtime checks; never part of the product APK. */
public final class AndroidVaultDeviceInstrumentation extends Instrumentation {
    private int checks;
    private interface Operation { void run() throws Exception; }
    private void require(boolean value) {
        if (!value) throw new AssertionError("Check " + (checks + 1) + " failed.");
        checks++;
    }
    private void rejects(Class<? extends Exception> type, Operation action) throws Exception {
        try { action.run(); }
        catch (Exception failure) {
            if (type.isInstance(failure)) { checks++; return; }
            throw failure;
        }
        throw new AssertionError("Expected rejection: " + type.getSimpleName());
    }
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            AndroidVaultKeysDeviceProbe.run();
            exerciseStore();
            exerciseCoordinator();
            result.putString("stream", "CAPY_VAULT_TESTS=PASS checks=" + checks + "\n");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            // All data in this test application is synthetic. Preserve a useful
            // stack trace without adding any production account or message data.
            result.putString("stream", "CAPY_VAULT_TESTS=FAIL\n"
                    + android.util.Log.getStackTraceString(failure));
            finish(Activity.RESULT_CANCELED, result);
        }
    }

    private <T> T call(AndroidVaultCoordinator coordinator, AndroidVaultCoordinator.Token token,
            AndroidVaultCoordinator.Work<T> operation) throws Exception {
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<T> value = new AtomicReference<>();
        AtomicBoolean failed = new AtomicBoolean();
        coordinator.submit(token, operation, (result, failure) -> {
            value.set(result); failed.set(failure); done.countDown();
        });
        if (!done.await(20, TimeUnit.SECONDS) || failed.get()) {
            throw new AssertionError("Coordinator callback failed or timed out.");
        }
        return value.get();
    }

    private void exerciseCoordinator() throws Exception {
        Context context = getTargetContext();
        String prefix = "capy-test-" + UUID.randomUUID() + "-";
        AtomicLongArray owners = new AtomicLongArray(new long[]{100, 200});
        AtomicBoolean unlocked = new AtomicBoolean(true);
        AndroidVaultCoordinator.Host host = new AndroidVaultCoordinator.Host() {
            @Override public long currentOwner(int account) { return owners.get(account); }
            @Override public boolean unlocked() { return unlocked.get(); }
            @Override public SharedPreferences preferences(int account) {
                return context.getSharedPreferences(prefix + account, Context.MODE_PRIVATE);
            }
            @Override public void storageProblem() { }
        };
        AndroidVaultCoordinator coordinator = new AndroidVaultCoordinator(context, host, 2);
        AndroidVaultCoordinator.Token first = coordinator.capture(0);
        call(coordinator, first, store -> { store.saveNote(1, 42, 0, "Первый владелец"); return true; });
        require("Первый владелец".equals(call(coordinator, first, store -> store.getNote(1, 42, 0))));
        require(call(coordinator, coordinator.capture(1), store -> store.getNote(1, 42, 0)).isEmpty());
        require(coordinator.capture(-1) == null && coordinator.capture(2) == null);

        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicBoolean staleCallback = new AtomicBoolean(), queuedWrite = new AtomicBoolean();
        coordinator.submit(first, store -> {
            entered.countDown();
            if (!release.await(20, TimeUnit.SECONDS)) throw new IOException("Test barrier timed out.");
            return true;
        }, (value, failed) -> staleCallback.set(true));
        require(entered.await(20, TimeUnit.SECONDS));
        coordinator.submit(first, store -> {
            queuedWrite.set(true); store.saveNote(1, 42, 0, "STALE"); return true;
        }, (value, failed) -> staleCallback.set(true));
        unlocked.set(false);
        coordinator.onLock();
        require(coordinator.capture(0) == null);
        unlocked.set(true);
        release.countDown();
        require("Первый владелец".equals(call(coordinator, coordinator.capture(0), store -> store.getNote(1, 42, 0))));
        require(!queuedWrite.get() && !staleCallback.get() && !coordinator.isCurrent(first));

        AndroidVaultCoordinator.Token old = coordinator.capture(0);
        UUID oldGeneration = UUID.fromString(host.preferences(0).getString("capy_vault_generation", ""));
        CountDownLatch inFlight = new CountDownLatch(1), finishOld = new CountDownLatch(1);
        coordinator.submit(old, store -> {
            inFlight.countDown();
            if (!finishOld.await(20, TimeUnit.SECONDS)) throw new IOException("Test barrier timed out.");
            store.saveNote(1, 42, 0, "Old generation only");
            return true;
        }, (value, failed) -> staleCallback.set(true));
        require(inFlight.await(20, TimeUnit.SECONDS));
        coordinator.onLogout(0);
        require(!host.preferences(0).contains("capy_vault_generation"));
        require(coordinator.capture(0) == null);
        owners.set(0, 101);
        coordinator.onOwnerChanged(0, 0, 101);
        finishOld.countDown();
        require(call(coordinator, coordinator.capture(0), store -> store.getNote(1, 42, 0)).isEmpty());
        require(!AndroidVaultStore.file(context, oldGeneration).exists() && !staleCallback.get());
        rejects(GeneralSecurityException.class, () -> AndroidVaultKeys.load(oldGeneration));

        call(coordinator, coordinator.capture(0), store -> { store.saveNote(1, 42, 0, "New login"); return true; });
        String previous = host.preferences(0).getString("capy_vault_generation", "");
        coordinator.onLogout(0);
        coordinator.onOwnerChanged(0, 0, 101); // Same Telegram owner logs in again.
        require(call(coordinator, coordinator.capture(0), store -> store.getNote(1, 42, 0)).isEmpty());
        require(!previous.equals(host.preferences(0).getString("capy_vault_generation", "")));

        // Simulate process termination between retirement and queued cleanup.
        UUID retiredGeneration = UUID.fromString(host.preferences(0).getString("capy_vault_generation", ""));
        require(context.getSharedPreferences("capy_vault_cleanup", Context.MODE_PRIVATE)
                .edit().putBoolean(retiredGeneration.toString(), true).commit());
        AndroidVaultCoordinator recovered = new AndroidVaultCoordinator(context, host, 2);
        require(call(recovered, recovered.capture(0), store -> store.getNote(1, 42, 0)).isEmpty());
        require(!AndroidVaultStore.file(context, retiredGeneration).exists());
        rejects(GeneralSecurityException.class, () -> AndroidVaultKeys.load(retiredGeneration));
        require(!retiredGeneration.toString().equals(host.preferences(0).getString("capy_vault_generation", "")));
        recovered.onLogout(0);
        recovered.onLogout(1);
    }

    private void exerciseStore() throws Exception {
        Context context = getTargetContext();
        UUID first = UUID.randomUUID(), second = UUID.randomUUID(), missing = UUID.randomUUID();
        boolean firstKey = false, secondKey = false;
        try {
            SecretKey key = AndroidVaultKeys.create(first);
            firstKey = true;
            SecretKey otherKey = AndroidVaultKeys.create(second);
            secondKey = true;
            String note = "Встреча в пятницу 🦫 '); DROP TABLE notes; --";
            long templateId;
            try (AndroidVaultStore store = AndroidVaultStore.create(context, first, key);
                 AndroidVaultStore other = AndroidVaultStore.create(context, second, otherKey)) {
                require(store.getNote(3, 42, 17).isEmpty());
                store.saveNote(3, 42, 17, note);
                require(note.equals(store.getNote(3, 42, 17)));
                require(store.getNote(3, 42, 18).isEmpty());
                require(store.getNote(1, 42, 0).isEmpty());
                require(other.getNote(3, 42, 17).isEmpty());
                other.saveNote(3, 42, 17, "Другой аккаунт");
                require(note.equals(store.getNote(3, 42, 17)));
                require("Другой аккаунт".equals(other.getNote(3, 42, 17)));
                store.saveNote(3, 42, 17, "Обновлённая заметка");
                require("Обновлённая заметка".equals(store.getNote(3, 42, 17)));
                store.saveNote(3, 42, 17, note);
                rejects(IllegalArgumentException.class, () -> store.saveNote(1, 42, 17, "invalid topic"));
                rejects(IllegalArgumentException.class, () -> store.saveNote(3, 42, 17, "\ud800"));
                require(note.equals(store.getNote(3, 42, 17)));
                templateId = store.addTemplate("Спасибо, проверю и отвечу.");
                require(store.listTemplates(0).size() == 1);
                store.updateTemplate(templateId, "Спасибо! 🦫");
                require("Спасибо! 🦫".equals(store.listTemplates(0).get(0).text));
                char[] excessive = new char[PayloadCipher.MAX_PLAINTEXT];
                Arrays.fill(excessive, 'Я');
                rejects(IllegalArgumentException.class, () -> store.addTemplate(new String(excessive)));
                require(store.listTemplates(0).size() == 1); // Failed insert rolled back.
                rejects(IllegalArgumentException.class, () -> store.updateTemplate(999999, "missing"));
                require(store.listTemplates(100).isEmpty());
                rejects(IOException.class, () -> AndroidVaultStore.create(context, first, key));
            }
            try (AndroidVaultStore reopened = AndroidVaultStore.open(context, first,
                    AndroidVaultKeys.load(first))) {
                require(note.equals(reopened.getNote(3, 42, 17)));
                require(reopened.listTemplates(0).get(0).id == templateId);
                require("Спасибо! 🦫".equals(reopened.listTemplates(0).get(0).text));
                reopened.deleteTemplate(templateId);
                require(reopened.listTemplates(0).isEmpty());
                reopened.saveNote(3, 42, 17, "");
                require(reopened.getNote(3, 42, 17).isEmpty());
                reopened.saveNote(3, 42, 17, note);
            }
            byte[] original;
            try (SQLiteDatabase raw = SQLiteDatabase.openDatabase(
                    AndroidVaultStore.file(context, first).toString(), null, SQLiteDatabase.OPEN_READWRITE)) {
                try (Cursor cursor = raw.rawQuery("SELECT payload FROM notes", null)) {
                    require(cursor.moveToFirst());
                    original = cursor.getBlob(0);
                    require(!new String(original, StandardCharsets.ISO_8859_1).contains("DROP TABLE"));
                }
                byte[] tampered = original.clone();
                tampered[tampered.length - 1] ^= 1;
                ContentValues values = new ContentValues();
                values.put("payload", tampered);
                require(raw.update("notes", values, null, null) == 1);
            }
            try (AndroidVaultStore reopened = AndroidVaultStore.open(context, first, key)) {
                rejects(GeneralSecurityException.class, () -> reopened.getNote(3, 42, 17));
            }
            try (SQLiteDatabase raw = SQLiteDatabase.openDatabase(
                    AndroidVaultStore.file(context, first).toString(), null, SQLiteDatabase.OPEN_READWRITE)) {
                ContentValues values = new ContentValues();
                values.put("payload", original);
                values.put("topic_id", 18L);
                require(raw.update("notes", values, null, null) == 1);
            }
            try (AndroidVaultStore reopened = AndroidVaultStore.open(context, first, key)) {
                rejects(GeneralSecurityException.class, () -> reopened.getNote(3, 42, 18));
            }
            try (AndroidVaultStore wrongKey = AndroidVaultStore.open(context, second, key)) {
                rejects(GeneralSecurityException.class, () -> wrongKey.getNote(3, 42, 17));
            }
            rejects(IOException.class, () -> AndroidVaultStore.open(context, missing, key));
            require(!AndroidVaultStore.file(context, missing).exists());
            // An unsupported schema must survive a failed open, byte for byte.
            try (SQLiteDatabase raw = SQLiteDatabase.openDatabase(
                    AndroidVaultStore.file(context, second).toString(), null, SQLiteDatabase.OPEN_READWRITE)) {
                raw.setVersion(99);
            }
            byte[] before = Files.readAllBytes(AndroidVaultStore.file(context, second).toPath());
            rejects(SQLiteException.class, () -> AndroidVaultStore.open(context, second, otherKey));
            require(Arrays.equals(before, Files.readAllBytes(AndroidVaultStore.file(context, second).toPath())));
            AndroidVaultKeys.delete(first);
            rejects(GeneralSecurityException.class, () -> AndroidVaultKeys.load(first));
            require(AndroidVaultStore.file(context, first).exists());
        } finally {
            // Keys are unique to this invocation in a dedicated test app.
            try {
                if (firstKey) AndroidVaultKeys.delete(first);
            } finally {
                if (secondKey) AndroidVaultKeys.delete(second);
                SQLiteDatabase.deleteDatabase(AndroidVaultStore.file(context, first));
                SQLiteDatabase.deleteDatabase(AndroidVaultStore.file(context, second));
            }
        }
    }
}
