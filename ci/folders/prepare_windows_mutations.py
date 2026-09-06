# SPDX-License-Identifier: MIT
"""Reconcile failed native folder edits and pinned-chat updates with server state."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PREFIX='Telegram/SourceFiles/'
FILES=[PREFIX+'boxes/filters/edit_filter_box.cpp',PREFIX+'api/api_chat_filters.cpp']
SHA='80158983dba09d3bf5d96701f21473d6c34bf5f5'
def digest(raw):return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Folder mutation anchor differs')
    return text.replace(old,new)
def transform(name,text):
    if name==FILES[0]:
        text=once(text,'#include "ui/rect.h"','#include "ui/rect.h"\n#include "ui/toast/toast.h"')
        marker='\t\tconst auto tl = result.tl();'
        indent='\t\t'
        ending='\t\t\ttl\n\t\t)).send();'
        replacement='\t\t\ttl\n'
    elif name==FILES[1]:
        marker='\tconst auto &order = session->data().pinnedChatsOrder(filterId);'
        indent='\t'
        ending='\t\tfilter.tl()\n\t)).send();'
        replacement='\t\tfilter.tl()\n'
    else:raise ValueError('Unexpected folder source')
    fail='''const auto capyFailed = [=] {
    session->data().chatsFilters().reload();
    Ui::Toast::Show(Lang::Id().startsWith(u"ru"_q)
        ? u"Не удалось сохранить изменения папки. Попробуйте ещё раз."_q
        : u"Could not save folder changes. Please try again."_q);
};'''
    def native(block):return '\n'.join(indent+line.replace('    ','\t') for line in block.splitlines())
    text=once(text,marker,native(fail)+'\n'+marker)
    callback=''' )).done([=](const MTPBool &result) {
    if (mtpIsTrue(result)) {
        session->data().chatsFilters().reload();
    } else {
        capyFailed();
    }
}).fail(capyFailed).send();'''.lstrip()
    return once(text,ending,replacement+native(callback))
def plan(source,check=False):
    source=Path(source).resolve(strict=True)
    hashes=json.loads((ROOT/'windows-mutation-hashes.json').read_text())
    if set(hashes['pre'])!=set(FILES) or set(hashes['post'])!=set(FILES):raise ValueError('Wrong allowlist')
    result={}
    for name in FILES:
        path=source/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):raise ValueError('Unsafe source path')
        raw=path.read_bytes().replace(b'\r\n',b'\n')
        if digest(raw)!=hashes['post' if check else 'pre'][name]:raise ValueError('Pinned source differs: '+name)
        output=raw if check else transform(name,raw.decode('utf-8')).encode('utf-8')
        if digest(output)!=hashes['post'][name]:raise ValueError('Output differs')
        result[name]=output
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    head=subprocess.run(['git','-C',str(a.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if head!=SHA:raise ValueError('Wrong Windows revision')
    result=plan(a.source,a.check)
    if not a.check:
        for name,raw in result.items():(a.source/name).write_bytes(raw)
    print('PASS: native folder edit and pinned-chat response handling', 'verified' if a.check else 'prepared')
