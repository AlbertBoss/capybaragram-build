// SPDX-License-Identifier: MIT
package org.capybaragram.local;

import android.content.Context;
import android.content.SharedPreferences;
import android.database.sqlite.SQLiteDatabase;
import android.os.Handler;
import android.os.Looper;
import java.io.IOException;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicIntegerArray;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicLongArray;
import javax.crypto.SecretKey;

/** Main-process vault coordinator; the native client supplies session identity. */
public final class AndroidVaultCoordinator {
    private static final String GENERATION = "capy_vault_generation";
    private static final String OWNER = "capy_vault_owner";
    private final Context context;
    private final Host host;
    private final AtomicLongArray epochs;
    private final AtomicIntegerArray retired;
    private final AtomicLong lockEpoch = new AtomicLong();
    private final Object metadataLock = new Object();
    private final SharedPreferences cleanup;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor(r -> {
        Thread thread = new Thread(r, "CapybaraGram-vault");
        thread.setDaemon(true);
        return thread;
    });

    public interface Host {
        long currentOwner(int account);
        boolean unlocked();
        SharedPreferences preferences(int account);
        void storageProblem(); // Sanitized diagnostic only; no plaintext or key data.
    }
    public interface Work<T> { T run(AndroidVaultStore store) throws Exception; }
    public interface Callback<T> { void complete(T value, boolean failed); }

    public AndroidVaultCoordinator(Context context, Host host, int accountCount) {
        if (context == null || host == null || accountCount < 1 || accountCount > 100) {
            throw new IllegalArgumentException("Invalid vault coordinator configuration.");
        }
        this.context = context.getApplicationContext();
        this.host = host;
        cleanup = this.context.getSharedPreferences("capy_vault_cleanup", Context.MODE_PRIVATE);
        epochs = new AtomicLongArray(accountCount);
        retired = new AtomicIntegerArray(accountCount);
        worker.execute(() -> {
            for (String value : cleanup.getAll().keySet()) {
                try { destroy(parse(value)); }
                catch (RuntimeException invalid) { host.storageProblem(); }
            }
        });
    }

    public Token capture(int account) {
        if (account < 0 || account >= epochs.length()) return null;
        long owner = host.currentOwner(account);
        Token token = new Token(account, owner, epochs.get(account), lockEpoch.get());
        return isCurrent(token) ? token : null;
    }

    public boolean isCurrent(Token token) {
        return token != null && token.owner > 0 && token.account >= 0
                && token.account < epochs.length() && retired.get(token.account) == 0
                && epochs.get(token.account) == token.epoch
                && lockEpoch.get() == token.lockEpoch && host.unlocked()
                && host.currentOwner(token.account) == token.owner;
    }

    public <T> void submit(Token token, Work<T> operation, Callback<T> callback) {
        if (operation == null || callback == null) throw new IllegalArgumentException();
        worker.execute(() -> {
            if (!isCurrent(token)) return;
            T result = null;
            boolean failure = false;
            try (AndroidVaultStore store = open(token)) {
                if (!isCurrent(token)) return;
                result = operation.run(store);
            } catch (Exception error) {
                failure = true;
                if (isCurrent(token)) host.storageProblem();
            }
            final T value = result;
            final boolean failed = failure;
            main.post(() -> {
                if (isCurrent(token)) callback.complete(value, failed);
            });
        });
    }

    /** Call after the app-lock flag is set and before presenting the passcode. */
    public void onLock() { lockEpoch.incrementAndGet(); }

    /** No disk or worker locks: safe from inside UserConfig's own synchronization. */
    public void onOwnerChanged(int account, long previous, long next) {
        if (account < 0 || account >= epochs.length() || previous == next) return;
        epochs.incrementAndGet(account);
        retired.set(account, next > 0 ? 0 : 1);
    }

    /**
     * Revoke immediately, durably remove the generation reference, then destroy
     * its key/database on the worker. In-flight operations can finish only in
     * the retired generation; they can never publish a callback into a new login.
     * The host must call this BEFORE clearing UserConfig preferences/currentUser.
     */
    public void onLogout(int account) {
        if (account < 0 || account >= epochs.length()) return;
        retired.set(account, 1);
        epochs.incrementAndGet(account);
        UUID generation = null;
        synchronized (metadataLock) {
            SharedPreferences preferences = host.preferences(account);
            try {
                String value = preferences.getString(GENERATION, "");
                if (!value.isEmpty()) generation = parse(value);
            } catch (RuntimeException invalid) {
                host.storageProblem();
            }
            if (generation != null) retire(generation);
            // Only our two keys are changed; Telegram logout still clears its own data.
            if (!preferences.edit().remove(GENERATION).remove(OWNER).commit()) {
                host.storageProblem();
            }
        }
        final UUID old = generation;
        if (old != null) worker.execute(() -> destroy(old));
    }

    private AndroidVaultStore open(Token token) throws Exception {
        UUID generation = null;
        UUID abandoned = null;
        synchronized (metadataLock) {
            requireCurrent(token);
            SharedPreferences preferences = host.preferences(token.account);
            String value = preferences.getString(GENERATION, "");
            long owner = preferences.getLong(OWNER, 0);
            if (!value.isEmpty()) {
                UUID stored = parse(value);
                if (cleanup.contains(value)) {
                    throw new IOException("Vault generation has been retired.");
                } else if (owner == token.owner) {
                    generation = stored;
                } else {
                    retire(stored);
                    if (!preferences.edit().remove(GENERATION).remove(OWNER).commit()) {
                        throw new IOException("Vault account metadata unavailable.");
                    }
                    abandoned = stored;
                }
            } else if (owner != 0) {
                throw new IOException("Incomplete vault account metadata.");
            }
        }
        if (abandoned != null) destroy(abandoned);
        requireCurrent(token);
        if (generation != null) {
            // Existing data never causes automatic key creation or schema replacement.
            return AndroidVaultStore.open(context, generation, AndroidVaultKeys.load(generation));
        }
        generation = UUID.randomUUID();
        SecretKey key = AndroidVaultKeys.create(generation);
        AndroidVaultStore store = null;
        boolean published = false;
        try {
            store = AndroidVaultStore.create(context, generation, key);
            synchronized (metadataLock) {
                requireCurrent(token);
                SharedPreferences preferences = host.preferences(token.account);
                if (!preferences.getString(GENERATION, "").isEmpty()) {
                    throw new IOException("Vault account metadata changed.");
                }
                if (!preferences.edit().putString(GENERATION, generation.toString())
                        .putLong(OWNER, token.owner).commit()) {
                    throw new IOException("Vault account metadata could not be saved.");
                }
                published = true;
            }
            return store;
        } finally {
            if (!published) {
                if (store != null) store.close();
                destroy(generation);
            }
        }
    }

    private void requireCurrent(Token token) throws IOException {
        if (!isCurrent(token)) throw new IOException("Vault session is no longer current.");
    }

    private static UUID parse(String value) {
        UUID result = UUID.fromString(value);
        if (!result.toString().equals(value)
                || (result.getMostSignificantBits() == 0 && result.getLeastSignificantBits() == 0)) {
            throw new IllegalArgumentException("Invalid vault generation.");
        }
        return result;
    }

    private void destroy(UUID generation) {
        try {
            // Tombstone precedes deletion and survives process termination.
            retire(generation);
            synchronized (metadataLock) {
                for (int account = 0; account < epochs.length(); account++) {
                    SharedPreferences preferences = host.preferences(account);
                    if (generation.toString().equals(preferences.getString(GENERATION, ""))
                            && !preferences.edit().remove(GENERATION).remove(OWNER).commit()) {
                        throw new IOException("Retired vault metadata removal failed.");
                    }
                }
            }
            AndroidVaultKeys.delete(generation);
            if (AndroidVaultStore.file(context, generation).exists()
                    && !SQLiteDatabase.deleteDatabase(AndroidVaultStore.file(context, generation))) {
                throw new IOException("Retired vault database deletion failed.");
            }
            if (!cleanup.edit().remove(generation.toString()).commit()) host.storageProblem();
        } catch (Exception failure) {
            host.storageProblem();
        }
    }

    private void retire(UUID generation) {
        if (!cleanup.edit().putBoolean(generation.toString(), true).commit()) host.storageProblem();
    }

    public static final class Token {
        public final int account;
        public final long owner;
        private final long epoch, lockEpoch;
        private Token(int account, long owner, long epoch, long lockEpoch) {
            this.account = account;
            this.owner = owner;
            this.epoch = epoch;
            this.lockEpoch = lockEpoch;
        }
    }
}
