# SPDX-License-Identifier: MIT
"""Reject failed folder mutations in the pinned native Android editor."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
NAME='TMessagesProj/src/main/java/org/telegram/ui/FilterCreateActivity.java'
SHA='62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c'
def digest(raw): return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
def once(text,old,new):
    if text.count(old)!=1: raise ValueError('Folder mutation anchor differs')
    return text.replace(old,new)
HELPER = """    private static boolean capyFilterRequestAccepted(org.telegram.tgnet.TLObject response, TLRPC.TL_error error, BaseFragment fragment) {
        if (error == null && response instanceof TLRPC.TL_boolTrue) {
            return true;
        }
        if (fragment.getParentActivity() != null) {
            if (error != null && !TextUtils.isEmpty(error.text)) {
                processErrors(error, fragment, BulletinFactory.of(fragment));
            } else {
                BulletinFactory.of(fragment).createErrorBulletin(LocaleController.getString(R.string.UnknownError)).show();
            }
        }
        return false;
    }

"""
def transform(text):
    text=once(text,'    public static void saveFilterToServer(',HELPER+'    public static void saveFilterToServer(')
    text=once(text,'                    getMessagesController().removeFilter(filter);',
        '                    if (!capyFilterRequestAccepted(response, error, FilterCreateActivity.this)) {\n                        return;\n                    }\n                    getMessagesController().removeFilter(filter);')
    old="""                processAddFilter(filter, newFilterFlags, newFilterName, newFilterNameEntities, newFilterNoanimate, newFilterColor, newAlwaysShow, newNeverShow, creatingNew, atBegin, hasUserChanged, resetUnreadCounter, fragment, onFinish);
            } else if (onFinish != null) {"""
    new="""            }
            if (!capyFilterRequestAccepted(response, error, fragment)) {
                if (!progress) {
                    // Existing chat-list actions update optimistically. Request
                    // authoritative server state after a rejected mutation.
                    messagesController.loadRemoteFilters(true);
                }
                return;
            }
            if (progress) {
                processAddFilter(filter, newFilterFlags, newFilterName, newFilterNameEntities, newFilterNoanimate, newFilterColor, newAlwaysShow, newNeverShow, creatingNew, atBegin, hasUserChanged, resetUnreadCounter, fragment, onFinish);
            } else if (onFinish != null) {"""
    return once(text,old,new)
def plan(source,check=False):
    source=Path(source).resolve(strict=True); path=source/NAME
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source): raise ValueError('Unsafe folder source path')
    manifest=json.loads((ROOT/'input-hashes.json').read_text())
    raw=path.read_bytes().replace(b'\r\n',b'\n')
    if digest(raw)!=manifest['post' if check else 'pre']: raise ValueError('Pinned folder source differs')
    result=raw if check else transform(raw.decode('utf-8')).encode('utf-8')
    if digest(result)!=manifest['post']: raise ValueError('Folder output differs')
    return path,result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    head=subprocess.run(['git','-C',str(a.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if head!=SHA: raise ValueError('Wrong Android revision')
    path,result=plan(a.source,a.check)
    if not a.check:path.write_bytes(result)
    print('PASS: native folder response guards', 'verified' if a.check else 'prepared')
