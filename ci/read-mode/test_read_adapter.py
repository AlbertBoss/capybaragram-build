import sys, shutil
import hashlib,json,subprocess,tempfile,zipfile
from pathlib import Path
ci=Path(__file__).resolve().parent
stage=Path(tempfile.mkdtemp(prefix='capy-read-adapter-')).resolve()
types=['TL_messages_readHistory','TL_channels_readHistory','TL_messages_readDiscussion','TL_messages_readEncryptedHistory','TL_messages_readMessageContents','TL_channels_readMessageContents','TL_messages_readSavedHistory','TL_messages_readMentions']
actual=(Path(sys.argv[1])/'TMessagesProj/src/main/java/org/telegram/tgnet/TLRPC.java').read_text(encoding='utf-8')
for name in types: assert 'class '+name+' ' in actual, name
host=(Path(sys.argv[1])/'TMessagesProj/src/main/java/org/telegram/messenger/UserConfig.java').read_text(encoding='utf-8')
assert 'public volatile long clientUserId;' in host
fixtures={
 'org/telegram/tgnet/TLObject.java':'package org.telegram.tgnet; public class TLObject {}',
 'org/telegram/tgnet/TLRPC.java':'package org.telegram.tgnet; public class TLRPC { '+''.join('public static class '+n+' extends TLObject {}' for n in types)+'}',
 'org/telegram/messenger/UserConfig.java':'''package org.telegram.messenger;
public class UserConfig {
 public static final int MAX_ACCOUNT_COUNT=10;
 private static final UserConfig[] all=new UserConfig[10];
 static {for(int i=0;i<10;i++){all[i]=new UserConfig();all[i].clientUserId=1001+i;}}
 public volatile long clientUserId;
 public final Object sync=new Object();
 private final Preferences prefs=new Preferences();
 public static UserConfig getInstance(int a){return all[a];}
 public long getClientUserId(){synchronized(sync){return clientUserId;}}
 public Preferences getPreferences(){return prefs;}
 public static class Preferences {
  private final java.util.Map<String,Boolean> values=new java.util.HashMap<>();
  public boolean getBoolean(String key,boolean fallback){return values.containsKey(key)?values.get(key):fallback;}
  public Preferences edit(){return this;}
  public Preferences putBoolean(String key,boolean value){values.put(key,value);return this;}
  public void apply(){}
 }
}''',
 'AdapterProbe.java':'''import org.capybaragram.readmode.CapyReadReceipts;
import org.telegram.tgnet.*;
import org.telegram.messenger.UserConfig;
public class AdapterProbe {
 static int checks;
 static void check(boolean b,String s){checks++;if(!b)throw new AssertionError(s);}
 public static void main(String[] args) throws Exception {
  synchronized(UserConfig.getInstance(0).sync) {
   Thread reader=new Thread(() -> CapyReadReceipts.isSilent(0));
   reader.start(); reader.join(2000);
   check(!reader.isAlive(),"bridge never acquires host owner lock under its own lock");
  }
  for(int i=0;i<10;i++){
   check(!CapyReadReceipts.isSilent(i),"ordinary default");
   check(CapyReadReceipts.setSilent(i,1001+i,true),"enable owner account");
   TLObject req=new TLRPC.TL_messages_readHistory();
   check(!CapyReadReceipts.consume(i,req,CapyReadReceipts.capture(i,req,false)),"automatic suppressed");
  }
  TLObject a=new TLRPC.TL_messages_readHistory(), b=new TLRPC.TL_messages_readHistory();
  CapyReadReceipts.CapturedRead permit=CapyReadReceipts.capture(0,a,true);
  check(!CapyReadReceipts.consume(1,a,permit),"other account");
  check(!CapyReadReceipts.consume(0,b,permit),"other request in same account");
  check(CapyReadReceipts.consume(0,a,permit),"exact request retained");
  check(!CapyReadReceipts.consume(0,a,permit),"replay");
  permit=CapyReadReceipts.capture(0,a,false);
  CapyReadReceipts.setSilent(0,1001,false);
  check(!CapyReadReceipts.consume(0,a,permit),"silent request not flushed");
  permit=CapyReadReceipts.capture(0,a,true);
  CapyReadReceipts.SessionIdentity identity=CapyReadReceipts.captureSession(0);
  check(CapyReadReceipts.isCurrent(identity),"live callback identity");
  CapyReadReceipts.beforeLogout(0);
  check(!CapyReadReceipts.isCurrent(identity),"callback retired before logout");
  check(CapyReadReceipts.captureSession(0)==null,"retired UI cannot open");
  check(!CapyReadReceipts.consume(0,a,permit),"logout");
  check(!CapyReadReceipts.setSilent(0,1001,false),"retired session cannot change mode");
  CapyReadReceipts.ownerChanged(0,0,1001);
  check(!CapyReadReceipts.isCurrent(identity),"same owner relogin invalidates old UI callback");
  check(!CapyReadReceipts.consume(0,a,permit),"same owner relogin cannot reuse old request");
  permit=CapyReadReceipts.capture(0,a,true);
  UserConfig.getInstance(0).clientUserId=2001;
  CapyReadReceipts.ownerChanged(0,1001,2001);
  check(!CapyReadReceipts.consume(0,a,permit),"new owner old permit");
  check(!CapyReadReceipts.setSilent(0,1001,true),"stale UI owner");
  check(!CapyReadReceipts.isSilent(0),"new owner does not inherit previous preferences");
  check(CapyReadReceipts.capture(0,new TLObject(),false)==null,"ordinary request unaffected");
  UserConfig.getInstance(0).clientUserId=0;
  CapyReadReceipts.ownerChanged(0,2001,0);
  check(CapyReadReceipts.isSilent(0),"logged out");
  check(CapyReadReceipts.captureSession(0)==null,"logged out has no UI identity");
  check(!CapyReadReceipts.isCurrent(null),"null identity rejected");
  check(!CapyReadReceipts.consume(0,a,CapyReadReceipts.capture(0,a,true)),"no owner cannot explicitly read");
  System.out.println("CAPY_READ_ADAPTER=PASS checks="+checks);
 }
}'''
}
sources=[]
for name,body in fixtures.items():
    p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body,encoding='utf-8');sources.append(p)
sources += [ci/'ReadReceiptPolicy.java',ci/'CapyReadReceipts.java']
jdk=Path(shutil.which('javac') or sys.exit('JDK javac missing')).resolve().parent
suffix='.exe' if sys.platform=='win32' else ''
result=subprocess.run([str(jdk/('javac'+suffix)),'--release','8','-Xlint:all','-Werror','-d',str(stage/'classes'),*[str(p) for p in sources]],capture_output=True,text=True,timeout=60)
if result.returncode: raise SystemExit(result.stderr)
result=subprocess.run([str(jdk/('java'+suffix)),'-cp',str(stage/'classes'),'AdapterProbe'],capture_output=True,text=True,timeout=25)
if result.returncode: raise SystemExit(result.stderr)
report={'output':result.stdout.strip(),'source_sha256':{n:hashlib.sha256((ci/n).read_bytes()).hexdigest() for n in ['ReadReceiptPolicy.java','CapyReadReceipts.java']},'tl_types_confirmed_in_pinned_source':types,'scope':'Real bridge and policy with fake UserConfig/preferences and TL object shells; fixture simulates host owner getter lock. Not Android runtime or Telegram integration. Production host/UI patch remains uncompiled.'}
print(json.dumps(report,indent=2))
print(result.stdout)
