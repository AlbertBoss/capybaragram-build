# SPDX-License-Identifier: MIT
"""Keep native Windows folders until server deletion has succeeded."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
NAME='Telegram/SourceFiles/api/api_chat_filters_remove_manager.cpp'
SHA='80158983dba09d3bf5d96701f21473d6c34bf5f5'
def digest(raw):return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Windows folder anchor differs')
    return text.replace(old,new)
def transform(text):
    text=once(text,'#include "ui/ui_utility.h"','#include "ui/ui_utility.h"\n#include "ui/toast/toast.h"')
    old="""	session->data().chatsFilters().apply(MTP_updateDialogFilter(
		MTP_flags(MTPDupdateDialogFilter::Flag(0)),
		MTP_int(filterId),
		MTPDialogFilter()));"""
    new="""	const auto removed = [=] {
		session->data().chatsFilters().apply(MTP_updateDialogFilter(
			MTP_flags(MTPDupdateDialogFilter::Flag(0)),
			MTP_int(filterId),
			MTPDialogFilter()));
	};
	const auto failed = [] {
		Ui::Toast::Show(Lang::Id().startsWith(u"ru"_q)
			? u"Не удалось удалить папку. Попробуйте ещё раз."_q
			: u"Could not remove the folder. Please try again."_q);
	};"""
    text=once(text,old,new)
    text=once(text,"""			MTPDialogFilter()
		)).send();""","""			MTPDialogFilter()
		)).done([=](const MTPBool &result) {
			if (mtpIsTrue(result)) {
				removed();
			} else {
				failed();
			}
		}).fail(failed).send();""")
    text=once(text,"""		)).done([=](const MTPUpdates &result) {
			api->applyUpdates(result);
		}).send();""","""		)).done([=](const MTPUpdates &result) {
			api->applyUpdates(result);
			removed();
		}).fail(failed).send();""")
    return text
def plan(source,check=False):
    source=Path(source).resolve(strict=True);path=source/NAME
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):raise ValueError('Unsafe folder source path')
    hashes=json.loads((ROOT/'windows-input-hashes.json').read_text())
    raw=path.read_bytes().replace(b'\r\n',b'\n')
    if digest(raw)!=hashes['post' if check else 'pre']:raise ValueError('Pinned Windows folder source differs')
    result=raw if check else transform(raw.decode('utf-8')).encode('utf-8')
    if digest(result)!=hashes['post']:raise ValueError('Windows folder output differs')
    return path,result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    head=subprocess.run(['git','-C',str(a.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if head!=SHA:raise ValueError('Wrong Windows revision')
    path,result=plan(a.source,a.check)
    if not a.check:path.write_bytes(result)
    print('PASS: native Windows folder removal', 'verified' if a.check else 'prepared')
