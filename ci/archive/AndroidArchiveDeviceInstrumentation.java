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
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.File;
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
            exerciseOriginals();
            exerciseSource();
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
    private static InputStream repeated(long length) {
        return new InputStream() {
            long left=length;
            @Override public int read(){if(left==0)return -1;left--;return 42;}
            @Override public int read(byte[] out,int offset,int count){
                if(count==0)return 0;if(left==0)return -1;int n=(int)Math.min(left,count);
                Arrays.fill(out,offset,offset+n,(byte)42);left-=n;return n;
            }
        };
    }
    private void exerciseOriginals() throws Exception {
        Context context=getTargetContext();UUID generation=UUID.randomUUID();SecretKey key=AndroidVaultKeys.create(generation);
        long id;byte[] body=new byte[140001];
        for(int i=0;i<body.length;i++)body[i]=(byte)(i*31);
        try {
            try(AndroidArchiveStore store=AndroidArchiveStore.create(context,generation,key)) {
                id=store.save(99,1,1,bytes("original"),"caption",true);
                require(id==store.save(99,1,1,bytes("original"),"caption",true));
                rejects(IOException.class,()->store.saveOriginal(id,new ByteArrayInputStream(body),body.length+1,"video/mp4"));
                require(store.originalInfo(id)==null);
                rejects(IOException.class,()->store.saveOriginal(id,new ByteArrayInputStream(body),body.length-1,"video/mp4"));
                require(store.originalInfo(id)==null);
                rejects(IllegalArgumentException.class,()->store.saveOriginal(id,repeated(1),AndroidArchiveStore.MAX_ORIGINAL_BYTES+1,"video/mp4"));
                rejects(IllegalArgumentException.class,()->store.saveOriginal(id,repeated(1),1,"../private"));
                rejects(IOException.class,()->store.saveOriginal(id+1,repeated(1),1,"audio/ogg"));
                store.saveOriginal(id,new ByteArrayInputStream(body),body.length,"video/mp4");
                require(store.originalInfo(id).size==body.length && store.list(99,0).get(0).original.chunks==3);
                ByteArrayOutputStream restored=new ByteArrayOutputStream();store.writeOriginal(id,restored);
                require(Arrays.equals(body,restored.toByteArray()));
                store.saveOriginal(id,repeated(1),1,"audio/ogg"); // existing verified original is preserved
                require(store.originalInfo(id).size==body.length);
                try(ArchiveMediaBuffer buffer=new ArchiveMediaBuffer(store.originalInfo(id))) {
                    store.writeOriginal(id,buffer);android.media.MediaDataSource source=buffer.source();
                    byte[] sample=new byte[7];require(source.readAt(65533,sample,0,7)==7);
                    require(Arrays.equals(sample,Arrays.copyOfRange(body,65533,65540)));
                    require(source.readAt(body.length,sample,0,7)==-1 && source.getSize()==body.length);
                    rejects(IOException.class,()->source.readAt(-1,sample,0,1));
                    source.close();rejects(IOException.class,source::getSize);
                }
            }
            byte[] encrypted;
            try(SQLiteDatabase raw=SQLiteDatabase.openDatabase(AndroidArchiveStore.file(context,generation).toString(),null,SQLiteDatabase.OPEN_READWRITE)) {
                try(Cursor c=raw.rawQuery("SELECT payload FROM original_parts WHERE part=2",null)){require(c.moveToFirst());encrypted=c.getBlob(0);}
                ContentValues change=new ContentValues();byte[] bad=encrypted.clone();bad[bad.length-1]^=1;change.put("payload",bad);
                require(raw.update("original_parts",change,"part=2",null)==1);
            }
            try(AndroidArchiveStore store=AndroidArchiveStore.open(context,generation,key)) {
                rejects(GeneralSecurityException.class,()->store.writeOriginal(id,new ByteArrayOutputStream()));
            }
            try(SQLiteDatabase raw=SQLiteDatabase.openDatabase(AndroidArchiveStore.file(context,generation).toString(),null,SQLiteDatabase.OPEN_READWRITE)) {
                ContentValues change=new ContentValues();change.put("payload",encrypted);raw.update("original_parts",change,"part=2",null);
                raw.delete("original_parts","part=3",null);
            }
            try(AndroidArchiveStore store=AndroidArchiveStore.open(context,generation,key)) {
                rejects(IOException.class,()->store.writeOriginal(id,new ByteArrayOutputStream()));
                // Four maximum-size originals exceed quota after authentication overhead.
                for(int i=2;i<=5;i++) {
                    long row=store.save(99,i,1,bytes("quota-original-"+i),"file",true);
                    store.saveOriginal(row,repeated(AndroidArchiveStore.MAX_ORIGINAL_BYTES),AndroidArchiveStore.MAX_ORIGINAL_BYTES,"audio/ogg");
                    require(store.originalInfo(row).size==AndroidArchiveStore.MAX_ORIGINAL_BYTES);
                }
                require(store.originalInfo(id)==null && store.list(99,0).get(3).original==null);
                require(store.list(99,0).get(0).original!=null && store.list(99,0).get(2).original!=null);
            }
            byte[] snapshot;
            try(SQLiteDatabase raw=SQLiteDatabase.openDatabase(AndroidArchiveStore.file(context,generation).toString(),null,SQLiteDatabase.OPEN_READWRITE)) {
                try(Cursor c=raw.rawQuery("SELECT payload FROM snapshots WHERE id="+id,null)){require(c.moveToFirst());snapshot=c.getBlob(0);}
                raw.execSQL("DROP TABLE original_parts");raw.execSQL("DROP TABLE originals");raw.setVersion(1);
            }
            try(AndroidArchiveStore migrated=AndroidArchiveStore.open(context,generation,key)) {
                require(migrated.list(99,0).size()==5 && migrated.originalInfo(id)==null);
                try(SQLiteDatabase raw=SQLiteDatabase.openDatabase(AndroidArchiveStore.file(context,generation).toString(),null,SQLiteDatabase.OPEN_READONLY)) {
                    try(Cursor c=raw.rawQuery("SELECT payload FROM snapshots WHERE id="+id,null)) {
                        require(c.moveToFirst() && Arrays.equals(snapshot,c.getBlob(0)));
                    }
                }

                migrated.saveOriginal(id,new ByteArrayInputStream(body),body.length,"video/mp4");
                ByteArrayOutputStream output=new ByteArrayOutputStream();migrated.writeOriginal(id,output);
                require(Arrays.equals(body,output.toByteArray()));
                for(int i=1;i<=AndroidArchiveStore.MAX_ROWS;i++)migrated.save(100,i,1,bytes("prune-original-"+i),"",false);
                require(migrated.originalInfo(id)==null);
            }
            try(SQLiteDatabase raw=SQLiteDatabase.openDatabase(AndroidArchiveStore.file(context,generation).toString(),null,SQLiteDatabase.OPEN_READONLY)) {
                require(raw.getVersion()==2);
                try(Cursor c=raw.rawQuery("SELECT count(*) FROM original_parts",null)){require(c.moveToFirst() && c.getLong(0)==0);}
            }
        } finally {Arrays.fill(body,(byte)0);AndroidVaultKeys.delete(generation);SQLiteDatabase.deleteDatabase(AndroidArchiveStore.file(context,generation));}
    }
    private void exerciseSource() throws Exception {
        File file=new File(getTargetContext().getCacheDir(),"synthetic-original.bin"),keyFile=new File(getTargetContext().getCacheDir(),"synthetic-key.bin");
        try {
            byte[] body=bytes("123456789");Files.write(file.toPath(),body);Files.write(keyFile.toPath(),new byte[48]);
            try(VerifiedMediaInput input=VerifiedMediaInput.open(file,body.length,null,null)) {
                require(file.delete() && !file.exists());
                byte[] copy=new byte[body.length];require(input.read(copy)==copy.length && input.read()==-1);
                require(input.read(copy,0,0)==0 && Arrays.equals(body,copy));
            }
            Files.write(file.toPath(),body);
            int[] position={0};
            try(VerifiedMediaInput input=VerifiedMediaInput.open(file,body.length,keyFile,(out,key,iv,start,count,offset)->{
                if(offset!=position[0] || count<=0)throw new AssertionError("Wrong decrypt range");position[0]+=count;
                for(int i=start;i<start+count;i++)out[i]^=1;
            })) {
                byte[] copy=new byte[20];require(input.read(copy,2,3)==3 && input.read(copy,5,15)==6);
                require(input.read(copy)==-1 && position[0]==body.length && copy[0]==0 && copy[11]==0);
                require(copy[2]==(body[0]^1) && copy[10]==(body[8]^1));
            }
            rejects(IOException.class,()->VerifiedMediaInput.open(file,body.length+1,null,null));
            Files.write(keyFile.toPath(),new byte[47]);rejects(IOException.class,()->VerifiedMediaInput.open(file,body.length,keyFile,(a,b,c,d,e,f)->{}));
        } finally {file.delete();keyFile.delete();}
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
        exerciseViewedCoordinator();
    }

    private void exerciseViewedCoordinator() throws Exception {
        Context context=getTargetContext();String prefix="archive-viewed-test-"+UUID.randomUUID()+"-";
        AtomicLongArray owners=new AtomicLongArray(new long[]{300,400});
        AndroidArchiveCoordinator.Host host=new AndroidArchiveCoordinator.Host() {
            @Override public long currentOwner(int account){return owners.get(account);}
            @Override public boolean unlocked(){return true;}
            @Override public SharedPreferences preferences(int account){return context.getSharedPreferences(prefix+account,Context.MODE_PRIVATE);}
            @Override public void storageProblem(){ }
        };
        AndroidArchiveCoordinator c=new AndroidArchiveCoordinator(context,host,2);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),cleaned=new CountDownLatch(1);
        c.submit(c.capture(0),store->{entered.countDown();if(!release.await(20,TimeUnit.SECONDS))throw new IOException("barrier");return true;},(value,error)->{});
        require(entered.await(20,TimeUnit.SECONDS));
        File file=new File(context.getCacheDir(),"viewed-original-test.bin");byte[] body=bytes("original-before-once-unlink");
        Files.write(file.toPath(),body);
        VerifiedMediaInput input=VerifiedMediaInput.open(file,body.length,null,null);
        AtomicBoolean accepted=new AtomicBoolean();
        runOnMainSync(()->accepted.set(c.persistViewed(c.captureBackground(0),store->{
            long id=store.save(55,1,2,bytes("once-tl"),"once caption",true);
            store.saveOriginal(id,input,body.length,"audio/ogg");return null;
        },()->{try{input.close();}catch(IOException ignored){}cleaned.countDown();})));
        // UI returned while the worker is deliberately blocked; no synchronous wait.
        require(accepted.get() && cleaned.getCount()==1 && file.delete());
        release.countDown();require(cleaned.await(20,TimeUnit.SECONDS));
        byte[] restored=call(c,c.capture(0),store->{
            long id=store.list(55,0).get(0).id;ByteArrayOutputStream out=new ByteArrayOutputStream();store.writeOriginal(id,out);return out.toByteArray();
        });
        require(Arrays.equals(body,restored));Arrays.fill(restored,(byte)0);Arrays.fill(body,(byte)0);
        rejects(IOException.class,()->input.read());

        CountDownLatch waiting=new CountDownLatch(1),resume=new CountDownLatch(1),discarded=new CountDownLatch(4);
        c.submit(c.capture(0),store->{waiting.countDown();if(!resume.await(20,TimeUnit.SECONDS))throw new IOException("barrier");return true;},(value,error)->{});
        require(waiting.await(20,TimeUnit.SECONDS));
        AndroidArchiveCoordinator.Token old=c.captureBackground(0);
        AtomicBoolean staleWrite=new AtomicBoolean();java.util.concurrent.atomic.AtomicInteger cleanupCount=new java.util.concurrent.atomic.AtomicInteger();
        for(int i=0;i<4;i++)require(c.persistViewed(old,store->{staleWrite.set(true);return null;},()->{cleanupCount.incrementAndGet();discarded.countDown();}));
        AtomicBoolean overflowClosed=new AtomicBoolean();
        require(!c.persistViewed(old,store->{throw new AssertionError("Overflow work ran");},()->overflowClosed.set(true)));
        require(overflowClosed.get());
        c.onLogout(0);owners.set(0,301);c.onOwnerChanged(0,300,301);resume.countDown();
        require(discarded.await(20,TimeUnit.SECONDS) && cleanupCount.get()==4 && !staleWrite.get());
        require(call(c,c.capture(0),store->store.list(55,0)).isEmpty());
        CountDownLatch failedCleanup=new CountDownLatch(1);
        require(c.persistViewed(c.captureBackground(0),store->{throw new IOException("synthetic operation failure");},failedCleanup::countDown));
        require(failedCleanup.await(20,TimeUnit.SECONDS));
        c.onLogout(0);c.onLogout(1);file.delete();
    }
}
