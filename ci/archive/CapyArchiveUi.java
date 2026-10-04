// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.LocaleController;
import org.telegram.messenger.R;
import org.telegram.ui.ActionBar.AlertDialog;
import org.telegram.ui.ActionBar.BaseFragment;
import java.text.DateFormat;
import java.util.Date;
import java.util.List;
import android.graphics.Bitmap;
import android.media.MediaPlayer;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import java.io.IOException;
import java.util.ArrayList;

/** Read-only native archive pages; never inserts or sends a stored message. */
public final class CapyArchiveUi {
    private static AlertDialog current;
    private static BaseFragment owner;
    private static Loaded media;
    private static MediaPlayer player;
    private static ImageView image;
    private CapyArchiveUi() {}
    public interface Current { boolean matches(); }
    private static String text(int id) { return LocaleController.getString(id); }

    public static void closeAll() {
        AlertDialog previous=current; current=null; owner=null;
        if (previous != null) previous.dismiss();
        releaseMedia();
    }
    private static void releaseMedia() {
        if(player!=null){player.release();player=null;}
        if(image!=null){image.setImageDrawable(null);image=null;}
        if(media!=null){media.close();media=null;}
    }
    public static void closeFor(BaseFragment fragment) { if (fragment == owner) closeAll(); }
    private static void display(BaseFragment fragment, AlertDialog dialog) {
        closeAll(); current=dialog; owner=fragment;
        android.content.DialogInterface.OnDismissListener listener=ignored -> {
            if (current == dialog) { current=null; owner=null; releaseMedia(); }
        };
        if (fragment.showDialog(dialog, listener) == null && current == dialog) { current=null; owner=null; }
    }

    private static boolean available(BaseFragment fragment, Current location,
            AndroidArchiveCoordinator coordinator, AndroidArchiveCoordinator.Token token) {
        return fragment.getParentActivity() != null && location.matches()
                && !AndroidUtilities.needShowPasscode() && coordinator.isCurrent(token);
    }

    public static void show(BaseFragment fragment, int account, long dialog, String name, Current location) {
        AndroidArchiveCoordinator coordinator=CapyMessageArchive.get();
        AndroidArchiveCoordinator.Token token=coordinator.capture(account);
        if (!available(fragment,location,coordinator,token)) return;
        boolean enabled=CapyMessageArchive.enabled(account);
        AlertDialog.Builder b=new AlertDialog.Builder(fragment.getParentActivity());
        b.setTitle(text(R.string.CapyArchive));
        b.setMessage(text(R.string.CapyArchiveDescription));
        b.setNegativeButton(text(R.string.Cancel), null);
        b.setPositiveButton(text(enabled ? R.string.CapyArchiveDisable : R.string.CapyArchiveEnable), (d,w) -> {
            if (!available(fragment,location,coordinator,token)) return;
            if (!CapyMessageArchive.setEnabled(account,token.owner,!enabled)) {
                AlertDialog.Builder error=new AlertDialog.Builder(fragment.getParentActivity());
                error.setTitle(text(R.string.CapyArchive)); error.setMessage(text(R.string.CapyArchiveFailure));
                error.setNegativeButton(text(R.string.Close),null);
                display(fragment,error.create());
            }
        });
        b.setNeutralButton(text(R.string.CapyArchiveOpen), (d,w) -> page(fragment,account,dialog,name,location,0));
        display(fragment,b.create());
    }

    private static void page(BaseFragment fragment, int account, long dialog, String name, Current location, long before) {
        AndroidArchiveCoordinator coordinator=CapyMessageArchive.get();
        AndroidArchiveCoordinator.Token token=coordinator.capture(account);
        if (!available(fragment,location,coordinator,token)) return;
        AlertDialog.Builder loading=new AlertDialog.Builder(fragment.getParentActivity());
        loading.setTitle(text(R.string.CapyArchive)); loading.setMessage(text(R.string.CapyArchiveLoading));
        loading.setNegativeButton(text(R.string.Cancel), null);
        AlertDialog waiting=loading.create(); display(fragment,waiting);
        coordinator.submit(token, store -> store.list(dialog,before), (entries,failed) -> {
            if (!available(fragment,location,coordinator,token) || current != waiting) return;
            AlertDialog.Builder b=new AlertDialog.Builder(fragment.getParentActivity());
            b.setTitle(text(R.string.CapyArchive)+" · "+name);
            StringBuilder body=new StringBuilder();
            long next=0;
            if (failed || entries == null) body.append(text(R.string.CapyArchiveFailure));
            else if (entries.isEmpty()) body.append(text(R.string.CapyArchiveEmpty));
            else for (AndroidArchiveStore.Entry entry : entries) {
                next=entry.id;
                body.append(DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(new Date(entry.savedAt))).append(" · ");
                body.append(text(entry.reason == CapyMessageArchive.DELETED ? R.string.CapyArchiveDeleted
                        : entry.reason == CapyMessageArchive.EXPIRED_MEDIA ? R.string.CapyArchiveExpired : R.string.CapyArchiveEdited));
                body.append("\n").append(entry.text.isEmpty() ? text(R.string.CapyArchiveNoText)
                        : entry.text);
                if (entry.media) body.append("\n").append(text(entry.original==null
                        ? R.string.CapyArchiveOriginalMissing : R.string.CapyArchiveOriginalSaved));
                body.append("\n\n");
            }
            b.setMessage(body.toString());
            if (!failed && entries!=null) {
                ArrayList<AndroidArchiveStore.Entry> originals=new ArrayList<>();
                for(AndroidArchiveStore.Entry entry:entries)if(entry.original!=null)originals.add(entry);
                if(!originals.isEmpty()) {
                    CharSequence[] labels=new CharSequence[originals.size()];
                    for(int i=0;i<labels.length;i++) {
                        AndroidArchiveStore.Entry entry=originals.get(i);
                        labels[i]=text(R.string.CapyArchiveViewOriginal)+" · #"+entry.message+" · "+entry.original.mime;
                    }
                    b.setItems(labels,(d,index)->{
                        if(available(fragment,location,coordinator,token) && index>=0 && index<originals.size())
                            viewOriginal(fragment,location,coordinator,token,originals.get(index).id);
                    });
                }
            }
            b.setNegativeButton(text(R.string.Close),null);
            if (!failed && entries != null && entries.size() == AndroidArchiveStore.PAGE_SIZE) {
                final long cursor=next;
                b.setPositiveButton(text(R.string.CapyArchiveOlder),(d,w) -> {
                    if (available(fragment,location,coordinator,token)) page(fragment,account,dialog,name,location,cursor);
                });
            }
            b.setNeutralButton(text(R.string.CapyArchiveClear),(d,w) -> {
                if (!available(fragment,location,coordinator,token)) return;
                AlertDialog.Builder confirm=new AlertDialog.Builder(fragment.getParentActivity());
                confirm.setTitle(text(R.string.CapyArchiveClear)); confirm.setMessage(text(R.string.CapyArchiveClearConfirm));
                confirm.setNegativeButton(text(R.string.Cancel),null);
                confirm.setPositiveButton(text(R.string.CapyArchiveClear),(accepted,which) -> {
                    if (available(fragment,location,coordinator,token)) coordinator.clearArchive(account);
                });
                display(fragment,confirm.create());
            });
            display(fragment,b.create());
        });
    }

    private static final class Loaded {
        final ArchiveMediaBuffer buffer;
        Bitmap bitmap;
        Loaded(ArchiveMediaBuffer buffer){this.buffer=buffer;}
        void close(){buffer.close();if(bitmap!=null){bitmap.recycle();bitmap=null;}}
    }
    private static void viewOriginal(BaseFragment fragment,Current location,AndroidArchiveCoordinator coordinator,
            AndroidArchiveCoordinator.Token token,long id) {
        if(!available(fragment,location,coordinator,token))return;
        AlertDialog.Builder loading=new AlertDialog.Builder(fragment.getParentActivity());
        loading.setTitle(text(R.string.CapyArchiveViewOriginal));loading.setMessage(text(R.string.CapyArchiveLoading));
        loading.setNegativeButton(text(R.string.Cancel),null);
        AlertDialog waiting=loading.create();display(fragment,waiting);
        coordinator.submit(token,store->{
            AndroidArchiveStore.Original descriptor=store.originalInfo(id);
            if(descriptor==null)throw new IOException("Original unavailable.");
            Loaded loaded=new Loaded(new ArchiveMediaBuffer(descriptor));
            try {
                store.writeOriginal(id,loaded.buffer);
                if(descriptor.mime.startsWith("image/"))loaded.bitmap=loaded.buffer.image();
                return loaded;
            }catch(Exception|OutOfMemoryError error){loaded.close();throw new IOException("Original preview unavailable.");}
        },(loaded,failed)->{
            if(!available(fragment,location,coordinator,token) || current!=waiting) {
                if(loaded!=null)loaded.close();return;
            }
            AlertDialog.Builder b=new AlertDialog.Builder(fragment.getParentActivity());
            b.setTitle(text(R.string.CapyArchiveViewOriginal));b.setNegativeButton(text(R.string.Close),null);
            if(failed || loaded==null){b.setMessage(text(R.string.CapyArchiveOriginalFailure));display(fragment,b.create());return;}
            LinearLayout layout=new LinearLayout(fragment.getParentActivity());layout.setOrientation(LinearLayout.VERTICAL);
            ImageView preview=null;MediaPlayer prepared=null;
            try {
                if(loaded.bitmap!=null) {
                    preview=new ImageView(fragment.getParentActivity());preview.setScaleType(ImageView.ScaleType.FIT_CENTER);
                    preview.setImageBitmap(loaded.bitmap);layout.addView(preview,new LinearLayout.LayoutParams(-1,AndroidUtilities.dp(280)));
                } else if(loaded.buffer.original.mime.startsWith("audio/") || loaded.buffer.original.mime.startsWith("video/")) {
                    prepared=new MediaPlayer();MediaPlayer playback=prepared;
                    playback.setDataSource(loaded.buffer.source());
                    if(loaded.buffer.original.mime.startsWith("video/")) {
                        SurfaceView surface=new SurfaceView(fragment.getParentActivity());
                        layout.addView(surface,new LinearLayout.LayoutParams(-1,AndroidUtilities.dp(240)));
                        surface.getHolder().addCallback(new SurfaceHolder.Callback(){
                            @Override public void surfaceCreated(SurfaceHolder holder){if(player==playback)playback.setDisplay(holder);}
                            @Override public void surfaceChanged(SurfaceHolder holder,int format,int width,int height){}
                            @Override public void surfaceDestroyed(SurfaceHolder holder){if(player==playback)playback.setDisplay(null);}
                        });
                    }
                    Button play=new Button(fragment.getParentActivity());play.setText(text(R.string.CapyArchivePlay));play.setEnabled(false);
                    layout.addView(play,new LinearLayout.LayoutParams(-1,AndroidUtilities.dp(52)));
                    playback.setOnPreparedListener(p->{if(player==p)play.setEnabled(true);});
                    playback.setOnCompletionListener(p->{if(player==p)play.setText(text(R.string.CapyArchivePlay));});
                    playback.setOnErrorListener((p,what,extra)->{
                        if(player==p && available(fragment,location,coordinator,token)) {
                            AlertDialog.Builder error=new AlertDialog.Builder(fragment.getParentActivity());
                            error.setTitle(text(R.string.CapyArchiveViewOriginal));error.setMessage(text(R.string.CapyArchiveOriginalFailure));
                            error.setNegativeButton(text(R.string.Close),null);display(fragment,error.create());
                        }
                        return true;
                    });
                    play.setOnClickListener(v->{
                        if(player!=playback || !available(fragment,location,coordinator,token))return;
                        if(playback.isPlaying()){playback.pause();play.setText(text(R.string.CapyArchivePlay));}
                        else {playback.start();play.setText(text(R.string.CapyArchivePause));}
                    });
                } else {
                    loaded.close();b.setMessage(text(R.string.CapyArchiveUnsupported));display(fragment,b.create());return;
                }
                b.setView(layout);display(fragment,b.create());
                if(current==null){if(prepared!=null)prepared.release();loaded.close();return;}
                media=loaded;image=preview;player=prepared;
                if(prepared!=null)prepared.prepareAsync();
            }catch(Exception|OutOfMemoryError error){
                if(prepared!=null && prepared!=player)prepared.release();loaded.close();
                b=new AlertDialog.Builder(fragment.getParentActivity());b.setTitle(text(R.string.CapyArchiveViewOriginal));
                b.setMessage(text(R.string.CapyArchiveOriginalFailure));b.setNegativeButton(text(R.string.Close),null);display(fragment,b.create());
            }
        },Loaded::close);
    }
}
