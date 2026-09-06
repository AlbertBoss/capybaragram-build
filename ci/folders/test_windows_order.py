# SPDX-License-Identifier: MIT
"""Run the patched native saveOrder method with delayed and rejected responses."""
import argparse,subprocess,tempfile
from pathlib import Path
import prepare_windows_reconcile as patch
p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
text=patch.plan(a.source)[patch.FILES[1]].decode('utf-8')
method=text[text.index('void ChatFilters::saveOrder('):text.index('bool ChatFilters::archiveNeeded() const {')]
program=r'''
#include <cassert>
#include <functional>
#include <iostream>
#include <map>
#include <string>
#include <vector>
using FilterId=int;
using mtpRequestId=int;
using MTPint=int;
template<typename T> using QVector=std::vector<T>;
int MTP_int(int value) { return value; }
template<typename T> std::vector<T> MTP_vector(const std::vector<T> &value) { return value; }
struct MTPBool { bool value; };
bool mtpIsTrue(MTPBool result) { return result.value; }
namespace MTP { struct Error {}; }
struct MTPmessages_UpdateDialogFiltersOrder { std::vector<int> value; explicit MTPmessages_UpdateDialogFiltersOrder(std::vector<int> v):value(v){} };
struct MTP_updateDialogFilterOrder { std::vector<int> value; explicit MTP_updateDialogFilterOrder(std::vector<int> v):value(v){} };
std::u16string operator""_q(const char16_t *value,size_t size) { return {value,size}; }
struct Language { bool startsWith(const std::u16string&) const { return true; } };
namespace Lang { Language Id() { return {}; } }
namespace Ui::Toast { int count=0; void Show(const std::u16string&) { ++count; } }
struct Api {
    struct Call { std::function<void(const MTPBool&,int)> done; std::function<void(const MTP::Error&,int)> fail; int after=0; };
    std::map<int,Call> calls; int issued=0;
    struct Builder {
        Api *api; int cancelId; Call call;
        Builder& done(std::function<void(const MTPBool&,int)> f) { call.done=f;return *this; }
        Builder& fail(std::function<void(const MTP::Error&,int)> f) { call.fail=f;return *this; }
        Builder& afterRequest(int id) { call.after=id;return *this; }
        int send() { int id=++api->issued;api->calls[id]=call;return id; }
        void cancel() { api->calls.erase(cancelId); }
    };
    Builder request(int id) { return {this,id,{}}; }
    Builder request(MTPmessages_UpdateDialogFiltersOrder) { return {this,0,{}}; }
    void finish(int id,int outcome) { auto call=calls.at(id);calls.erase(id);if(outcome==2)call.fail({},id);else call.done({outcome==0},id); }
};
struct Session { Api value; Api& api() { return value; } };
struct Owner { Session value; Session& session() { return value; } };
struct ChatFilters {
    Owner owner; Owner *_owner=&owner;
    int _saveOrderRequestId=0,_saveOrderAfterId=0,reloads=0;
    std::vector<int> displayed;
    void apply(MTP_updateDialogFilterOrder value) { displayed=value.value; }
    void reload() { ++reloads; }
    Api& api() { return owner.value.value; }
    void saveOrder(const std::vector<FilterId>&,mtpRequestId after=0);
};
'''+method+r'''
int main() {
    { ChatFilters f; f.saveOrder({2,1});assert((f.displayed==std::vector<int>{2,1}));f.api().finish(1,0);assert(!f._saveOrderRequestId&&!f._saveOrderAfterId&&f.reloads==1&&Ui::Toast::count==0); }
    for(int outcome:{1,2}) { Ui::Toast::count=0;ChatFilters f;f.saveOrder({1,2});f.api().finish(1,outcome);assert(!f._saveOrderRequestId&&f.reloads==1&&Ui::Toast::count==1); }
    { Ui::Toast::count=0;ChatFilters f;f.saveOrder({1,2});auto stale=f.api().calls.at(1);f.saveOrder({2,1});assert(!f.api().calls.count(1));stale.fail({},1);stale.done({true},1);assert(f._saveOrderRequestId==2&&f.reloads==0&&Ui::Toast::count==0);f.api().finish(2,0);assert(f.reloads==1&&!f._saveOrderRequestId); }
    { ChatFilters f;f.saveOrder({1,2},77);f.saveOrder({2,1});assert(f.api().calls.at(2).after==77);f.api().finish(2,0);assert(!f._saveOrderAfterId);f.saveOrder({1,2});assert(f.api().calls.at(3).after==0);f.api().finish(3,0); }
    { ChatFilters f;f.saveOrder({1,2},77);f.saveOrder({2,1},88);assert(f.api().calls.at(2).after==88);f.api().finish(2,0);assert(!f._saveOrderAfterId&&f.reloads==1); }
    std::cout << "CAPY_NATIVE_FOLDER_ORDER=PASS (success, false Bool, RPC error, stale replies, carried dependency cleanup, replaced dependency)\n";
}
'''
with tempfile.TemporaryDirectory(prefix='capy-order-') as tmp:
    folder=Path(tmp);source=folder/'order.cpp';exe=folder/'order'
    source.write_text(program,encoding='utf-8')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
