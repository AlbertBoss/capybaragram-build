# SPDX-License-Identifier: MIT
import argparse,importlib.util,json,subprocess,tempfile
from pathlib import Path
import prepare_android_folders as patch
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--javac',default='javac');args=p.parse_args()
path,result=patch.plan(args.source)
text=result.decode('utf-8')
# Compile the actual method extracted from transformed native source.
start=text.index('    private static boolean capyFilterRequestAccepted(')
end=text.index('    public static void saveFilterToServer(',start)
method=text[start:end]
assert text.count('if (!capyFilterRequestAccepted(')==2
harness="""import org.telegram.tgnet.TLObject;
public class FolderResponseProbe {
 static int notices;
 static class TLRPC {
  static class TL_boolTrue extends TLObject {}
  static class TL_boolFalse extends TLObject {}
  static class TL_error { String text; TL_error(String text) { this.text=text; } }
 }
 static class BaseFragment { boolean attached=true; Object getParentActivity() { return attached?this:null; } }
 static class TextUtils { static boolean isEmpty(String x) { return x==null || x.isEmpty(); } }
 static class R { static class string { static int UnknownError=1; } }
 static class LocaleController { static String getString(int id) { return "unknown"; } }
 static class BulletinFactory {
  static BulletinFactory of(BaseFragment f) { return new BulletinFactory(); }
  BulletinFactory createErrorBulletin(String x) { return this; }
  void show() { notices++; }
 }
 static boolean processErrors(TLRPC.TL_error e, BaseFragment f, BulletinFactory b) { notices++; return true; }
"""+method+"""
 static void expect(TLObject response, TLRPC.TL_error error, boolean attached, boolean accepted, int expectedNotices) {
  notices=0; BaseFragment fragment=new BaseFragment(); fragment.attached=attached;
  if (capyFilterRequestAccepted(response,error,fragment)!=accepted || notices!=expectedNotices) throw new AssertionError();
 }
 public static void main(String[] args) {
  expect(new TLRPC.TL_boolTrue(),null,true,true,0);
  expect(new TLRPC.TL_boolFalse(),null,true,false,1);
  expect(null,null,true,false,1);
  expect(new TLRPC.TL_boolTrue(),new TLRPC.TL_error("DIALOG_FILTERS_TOO_MUCH"),true,false,1);
  expect(null,new TLRPC.TL_error(""),true,false,1);
  expect(null,new TLRPC.TL_error("NETWORK_ERROR"),false,false,0);
  expect(new TLRPC.TL_boolTrue(),null,false,true,0);
  System.out.println("CAPY_FOLDER_RESPONSE=PASS (7 native helper cases)");
 }
}
"""
with tempfile.TemporaryDirectory(prefix='capy-folder-test-') as tmp:
 root=Path(tmp);package=root/'org/telegram/tgnet';package.mkdir(parents=True)
 (package/'TLObject.java').write_text('package org.telegram.tgnet; public class TLObject {}',encoding='utf-8')
 (root/'FolderResponseProbe.java').write_text(harness,encoding='utf-8')
 subprocess.run([args.javac,'-encoding','UTF-8','-d',str(root),str(package/'TLObject.java'),str(root/'FolderResponseProbe.java')],check=True)
 java=str(Path(args.javac).with_name('java.exe')) if args.javac.endswith('.exe') else 'java'
 subprocess.run([java,'-cp',str(root),'FolderResponseProbe'],check=True)
print('Pinned native response helper compiled and exercised; full client compilation and network integration still required.')
