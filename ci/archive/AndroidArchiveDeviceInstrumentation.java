// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Bundle;
import org.capybaragram.local.AndroidVaultKeys;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.GeneralSecurityException;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLongArray;
import java.util.concurrent.atomic.AtomicReference;
import javax.crypto.SecretKey;

/** Synthetic data only; this class is excluded from the client APK. */
public final class AndroidArchiveDeviceInstrumentation extends Instrumentation {
    private int checks;
    private interface Operation { void run() throws Exception; }
    private void require(boolean value) {
        if (!value) throw new AssertionError("Check " + (checks + 1) + " failed");
        checks++;
    }
    private void rejects(Class<? extends Exception> type, Operation action) throws Exception {
        try { action.run(); }
        catch (Exception failure) {
            if (type.isInstance(failure)) { checks++; return; }
            throw failure;
        }
        throw new AssertionError("Expected " + type.getSimpleName());
    }
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        Bundle report = new Bundle();
        try {
            exerciseStore();
            exerciseCoordinator();
            report.putString("stream", "CAPY_ARCHIVE_TESTS=PASS checks="+checks+"\n");
            finish(Activity.RESULT_OK,report);
        } catch (Throwable failure) {
            report.putString("stream", "CAPY_ARCHIVE_TESTS=FAIL\n"+android.util.Log.getStackTraceString(failure));
            finish(Activity.RESULT_CANCELED,report);
        }
    }
    private static byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
    private void exerciseStore() throws Exception {
        Context context=getTargetContext();
        UUID first=UUID.randomUUID(), second=UUID.randomUUID(), missing=UUID.randomUUID();
        boolean firstKey=false,secondKey=false;
        long secretDialog=42L << 32, channel=-1000000000042L;
        String text="Капибара 🦫 '); DROP TABLE snapshots; --";
        byte[] tl=bytes("synthetic-message-1");
        try {
            SecretKey key=AndroidVaultKeys.create(first); firstKey=true;
            SecretKey other=AndroidVaultKeys.create(second); secondKey=true;
            try (AndroidArchiveStore store=AndroidArchiveStore.create(context,first,key);
                 AndroidArchiveStore isolated=AndroidArchiveStore.create(context,second,other)) {
                store.save(secretDialog,-123,1,tl,text,false);
                require(store.list(secretDialog,0).get(0).text.equals(text));
                store.save(secretDialog,-123,1,tl,text,false);
                require(store.list(secretDialog,0).size()==1); // duplicate event
                store.save(secretDialog,-123,3,bytes("edited version"),"До правки",true);
                require(store.list(secretDialog,0).size()==2);
                require(store.list(secretDialog,0).get(0).media);
                require(store.list(channel,0).isEmpty() && isolated.list(secretDialog,0).isEmpty());
                isolated.save(secretDialog,-123,1,tl,"Другой аккаунт",false);
                rejects(IllegalArgumentException.class,()->store.save(0,1,1,tl,text,false));
                rejects(IllegalArgumentException.class,()->store.save(secretDialog,0,1,tl,text,false));
                rejects(IllegalArgumentException.class,()->store.save(secretDialog,1,4,tl,text,false));
                rejects(IllegalArgumentException.class,()->store.save(secretDialog,1,1,
                        new byte[AndroidArchiveStore.MAX_TL_BYTES+1],text,false));
                require(store.list(secretDialog,0).size()==2);
                rejects(IOException.class,()->AndroidArchiveStore.create(context,first,key));
            }
            try (AndroidArchiveStore reopened=AndroidArchiveStore.open(context,first,AndroidVaultKeys.load(first))) {
                List<AndroidArchiveStore.Entry> page=reopened.list(secretDialog,0);
                require(page.size()==2 && page.get(1).text.equals(text));
                require(reopened.list(secretDialog,page.get(0).id).size()==1);
                for(int i=1;i<=AndroidArchiveStore.MAX_ROWS+1;i++)
                    reopened.save(channel,i,1,bytes("quota-"+i),"message-"+i,false);
                int count=0;long before=0;
                for(;;) {
                    page=reopened.list(channel,before);
                    if(page.isEmpty())break;
                    require(page.size()<=AndroidArchiveStore.PAGE_SIZE);
                    for(AndroidArchiveStore.Entry entry:page) {
                        require(entry.message>1);
                        if(before>0)require(entry.id<before);
                        before=entry.id;count++;
                    }
                }
                require(count==AndroidArchiveStore.MAX_ROWS && reopened.list(secretDialog,0).isEmpty());
            }
            byte[] original;
            try (SQLiteDatabase raw=SQLiteDatabase.openDatabase(AndroidArchiveStore.file(context,second).toString(),
                    null,SQLiteDatabase.OPEN_READWRITE)) {
                try(Cursor c=raw.rawQuery("SELECT payload FROM snapshots",null)) {
                    require(c.moveToFirst());original=c.getBlob(0);
                    require(!new String(original,StandardCharsets.ISO_8859_1).contains("synthetic-message"));
                }
                ContentValues change=new ContentValues();byte[] bad=original.clone();bad[bad.length-1]^=1;
                change.put("payload",bad);require(raw.update("snapshots",change,null,null)==1);
            }
            try(AndroidArchiveStore broken=AndroidArchiveStore.open(context,second,other)) {
                rejects(GeneralSecurityException.class,()->broken.list(secretDialog,0));
            }
            try(SQLiteDatabase raw=SQLiteDatabase.openDatabase(AndroidArchiveStore.file(context,second).toString(),
                    null,SQLiteDatabase.OPEN_READWRITE)) {
                ContentValues change=new ContentValues();change.put("payload",original);change.put("dialog_id",channel);
                require(raw.update("snapshots",change,null,null)==1);
            }
            try(AndroidArchiveStore swapped=AndroidArchiveStore.open(context,second,other)) {
                rejects(IOException.class,()->swapped.list(channel,0));
            }
            try(AndroidArchiveStore wrongKey=AndroidArchiveStore.open(context,second,key)) {
                rejects(GeneralSecurityException.class,()->wrongKey.list(channel,0));
            }
            rejects(IOException.class,()->AndroidArchiveStore.open(context,missing,key));
            require(!AndroidArchiveStore.file(context,missing).exists());
            try(SQLiteDatabase raw=SQLiteDatabase.openDatabase(AndroidArchiveStore.file(context,second).toString(),
                    null,SQLiteDatabase.OPEN_READWRITE)) { raw.setVersion(99); }
            byte[] before=Files.readAllBytes(AndroidArchiveStore.file(context,second).toPath());
            rejects(IOException.class,()->AndroidArchiveStore.open(context,second,other));
            require(Arrays.equals(before,Files.readAllBytes(AndroidArchiveStore.file(context,second).toPath())));
        } finally {
            if(firstKey)AndroidVaultKeys.delete(first);
            if(secondKey)AndroidVaultKeys.delete(second);
            SQLiteDatabase.deleteDatabase(AndroidArchiveStore.file(context,first));
            SQLiteDatabase.deleteDatabase(AndroidArchiveStore.file(context,second));
        }
    }
    private <T> T call(AndroidArchiveCoordinator c,AndroidArchiveCoordinator.Token token,
            AndroidArchiveCoordinator.Work<T> operation) throws Exception {
        CountDownLatch done=new CountDownLatch(1);AtomicReference<T> value=new AtomicReference<>();
        AtomicBoolean failed=new AtomicBoolean();
        c.submit(token,operation,(result,error)->{value.set(result);failed.set(error);done.countDown();});
        require(done.await(20,TimeUnit.SECONDS) && !failed.get());return value.get();
    }
    private void exerciseCoordinator() throws Exception {
        Context context=getTargetContext();String prefix="archive-test-"+UUID.randomUUID()+"-";
        AtomicLongArray owners=new AtomicLongArray(new long[]{100,200});AtomicBoolean unlocked=new AtomicBoolean(true);
        AndroidArchiveCoordinator.Host host=new AndroidArchiveCoordinator.Host() {
            @Override public long currentOwner(int account){return owners.get(account);}
            @Override public boolean unlocked(){return unlocked.get();}
            @Override public SharedPreferences preferences(int account){return context.getSharedPreferences(prefix+account,Context.MODE_PRIVATE);}
            @Override public void storageProblem(){ }
        };
        AndroidArchiveCoordinator c=new AndroidArchiveCoordinator(context,host,2);
        AndroidArchiveCoordinator.Token original=c.capture(0);
        require(c.persistBackground(c.captureBackground(0),store->{store.save(42,1,1,bytes("sync"),"committed",false);return null;}));
        require(call(c,original,store->store.list(42,0)).size()==1);
        require(call(c,c.capture(1),store->store.list(42,0)).isEmpty());
        require(c.capture(-1)==null && c.captureBackground(2)==null);
        unlocked.set(false);c.onLock();
        require(!c.isCurrent(original) && c.capture(0)==null);
        require(c.persistBackground(c.captureBackground(0),store->{store.save(42,2,1,bytes("locked"),"while locked",false);return null;}));
        unlocked.set(true);
        require(call(c,c.capture(0),store->store.list(42,0)).size()==2);
        AndroidArchiveCoordinator.Token background=c.captureBackground(0);
        AtomicBoolean deniedUi=new AtomicBoolean();
        runOnMainSync(()->{
            try {c.persistBackground(background,store->null);}
            catch(IllegalStateException expected){deniedUi.set(true);}
        });
        require(deniedUi.get());
        AndroidArchiveCoordinator.Token old=c.capture(0);
        UUID oldGeneration=UUID.fromString(host.preferences(0).getString("capy_archive_generation",""));
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        AtomicBoolean staleCallback=new AtomicBoolean();
        c.submit(old,store->{entered.countDown();if(!release.await(20,TimeUnit.SECONDS))throw new IOException("barrier");return true;},
                (result,error)->staleCallback.set(true));
        require(entered.await(20,TimeUnit.SECONDS));
        c.onLogout(0);owners.set(0,101);c.onOwnerChanged(0,0,101);release.countDown();
        require(call(c,c.capture(0),store->store.list(42,0)).isEmpty());
        require(!staleCallback.get() && !c.isCurrent(old) && !c.isCurrent(background));
        require(!AndroidArchiveStore.file(context,oldGeneration).exists());
        rejects(GeneralSecurityException.class,()->AndroidVaultKeys.load(oldGeneration));
        require(!c.persistBackground(background,store->{throw new AssertionError("Stale archive write");}));
        require(c.persistBackground(c.captureBackground(0),store->{store.save(42,3,1,bytes("clear"),"clear me",false);return null;}));
        UUID clearGeneration=UUID.fromString(host.preferences(0).getString("capy_archive_generation",""));
        c.clearArchive(0);
        require(owners.get(0)==101 && call(c,c.capture(0),store->store.list(42,0)).isEmpty());
        rejects(GeneralSecurityException.class,()->AndroidVaultKeys.load(clearGeneration));
        require(!AndroidArchiveStore.file(context,clearGeneration).exists());
        c.onLogout(0);c.onLogout(1);
    }
}
