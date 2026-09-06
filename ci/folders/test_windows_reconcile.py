# SPDX-License-Identifier: MIT
"""Compile actual patched load methods against a deterministic request transport."""
import argparse,subprocess,tempfile
from pathlib import Path
import prepare_windows_reconcile as patch
p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
output=patch.plan(a.source)
s=output[patch.FILES[1]].decode('utf-8')
methods=s[s.index('void ChatFilters::load() {'):s.index('bool ChatFilters::tagsEnabled() const {')]
assert 'chatsFilters().set(was)' not in output[patch.FILES[0]].decode('utf-8')
fixture=r"""
#include <cassert>
#include <functional>
#include <map>
#include <vector>
#include <iostream>
struct MTPmessages_GetDialogFilters {};
struct MTPmessages_DialogFilters {
 struct Data { bool is_tags_enabled() const { return false; } struct { std::vector<int> v; } filters; const auto &vfilters() const { return filters; } } value;
 const Data &data() const { return value; }
};
struct Api {
 struct Call { std::function<void(const MTPmessages_DialogFilters&)> done; std::function<void()> fail; };
 std::map<int,Call> calls; int issued=0;
 struct Builder {
  Api *api; int cancelId; Call call;
  Builder& done(std::function<void(const MTPmessages_DialogFilters&)> f) { call.done=f;return *this; }
  Builder& fail(std::function<void()> f) { call.fail=f;return *this; }
  int send() { const auto id=++api->issued;api->calls[id]=call;return id; }
  void cancel() { api->calls.erase(cancelId); }
 };
 Builder request(int id) { return {this,id,{}}; }
 Builder request(MTPmessages_GetDialogFilters) { return {this,0,{}}; }
 void finish(int id,bool ok) { auto call=calls.at(id);calls.erase(id);if(ok)call.done({});else call.fail(); }
};
struct Session { Api value; Api &api() { return value; } };
struct Owner { Session value;Session &session() { return value; } };
struct ChatFilters {
 Owner owner;Owner *_owner=&owner;int _loadRequestId=0;
 bool _reloading=false,_capyReloadPending=false,_tagsEnabled=false;
 struct { int count=0;void fire(std::initializer_list<int>) {++count;} } _listChanged;
 std::function<void()> onReceived;
 void received(const std::vector<int>&) { _reloading=false;auto f=onReceived;onReceived={};if(f)f(); }
 void load();void load(bool force);void reload();
 Api &api() {return owner.value.value;}
};
"""+methods+r"""
int main() {
 {ChatFilters f;f.reload();assert(f.api().issued==1);f.api().finish(1,true);assert(f._loadRequestId==0&&f.api().issued==1);}
 {ChatFilters f;f.reload();f.reload();assert(f.api().issued==1);f.api().finish(1,true);assert(f._loadRequestId==2);f.api().finish(2,true);assert(f.api().calls.empty());}
 {ChatFilters f;f.reload();for(int i=0;i<100;i++)f.reload();f.api().finish(1,true);assert(f.api().issued==2);f.api().finish(2,true);assert(f._loadRequestId==0);}
 {ChatFilters f;f.reload();f.reload();f.api().finish(1,false);assert(f._loadRequestId==2);f.api().finish(2,false);assert(f._loadRequestId==0&&f.api().issued==2);}
 {ChatFilters f;f.reload();f.reload();f.load(true);assert(f.api().issued==2&&!f.api().calls.count(1));f.api().finish(2,true);assert(f._loadRequestId==0&&f.api().issued==2);}
 {ChatFilters f;f.reload();f.onReceived=[&]{f.reload();};f.api().finish(1,true);assert(f._loadRequestId==2);f.reload();f.api().finish(2,true);assert(f._loadRequestId==3);f.api().finish(3,true);assert(f._loadRequestId==0);}
 std::cout<<"CAPY_NATIVE_FOLDER_RELOAD=PASS (6 actual-method response-order scenarios)\n";
}
"""
with tempfile.TemporaryDirectory(prefix='capy-reload-contract-') as directory:
 root=Path(directory);src=root/'reload.cpp';binary=root/'reload-probe';src.write_text(fixture,encoding='utf-8')
 subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(src),'-o',str(binary)],check=True)
 subprocess.run([str(binary)],check=True)
print('Actual C++ load methods passed controlled callback ordering; real Qt/MTProto integration remains required.')
