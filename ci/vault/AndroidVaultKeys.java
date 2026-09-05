// SPDX-License-Identifier: MIT
package org.capybaragram.local;

import android.os.Build;
import android.os.Looper;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.io.IOException;
import java.security.GeneralSecurityException;
import java.security.Key;
import java.security.KeyStore;
import java.util.UUID;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;

/**
 * Per-account-generation keys. Call only from the serialized vault worker.
 * The account generation must come from private account metadata, never a slot
 * number or an imported database. Creation is only for a NEW empty vault.
 * This adapter does not enforce the Telegram app passcode or device unlock.
 * The vault coordinator must gate access, close editors on lock/logout, and
 * serialize database commits with account retirement. No silent recovery or
 * key replacement is permitted when a previously created vault loses its key.
 */
public final class AndroidVaultKeys {
    private static final String PROVIDER = "AndroidKeyStore";
    private static final String PREFIX = "org.capybaragram.vault.v1.";
    private AndroidVaultKeys() {}

    public static synchronized SecretKey create(UUID generation)
            throws GeneralSecurityException {
        String alias = alias(generation);
        KeyStore store = open();
        if (store.containsAlias(alias)) {
            throw new GeneralSecurityException("Vault key already exists.");
        }
        KeyGenerator generator = KeyGenerator.getInstance("AES", PROVIDER);
        generator.init(new KeyGenParameterSpec.Builder(alias,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build());
        return generator.generateKey();
    }

    public static synchronized SecretKey load(UUID generation)
            throws GeneralSecurityException {
        String alias = alias(generation);
        Key key = open().getKey(alias, null);
        if (!(key instanceof SecretKey) || !"AES".equals(key.getAlgorithm())) {
            throw new GeneralSecurityException("Vault key unavailable.");
        }
        return (SecretKey) key;
    }

    /** Retire the generation first; retry failed deletion before removing its tombstone. */
    public static synchronized void delete(UUID generation)
            throws GeneralSecurityException {
        String alias = alias(generation);
        KeyStore store = open();
        store.deleteEntry(alias);
        if (store.containsAlias(alias)) {
            throw new GeneralSecurityException("Vault key deletion failed.");
        }
    }

    private static String alias(UUID generation) {
        if (generation == null || (generation.getMostSignificantBits() == 0
                && generation.getLeastSignificantBits() == 0)) {
            throw new IllegalArgumentException("Invalid account generation.");
        }
        return PREFIX + generation;
    }

    private static KeyStore open() throws GeneralSecurityException {
        if (Build.VERSION.SDK_INT < 23) {
            throw new GeneralSecurityException("Vault requires Android API 23 or newer.");
        }
        if (Looper.myLooper() == Looper.getMainLooper()) {
            throw new IllegalStateException("Vault keys require a background worker.");
        }
        KeyStore store = KeyStore.getInstance(PROVIDER);
        try {
            store.load(null);
        } catch (IOException failure) {
            throw new GeneralSecurityException("Vault key store unavailable.");
        }
        return store;
    }
}
