// SPDX-License-Identifier: MIT
package org.capybaragram.voice;

import android.os.Build;
import org.capybaragram.local.AndroidVaultCoordinator;
import org.capybaragram.telegram.CapyVault;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.ApplicationLoader;
import org.telegram.messenger.FileLoader;
import org.telegram.messenger.LocaleController;
import org.telegram.messenger.MessageObject;
import org.telegram.messenger.R;
import org.telegram.ui.ActionBar.AlertDialog;
import org.telegram.ui.ActionBar.BaseFragment;
import java.io.File;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** Local-only voice result. No send, premium RPC or listening acknowledgement. */
public final class CapyVoiceUi {
    private static final ExecutorService worker=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"CapybaraGram-speech");t.setDaemon(true);return t;});
    private static AlertDialog current;
    private static BaseFragment owner;
    private static Job active;
    private CapyVoiceUi(){}
    public interface Current { boolean matches(); }
    private static String text(int id){return LocaleController.getString(id);}
    private static final class Job implements SpeechModel.Status {
        final AtomicBoolean cancelled=new AtomicBoolean();
        volatile OfflineSpeech speech;
        volatile int percent;
        volatile boolean downloading;
        void cancel(){cancelled.set(true);OfflineSpeech value=speech;if(value!=null)value.cancel();}
        @Override public boolean cancelled(){return cancelled.get();}
        @Override public void progress(long received,long total){percent=(int)(100*received/total);}
    }
    public static void closeAll(){
        Job job=active;active=null;if(job!=null)job.cancel();
        AlertDialog previous=current;current=null;owner=null;if(previous!=null)previous.dismiss();
    }
    public static void closeFor(BaseFragment fragment){if(fragment==owner)closeAll();}
    private static boolean available(BaseFragment fragment,Current location,AndroidVaultCoordinator c,AndroidVaultCoordinator.Token token){
        return fragment.getParentActivity()!=null&&location.matches()&&!AndroidUtilities.needShowPasscode()&&c.isCurrent(token);
    }
    private static void display(BaseFragment fragment,AlertDialog dialog,Job job){
        closeAll();current=dialog;owner=fragment;active=job;
        if(fragment.showDialog(dialog,ignored->{if(current==dialog)closeAll();})==null&&current==dialog)closeAll();
    }
    public static void show(BaseFragment fragment,int account,MessageObject message,Current location){
        if(Build.VERSION.SDK_INT<23||message==null||!message.isVoice()||message.getDocument()==null)return;
        AndroidVaultCoordinator c=CapyVault.get();AndroidVaultCoordinator.Token token=c.capture(account);
        if(!available(fragment,location,c,token))return;
        AlertDialog.Builder b=new AlertDialog.Builder(fragment.getParentActivity());
        b.setTitle(text(R.string.CapySpeech));b.setMessage(text(R.string.CapySpeechDescription));
        b.setNegativeButton(text(R.string.Cancel),null);
        b.setPositiveButton(text(R.string.CapySpeechStart),(d,w)->start(fragment,account,message,location,c,token,false));
        display(fragment,b.create(),null);
    }
    private static void start(BaseFragment fragment,int account,MessageObject message,Current location,
            AndroidVaultCoordinator c,AndroidVaultCoordinator.Token token,boolean download){
        if(!available(fragment,location,c,token))return;
        Job job=new Job();AlertDialog.Builder b=new AlertDialog.Builder(fragment.getParentActivity());
        b.setTitle(text(R.string.CapySpeech));b.setMessage(text(R.string.CapySpeechWorking));
        b.setNegativeButton(text(R.string.Cancel),(d,w)->job.cancel());
        AlertDialog waiting=b.create();display(fragment,waiting,job);
        Runnable progress=new Runnable(){@Override public void run(){
            if(active!=job||current!=waiting)return;
            if(!available(fragment,location,c,token)){closeAll();return;}
            int value=job.speech==null?job.percent:job.speech.progress();
            waiting.setMessage(text(job.downloading?R.string.CapySpeechDownloading:R.string.CapySpeechWorking)+" · "+value+"%");
            AndroidUtilities.runOnUIThread(this,500);
        }};
        AndroidUtilities.runOnUIThread(progress,500);
        worker.execute(()->{
            String result=null;boolean needModel=false;boolean failed=false;float[] pcm=null;
            try {
                if(job.cancelled()||!c.isCurrent(token))return;
                File model=SpeechModel.existing(ApplicationLoader.applicationContext);
                if(model==null&&!download){needModel=true;}
                else {
                    if(model==null){job.downloading=true;model=SpeechModel.download(ApplicationLoader.applicationContext,job);job.downloading=false;}
                    if(job.cancelled()||!c.isCurrent(token))return;
                    File audio=FileLoader.getInstance(account).getPathToMessage(message.messageOwner,true);
                    pcm=AndroidPcmDecoder.decode(audio,job::cancelled);
                    if(job.cancelled()||!c.isCurrent(token))return;
                    OfflineSpeech speech=new OfflineSpeech();job.speech=speech;
                    if(job.cancelled())speech.cancel();
                    result=speech.run(model,pcm,"auto");
                }
            } catch(Exception|LinkageError|OutOfMemoryError failure){failed=true;}
            finally {if(pcm!=null)Arrays.fill(pcm,0f);}
            final String transcript=result;final boolean missing=needModel,error=failed;
            AndroidUtilities.runOnUIThread(()->{
                if(active!=job||current!=waiting||job.cancelled()||!available(fragment,location,c,token))return;
                AlertDialog.Builder done=new AlertDialog.Builder(fragment.getParentActivity());
                done.setTitle(text(R.string.CapySpeech));done.setNegativeButton(text(R.string.Close),null);
                if(missing){
                    done.setMessage(text(R.string.CapySpeechModel));
                    done.setPositiveButton(text(R.string.CapySpeechDownload),(d,w)->start(fragment,account,message,location,c,token,true));
                } else {
                    done.setMessage(error?text(R.string.CapySpeechFailure):transcript==null||transcript.isEmpty()?text(R.string.CapySpeechEmpty):transcript);
                    if(!error&&transcript!=null&&!transcript.isEmpty())done.setPositiveButton(text(R.string.Copy),(d,w)->{
                        if(available(fragment,location,c,token))AndroidUtilities.addToClipboard(transcript);
                    });
                }
                display(fragment,done.create(),null);
            });
        });
    }
}
