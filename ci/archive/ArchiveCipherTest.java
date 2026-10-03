// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import org.capybaragram.local.PayloadCipher;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.UUID;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;

/** Executes production AES-GCM; this is not an Android Keystore/SQLite test. */
public final class ArchiveCipherTest {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("Archive isolation"); }
    private static void denied(SecretKey key, PayloadCipher.Context context, byte[] envelope) {
        try { PayloadCipher.decrypt(key,context,envelope); throw new AssertionError("Unauthenticated archive accepted"); }
        catch (java.security.GeneralSecurityException expected) { checks++; }
    }
    public static void main(String[] args) throws Exception {
        UUID first=UUID.fromString("7c17e182-16cd-4a90-bdaf-c620c9400201");
        UUID second=UUID.fromString("7c17e182-16cd-4a90-bdaf-c620c9400202");
        SecretKey key=new SecretKeySpec(new byte[32],"AES");
        byte[] plain="Тестовое удалённое сообщение".getBytes(StandardCharsets.UTF_8);
        byte[] encoded=PayloadCipher.encrypt(key,PayloadCipher.Context.archive(first,42,0),plain);
        check(Arrays.equals(plain,PayloadCipher.decrypt(key,PayloadCipher.Context.archive(first,42,0),encoded)));
        denied(key,PayloadCipher.Context.archive(second,42,0),encoded);
        denied(key,PayloadCipher.Context.archive(first,43,0),encoded);
        denied(key,PayloadCipher.Context.archive(first,42,1),encoded);
        denied(key,PayloadCipher.Context.template(first,42),encoded);
        denied(key,PayloadCipher.Context.note(first,3,42,0),encoded);
        encoded[encoded.length-1]^=1;
        denied(key,PayloadCipher.Context.archive(first,42,0),encoded);
        try { PayloadCipher.Context.archive(first,0,0); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { checks++; }
        try { PayloadCipher.Context.archive(first,42,-1); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { checks++; }
        System.out.println("CAPY_ARCHIVE_CIPHER=PASS checks="+checks);
    }
}
