import sys, shutil
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

ci=Path(__file__).resolve().parent
stage=Path(tempfile.mkdtemp(prefix='capy-read-request-')).resolve()
dialog=(Path(sys.argv[1])/'TMessagesProj/src/main/java/org/telegram/messenger/DialogObject.java').read_text(encoding='utf-8')
methods=[]
for name in ['isEncryptedDialog','getEncryptedChatId','makeEncryptedDialogId']:
    match=re.search(r'    public static (?:boolean|int|long) '+name+r'\([^)]*\) \{.*?\n    \}',dialog,re.S)
    if not match: raise ValueError('Missing actual DialogObject method: '+name)
    methods.append(match.group(0))
fixtures={
 'org/telegram/messenger/DialogObject.java':'package org.telegram.messenger; public class DialogObject {\n'+'\n'.join(methods)+'\n}',
 'org/telegram/tgnet/TLObject.java':'package org.telegram.tgnet; public class TLObject {}',
 'org/telegram/tgnet/TLRPC.java':'''package org.telegram.tgnet;
public class TLRPC {
 public static class InputPeer extends TLObject {}
 public static class TL_inputPeerEmpty extends InputPeer {}
 public static class TL_inputPeerUser extends InputPeer {}
 public static class TL_inputPeerChannel extends InputPeer {}
 public static class InputChannel extends TLObject {}
 public static class EncryptedChat extends TLObject {public int id;public long access_hash;public byte[] auth_key;}
 public static class TL_encryptedChat extends EncryptedChat {}
 public static class TL_inputEncryptedChat extends TLObject {public int chat_id;public long access_hash;}
 public static class TL_messages_readHistory extends TLObject {public InputPeer peer;public int max_id;}
 public static class TL_channels_readHistory extends TLObject {public InputChannel channel;public int max_id;}
 public static class TL_messages_readDiscussion extends TLObject {public InputPeer peer;public int msg_id,read_max_id;}
 public static class TL_messages_readSavedHistory extends TLObject {public InputPeer parent_peer,peer;public int max_id;}
 public static class TL_messages_readEncryptedHistory extends TLObject {public TL_inputEncryptedChat peer;public int max_date;}
 public static class TL_messages_affectedMessages extends TLObject {}
 public static class TL_boolTrue extends TLObject {}
 public static class TL_boolFalse extends TLObject {}
 public static class TL_error extends TLObject {}
}''',
 'org/telegram/messenger/MessagesController.java':'''package org.telegram.messenger;
import org.telegram.tgnet.TLRPC;
public class MessagesController {
 public final java.util.Map<Long,TLRPC.InputPeer> peers=new java.util.HashMap<>();
 public TLRPC.InputPeer getInputPeer(long id){return peers.get(id);}
 public static TLRPC.InputChannel getInputChannel(TLRPC.InputPeer p){return new TLRPC.InputChannel();}
}''',
 'RequestProbe.java':'''import org.telegram.tgnet.*;
import org.telegram.messenger.*;
import org.capybaragram.readmode.CapyReadRequest;
public class RequestProbe {
 static int checks;
 static void check(boolean b,String s){checks++;if(!b)throw new AssertionError(s);}
 public static void main(String[] args){
  MessagesController c=new MessagesController();
  c.peers.put(1L,new TLRPC.TL_inputPeerUser());
  c.peers.put(-2L,new TLRPC.TL_inputPeerChannel());
  c.peers.put(3L,new TLRPC.TL_inputPeerEmpty());
  TLObject user=CapyReadRequest.create(c,1,0,false,null,100,200);
  check(user instanceof TLRPC.TL_messages_readHistory,"user request");
  check(((TLRPC.TL_messages_readHistory)user).max_id==100,"read exact snapshot");
  check(((TLRPC.TL_messages_readHistory)user).peer==c.peers.get(1L),"original peer");
  TLObject channel=CapyReadRequest.create(c,-2,0,false,null,110,200);
  check(channel instanceof TLRPC.TL_channels_readHistory,"channel request");
  check(((TLRPC.TL_channels_readHistory)channel).max_id==110,"channel latest");
  TLObject topic=CapyReadRequest.create(c,-2,44,false,null,120,200);
  check(topic instanceof TLRPC.TL_messages_readDiscussion,"discussion thread");
  check(((TLRPC.TL_messages_readDiscussion)topic).msg_id==44 && ((TLRPC.TL_messages_readDiscussion)topic).read_max_id==120,"thread snapshot");
  TLObject saved=CapyReadRequest.create(c,-2,1,true,null,130,200);
  check(saved instanceof TLRPC.TL_messages_readSavedHistory,"mono forum");
  check(((TLRPC.TL_messages_readSavedHistory)saved).peer==c.peers.get(1L) && ((TLRPC.TL_messages_readSavedHistory)saved).parent_peer==c.peers.get(-2L),"mono forum both peers");
  check(CapyReadRequest.create(c,1,-1,false,null,100,200)==null,"negative thread");
  check(CapyReadRequest.create(c,1,1L+Integer.MAX_VALUE,false,null,100,200)==null,"overflow thread");
  check(CapyReadRequest.create(c,-2,3,true,null,100,200)==null,"missing mono forum peer");
  for(long id:new long[]{0,Long.MIN_VALUE,3,4}) check(CapyReadRequest.create(c,id,0,false,null,100,200)==null,"invalid peer");
  for(int id:new int[]{Integer.MIN_VALUE,-1,0,Integer.MAX_VALUE}) check(CapyReadRequest.create(c,1,0,false,null,id,200)==null,"unloaded message sentinel");
  TLRPC.TL_encryptedChat secret=new TLRPC.TL_encryptedChat();secret.id=7;secret.access_hash=123;secret.auth_key=new byte[256];
  long encryptedId=DialogObject.makeEncryptedDialogId(7);
  TLObject encrypted=CapyReadRequest.create(c,encryptedId,0,false,secret,-10,250);
  check(encrypted instanceof TLRPC.TL_messages_readEncryptedHistory,"secret chat request");
  TLRPC.TL_messages_readEncryptedHistory e=(TLRPC.TL_messages_readEncryptedHistory)encrypted;
  check(e.peer.chat_id==7 && e.peer.access_hash==123 && e.max_date==250,"secret snapshot");
  check(CapyReadRequest.create(c,encryptedId,0,false,null,10,250)==null,"secret cannot fall back to ordinary");
  check(CapyReadRequest.create(c,1,0,false,secret,10,250)==null,"secret object for ordinary chat rejected");
  check(CapyReadRequest.create(c,DialogObject.makeEncryptedDialogId(8),0,false,secret,10,250)==null,"wrong secret chat rejected");
  for(int date:new int[]{0,-1,Integer.MAX_VALUE}) check(CapyReadRequest.create(c,encryptedId,0,false,secret,10,date)==null,"unloaded secret date");
  secret.auth_key=null;
  check(CapyReadRequest.create(c,encryptedId,0,false,secret,10,250)==null,"unestablished secret");
  check(CapyReadRequest.accepted(user,new TLRPC.TL_messages_affectedMessages(),null),"user correct ACK");
  check(!CapyReadRequest.accepted(user,new TLRPC.TL_boolTrue(),null),"no fake user Bool ACK");
  for(TLObject req:new TLObject[]{channel,topic,saved,encrypted}) {
   check(CapyReadRequest.accepted(req,new TLRPC.TL_boolTrue(),null),"correct Bool ACK");
   check(!CapyReadRequest.accepted(req,new TLRPC.TL_boolFalse(),null),"false is not success");
   check(!CapyReadRequest.accepted(req,new TLRPC.TL_messages_affectedMessages(),null),"wrong ACK type rejected");
   check(!CapyReadRequest.accepted(req,null,null),"empty ACK rejected");
   check(!CapyReadRequest.accepted(req,new TLRPC.TL_boolTrue(),new TLRPC.TL_error()),"error overrides response");
  }
  check(!CapyReadRequest.accepted(new TLObject(),new TLRPC.TL_boolTrue(),null),"unrelated operation");
  System.out.println("CAPY_READ_REQUEST=PASS checks="+checks);
 }
}'''
}
sources=[]
for name,body in fixtures.items():
    path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body,encoding='utf-8');sources.append(path)
sources.append(ci/'CapyReadRequest.java')
jdk=Path(shutil.which('javac') or sys.exit('JDK javac missing')).resolve().parent
suffix='.exe' if sys.platform=='win32' else ''
result=subprocess.run([str(jdk/('javac'+suffix)),'--release','8','-Xlint:all','-Werror','-d',str(stage/'classes'),*[str(p) for p in sources]],capture_output=True,text=True,timeout=60)
if result.returncode: raise SystemExit(result.stderr)
result=subprocess.run([str(jdk/('java'+suffix)),'-cp',str(stage/'classes'),'RequestProbe'],capture_output=True,text=True,timeout=25)
if result.returncode: raise SystemExit(result.stderr)
report={'output':result.stdout.strip(),'source_sha256':hashlib.sha256((ci/'CapyReadRequest.java').read_bytes()).hexdigest(),'scope':'Real request factory + exact three DialogObject methods from pinned Android source, TL field/controller fixtures. No native UI, real network or full APK compilation.'}
print(json.dumps(report,indent=2))
print(result.stdout)
