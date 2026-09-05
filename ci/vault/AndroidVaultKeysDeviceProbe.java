// SPDX-License-Identifier: MIT
package org.capybaragram.local;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.Arrays;
import java.util.UUID;
import javax.crypto.SecretKey;

/** Run on an Android test app background thread. Never include in release UI. */
public final class AndroidVaultKeysDeviceProbe {
    private interface Operation { void run() throws GeneralSecurityException; }
    private static void require(boolean value) {
        if (!value) throw new AssertionError("Vault device probe failed.");
    }
    private static void rejected(Operation operation) throws GeneralSecurityException {
        try { operation.run(); }
        catch (GeneralSecurityException expected) { return; }
        throw new AssertionError("Vault accepted unavailable or mismatched key.");
    }

    public static void run() throws GeneralSecurityException {
        UUID first = UUID.randomUUID(), second = UUID.randomUUID();
        // Only synthetic, randomly named keys owned by this invocation are removed.
        boolean firstCreated = false, secondCreated = false;
        try {
            rejected(() -> AndroidVaultKeys.load(first));
            SecretKey key = AndroidVaultKeys.create(first);
            firstCreated = true;
            require(key.getEncoded() == null);
            rejected(() -> AndroidVaultKeys.create(first));
            byte[] text = "Личная заметка 🦫".getBytes(StandardCharsets.UTF_8);
            PayloadCipher.Context context = PayloadCipher.Context.note(first, 3, 42, 17);
            byte[] encrypted = PayloadCipher.encrypt(key, context, text);
            require(Arrays.equals(text, PayloadCipher.decrypt(
                    AndroidVaultKeys.load(first), context, encrypted)));
            SecretKey other = AndroidVaultKeys.create(second);
            secondCreated = true;
            rejected(() -> PayloadCipher.decrypt(other, context, encrypted));
            rejected(() -> PayloadCipher.decrypt(key,
                    PayloadCipher.Context.note(first, 3, 42, 18), encrypted));
            encrypted[encrypted.length - 1] ^= 1;
            rejected(() -> PayloadCipher.decrypt(key, context, encrypted));
            AndroidVaultKeys.delete(first);
            rejected(() -> AndroidVaultKeys.load(first));
            // Deletion must leave the other account generation readable.
            require(AndroidVaultKeys.load(second).getEncoded() == null);
        } finally {
            try {
                if (firstCreated) AndroidVaultKeys.delete(first);
            } finally {
                if (secondCreated) AndroidVaultKeys.delete(second);
            }
        }
    }
}
