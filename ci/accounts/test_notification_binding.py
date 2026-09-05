# SPDX-License-Identifier: MIT
"""Execute actual Java binding/receivers with explicit Android/storage fakes, not a device test."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import android_accounts_patch as patch

STUBS = {
'android/content/Context.java': 'package android.content; public class Context {}',
'android/content/BroadcastReceiver.java': 'package android.content; public abstract class BroadcastReceiver { public abstract void onReceive(Context c, Intent i); }',
'android/content/Intent.java': '''package android.content;
import java.util.HashMap; import android.net.Uri; import android.os.Bundle;
public class Intent {
 private final HashMap<String,Object> extras = new HashMap<>(); private Uri data;
 public Bundle reply;
 public Intent putExtra(String k, long v) { extras.put(k,v); return this; }
 public Intent putExtra(String k, int v) { extras.put(k,v); return this; }
 public Intent putExtra(String k, boolean v) { extras.put(k,v); return this; }
 public long getLongExtra(String k,long d) { return extras.containsKey(k)?((Number)extras.get(k)).longValue():d; }
 public int getIntExtra(String k,int d) { return extras.containsKey(k)?((Number)extras.get(k)).intValue():d; }
 public boolean getBooleanExtra(String k,boolean d) { return extras.containsKey(k)?(Boolean)extras.get(k):d; }
 public int[] getIntArrayExtra(String k) { return (int[])extras.get(k); }
 public Intent setData(Uri value) { data=value; return this; } public Uri getData(){return data;}
}''',
'android/net/Uri.java': '''package android.net;
public class Uri {
 private final String text; private Uri(String value){text=value;} public String toString(){return text;}
 public static class Builder { private String scheme, authority, path="";
 public Builder scheme(String value){scheme=value;return this;} public Builder authority(String value){authority=value;return this;}
 public Builder appendPath(String value){path+="/"+value;return this;} public Uri build(){return new Uri(scheme+"://"+authority+path);}
 }
}''',
'android/os/Bundle.java': 'package android.os; public class Bundle { public CharSequence getCharSequence(String key){return "reply";} }',
'android/text/TextUtils.java': 'package android.text; public class TextUtils { public static boolean isEmpty(CharSequence s){return s==null||s.length()==0;} }',
'androidx/core/app/RemoteInput.java': 'package androidx.core.app; import android.content.Intent; import android.os.Bundle; public class RemoteInput { public static Bundle getResultsFromIntent(Intent i){return i.reply;} }',
'org/telegram/tgnet/TLRPC.java': '''package org.telegram.tgnet; public class TLRPC {
 public static class User {} public static class Chat {}
 public static class TL_message { public String message; public int id; public Object peer_id; public TL_messageActionTopicCreate action; }
 public static class TL_messageActionTopicCreate { public String title; }
}''',
'org/telegram/messenger/UserConfig.java': '''package org.telegram.messenger; public class UserConfig {
 public static int selectedAccount=0; static final UserConfig[] slots = new UserConfig[10];
 static {for(int i=0;i<slots.length;i++)slots[i]=new UserConfig();} public long id;
 public long getClientUserId(){return id;} public static UserConfig getInstance(int slot){return slots[slot];}
 public static boolean isValidAccount(int slot){return slot>=0&&slot<slots.length&&slots[slot].id>0;}
}''',
'org/telegram/messenger/Fakes.java': '''package org.telegram.messenger;
import java.util.ArrayList; import org.telegram.tgnet.TLRPC;
class FakeState {
 static boolean cached; static int sends, reads, puts, marks, sender;
 static final ArrayList<Runnable> db=new ArrayList<>(), ui=new ArrayList<>();
 static void reset(){cached=false;sends=reads=puts=marks=0;sender=-1;db.clear();ui.clear();
  for(int i=0;i<10;i++)UserConfig.slots[i].id=10000+i;UserConfig.selectedAccount=0;}
 static void flush(ArrayList<Runnable> q){while(!q.isEmpty())q.remove(0).run();}
}
class ApplicationLoader {static void postInitApplication(){}}
class NotificationsController {static final String EXTRA_VOICE_REPLY="voice";}
class AndroidUtilities {static void runOnUIThread(Runnable r){FakeState.ui.add(r);}}
class Utilities {static final Queue globalQueue=new Queue();static class Queue {void postRunnable(Runnable r){FakeState.db.add(r);}}}
class DialogObject {static boolean isUserDialog(long id){return id>0;}static boolean isChatDialog(long id){return id<0;}}
class MessageObject {MessageObject(int a,TLRPC.TL_message m,boolean b,boolean c){}}
class AccountInstance {
 final int slot; AccountInstance(int n){slot=n;} static AccountInstance getInstance(int slot){return new AccountInstance(slot);}
 int getCurrentAccount(){return slot;} MessagesController getMessagesController(){return new MessagesController();}
 MessagesStorage getMessagesStorage(){return new MessagesStorage();} SendMessagesHelper getSendMessagesHelper(){return new SendMessagesHelper(slot);}
}
class MessagesController {
 static MessagesController getInstance(int slot){return new MessagesController();}
 TLRPC.User getUser(long id){return FakeState.cached?new TLRPC.User():null;}
 TLRPC.Chat getChat(long id){return FakeState.cached?new TLRPC.Chat():null;}
 void putUser(TLRPC.User user,boolean b){FakeState.puts++;} void putChat(TLRPC.Chat chat,boolean b){FakeState.puts++;}
 Object getPeer(long id){return new Object();} void markDialogAsRead(Object... args){FakeState.marks++;}
 void markReactionsAsRead(long id,long topic){FakeState.marks++;}
}
class MessagesStorage {
 TLRPC.User getUserSync(long id){FakeState.reads++;return new TLRPC.User();}
 TLRPC.Chat getChatSync(long id){FakeState.reads++;return new TLRPC.Chat();}
 void markVoiceMessageContentAsRead(long id,ArrayList<Integer> ids){}
}
class SendMessagesHelper {
 final int slot; SendMessagesHelper(int n){slot=n;} void sendMessage(SendMessageParams params){FakeState.sends++;FakeState.sender=slot;}
 static class SendMessageParams {static SendMessageParams of(Object... args){return new SendMessageParams();}}
}
''',
'org/telegram/messenger/BindingTest.java': '''package org.telegram.messenger;
import android.content.Intent; import android.os.Bundle; import android.content.BroadcastReceiver;
public class BindingTest {
 static int checks=0;
 static void check(boolean value,String name){checks++;if(!value)throw new AssertionError(name);}
 static Intent intent(int slot,long dialog){Intent i=new Intent().putExtra("dialog_id",dialog).putExtra("max_id",42);i.reply=new Bundle();return NotificationAccountBinding.bind(i,slot);}
 public static void main(String[] args){
  FakeState.reset(); Intent a=intent(0,123), b=intent(9,123);
  check(!a.getData().toString().equals(b.getData().toString()),"same chat, different account URI");
  check(NotificationAccountBinding.isCurrent(a,0),"owner matches");
  check(!NotificationAccountBinding.isCurrent(a,9),"wrong slot");
  check(!NotificationAccountBinding.isCurrent(null,0),"null intent");
  check(!NotificationAccountBinding.isCurrent(new Intent(),0),"unstamped old intent");
  check(!NotificationAccountBinding.isCurrent(-1,10000),"negative slot");
  check(!NotificationAccountBinding.isCurrent(10,10000),"capacity overflow");
  check(!NotificationAccountBinding.isCurrent(0,0),"zero identity");
  UserConfig.slots[0].id=999; Intent replacement=intent(0,123);
  check(!NotificationAccountBinding.isCurrent(a,0),"slot reused");
  check(!a.getData().toString().equals(replacement.getData().toString()),"reused slot URI differs");
  for(boolean heard:new boolean[]{false,true})for(long dialog:new long[]{123,-456}){
   BroadcastReceiver receiver=heard?new AutoMessageHeardReceiver():new WearReplyReceiver();
   FakeState.reset();FakeState.cached=true;a=intent(9,dialog);UserConfig.selectedAccount=0;
   receiver.onReceive(null,a);
   check(heard?FakeState.marks>0:(FakeState.sends==1&&FakeState.sender==9),"selected UI account does not change action account");
   FakeState.reset();a=intent(9,dialog);receiver.onReceive(null,a);UserConfig.slots[9].id=20009;
   FakeState.flush(FakeState.db);FakeState.flush(FakeState.ui);
   check(FakeState.reads==0&&FakeState.puts==0&&FakeState.sends==0&&FakeState.marks==0,"logout before DB");
   FakeState.reset();a=intent(9,dialog);receiver.onReceive(null,a);FakeState.flush(FakeState.db);UserConfig.slots[9].id=20009;
   FakeState.flush(FakeState.ui);
   check(FakeState.reads==1&&FakeState.puts==0&&FakeState.sends==0&&FakeState.marks==0,"logout after DB before UI");
   FakeState.reset();a=intent(9,dialog);receiver.onReceive(null,a);FakeState.flush(FakeState.db);FakeState.flush(FakeState.ui);
   check(FakeState.reads==1&&FakeState.puts==1&&(heard?FakeState.marks>0:FakeState.sends==1),"same owner async action works");
   FakeState.reset();a=intent(9,dialog);UserConfig.slots[9].id=0;receiver.onReceive(null,a);
   check(FakeState.db.isEmpty()&&FakeState.sends==0&&FakeState.marks==0,"logged out receiver rejects");
  }
  System.out.println("PASS: "+checks+" actual Java binding/receiver checks with explicit Android and storage fakes. Device PendingIntent delivery not tested.");
 }
}'''
}

def run(source, jdk=None):
    javac = str(Path(jdk)/'bin/javac.exe') if jdk else shutil.which('javac')
    java = str(Path(jdk)/'bin/java.exe') if jdk else shutil.which('java')
    if not javac or not java:
        raise SystemExit('JDK is required; do not report the Java execution as passed.')
    planned = patch.plan(source)
    files = dict(STUBS)
    for name in [patch.BINDING, patch.JAVA+'messenger/WearReplyReceiver.java', patch.JAVA+'messenger/AutoMessageHeardReceiver.java']:
        files[name.split('/java/',1)[1]] = planned[name].decode('utf-8')
    scratch = Path('work')
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as folder:
        root = Path(folder)
        sources = []
        for name, content in files.items():
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            sources.append(str(path))
        compiler = [java, '-Xmx256m', '-XX:ActiveProcessorCount=2', '-m', 'jdk.compiler/com.sun.tools.javac.Main'] if jdk else [javac, '-J-Xmx256m']
        subprocess.run([*compiler, '-encoding', 'UTF-8', '-d', str(root/'classes'), *sources], check=True, timeout=60)
        subprocess.run([java, '-Xmx128m', '-XX:ActiveProcessorCount=2', '-cp', str(root/'classes'), 'org.telegram.messenger.BindingTest'], check=True, timeout=30)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('--jdk')
    args = parser.parse_args()
    run(args.source,args.jdk)
