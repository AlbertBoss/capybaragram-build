# SPDX-License-Identifier: MIT
"""Keep each native remote-folder request's completion callback local to that request."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
NAME='TMessagesProj/src/main/java/org/telegram/messenger/MessagesController.java'
SHA='62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c'
def digest(raw):return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
def transform(text):
    start=text.index('    private Utilities.Callback<Boolean> onLoadedRemoteFilters;')
    end=text.index('    private boolean loggedDeviceStats;',start)
    section=text[start:end]
    section=section.replace('    private Utilities.Callback<Boolean> onLoadedRemoteFilters;\n\n','',1)
    old='''        if (whenDone != null) {
            onLoadedRemoteFilters = whenDone;
        }
'''
    if section.count(old)!=1:raise ValueError('Callback assignment anchor differs')
    section=section.replace(old,'',1)
    if section.count('                        onLoadedRemoteFilters = null;')!=3:raise ValueError('Callback completion anchors differ')
    section=section.replace('                        onLoadedRemoteFilters = null;\n','')
    section=section.replace('onLoadedRemoteFilters','whenDone')
    if 'onLoadedRemoteFilters' in text[:start]+text[end:]:raise ValueError('Unexpected shared callback reference outside reviewed methods')
    return text[:start]+section+text[end:]
def plan(source,check=False):
    source=Path(source).resolve(strict=True);path=source/NAME
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):raise ValueError('Unsafe Android source path')
    hashes=json.loads((ROOT/'android-callback-hashes.json').read_text())
    raw=path.read_bytes().replace(b'\r\n',b'\n')
    if digest(raw)!=hashes['post' if check else 'pre']:raise ValueError('Pinned Android callback source differs')
    result=raw if check else transform(raw.decode('utf-8')).encode('utf-8')
    if digest(result)!=hashes['post']:raise ValueError('Callback output differs')
    return path,result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    head=subprocess.run(['git','-C',str(a.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if head!=SHA:raise ValueError('Wrong Android revision')
    path,result=plan(a.source,a.check)
    if not a.check:path.write_bytes(result)
    print('PASS: native Android folder callbacks', 'verified' if a.check else 'prepared')
