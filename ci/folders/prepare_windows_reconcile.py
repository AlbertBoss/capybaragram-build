# SPDX-License-Identifier: MIT
"""Refresh authoritative folder state without restoring stale optimistic snapshots."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PREFIX='Telegram/SourceFiles/'
FILES=[PREFIX+'boxes/choose_filter_box.cpp',PREFIX+'data/data_chat_filters.cpp',PREFIX+'data/data_chat_filters.h']
SHA='80158983dba09d3bf5d96701f21473d6c34bf5f5'
def digest(raw):return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Folder reconcile anchor differs')
    return text.replace(old,new)
def transform(name,text):
    if name==FILES[0]:
        text=once(text,'			// Revert filter on fail.\n			history->owner().chatsFilters().set(was);',
          '			// A late failure must not restore a snapshot over a newer edit.\n			history->owner().chatsFilters().reload();')
        return once(text,'		)).done([=, chat = history->peer->name(), name = filter.title()] {',
          '		)).done([=, chat = history->peer->name(), name = filter.title()] {\n			history->owner().chatsFilters().reload();')
    if name==FILES[2]:
        return once(text,'	bool _reloading = false;','	bool _reloading = false;\n	bool _capyReloadPending = false;')
    if name==FILES[1]:
        text=once(text,'void ChatFilters::reload() {\n	_reloading = true;',
          'void ChatFilters::reload() {\n	if (_loadRequestId) {\n		_capyReloadPending = true;\n	}\n	_reloading = true;')
        text=once(text,'	api.request(_loadRequestId).cancel();\n	_loadRequestId = api.request(MTPmessages_GetDialogFilters(',
          '	api.request(_loadRequestId).cancel();\n	_capyReloadPending = false;\n	_loadRequestId = api.request(MTPmessages_GetDialogFilters(')
        text=once(text,"""		_tagsEnabled = result.data().is_tags_enabled();
		received(result.data().vfilters().v);
		_loadRequestId = 0;""","""		// Clear before received(), which may synchronously request a new load.
		_loadRequestId = 0;
		_tagsEnabled = result.data().is_tags_enabled();
		received(result.data().vfilters().v);
		if (_capyReloadPending) {
			_capyReloadPending = false;
			reload();
		}""")
        return once(text,"""		if (_reloading) {
			_reloading = false;
			_listChanged.fire({});
		}
	}).send();""","""		if (_reloading) {
			_reloading = false;
			_listChanged.fire({});
		}
		if (_capyReloadPending) {
			_capyReloadPending = false;
			reload();
		}
	}).send();""")
    raise ValueError('Unexpected source')
def plan(source,check=False):
    source=Path(source).resolve(strict=True);hashes=json.loads((ROOT/'windows-reconcile-hashes.json').read_text());result={}
    if set(hashes['pre'])!=set(FILES) or set(hashes['post'])!=set(FILES):raise ValueError('Wrong allowlist')
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
    print('PASS: three native folder reconciliation files', 'verified' if a.check else 'prepared')
