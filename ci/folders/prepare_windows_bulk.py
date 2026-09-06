# SPDX-License-Identifier: MIT
"""Drain failed bulk folder requests and suppress continuation after a rejection."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
NAME='Telegram/SourceFiles/settings/sections/settings_folders.cpp'
SHA='80158983dba09d3bf5d96701f21473d6c34bf5f5'
def digest(raw):return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Bulk folder anchor differs')
    return text.replace(old,new)
def transform(text):
    text=once(text,'#include "lang/lang_keys.h"','#include "lang/lang_keys.h"\n#include "ui/toast/toast.h"')
    text=once(text,'''\t\t\tconst auto checkFinished = [=] {
\t\t\t\tif (ids->empty() && next) {
\t\t\t\t\tAssert(updated.id() != 0);
\t\t\t\t\tnext(updated);
\t\t\t\t}
\t\t\t};''','''\t\t\tstruct CapySaveState { bool failed = false; bool finished = false; };
\t\t\tconst auto capySave = std::make_shared<CapySaveState>();
\t\t\tconst auto checkFinished = [=] {
\t\t\t\tif (!ids->empty() || capySave->finished) {
\t\t\t\t\treturn;
\t\t\t\t}
\t\t\t\tcapySave->finished = true;
\t\t\t\tfilters->reload();
\t\t\t\tif (capySave->failed) {
\t\t\t\t\tUi::Toast::Show(Lang::Id().startsWith(u"ru"_q)
\t\t\t\t\t\t? u"Не все изменения папок сохранены. Проверьте папки и повторите попытку."_q
\t\t\t\t\t\t: u"Some folder changes were not saved. Check your folders and try again."_q);
\t\t\t\t} else if (next) {
\t\t\t\t\tAssert(updated.id() != 0);
\t\t\t\t\tnext(updated);
\t\t\t\t}
\t\t\t};''')
    text=once(text,'''\t\t\t\t\t\t\tsession->api().applyUpdates(result);
\t\t\t\t\t\t}
\t\t\t\t\t\tids->remove(id);''','''\t\t\t\t\t\t\tsession->api().applyUpdates(result);
\t\t\t\t\t\t} else if constexpr (std::is_same_v<
\t\t\t\t\t\t\t\tstd::decay_t<decltype(result)>, MTPBool>) {
\t\t\t\t\t\t\tif (!mtpIsTrue(result)) {
\t\t\t\t\t\t\t\tcapySave->failed = true;
\t\t\t\t\t\t\t}
\t\t\t\t\t\t}
\t\t\t\t\t\tids->remove(id);''')
    return once(text,'\t\t\t\t\t}).afterRequest(previousId).send();','''\t\t\t\t\t}).fail([=](const MTP::Error &, mtpRequestId id) {
\t\t\t\t\t\tcapySave->failed = true;
\t\t\t\t\t\tids->remove(id);
\t\t\t\t\t\tcheckFinished();
\t\t\t\t\t}).afterRequest(previousId).send();''')
def plan(source,check=False):
    source=Path(source).resolve(strict=True);path=source/NAME
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):raise ValueError('Unsafe source path')
    hashes=json.loads((ROOT/'windows-bulk-hashes.json').read_text())
    raw=path.read_bytes().replace(b'\r\n',b'\n')
    if digest(raw)!=hashes['post' if check else 'pre']:raise ValueError('Pinned bulk folder source differs')
    result=raw if check else transform(raw.decode('utf-8')).encode('utf-8')
    if digest(result)!=hashes['post']:raise ValueError('Bulk folder output differs')
    return path,result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    head=subprocess.run(['git','-C',str(a.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if head!=SHA:raise ValueError('Wrong Windows revision')
    path,result=plan(a.source,a.check)
    if not a.check:path.write_bytes(result)
    print('PASS: native bulk folder response handling', 'verified' if a.check else 'prepared')
