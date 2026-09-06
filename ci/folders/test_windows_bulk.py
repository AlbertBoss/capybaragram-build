# SPDX-License-Identifier: MIT
"""Compile real patched bulk callbacks and inject reordered accepted/rejected replies."""
import argparse,importlib.util,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('patch',root/'prepare_windows_bulk.py')
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
text=patch.plan(a.source)[1].decode('utf-8')
state='struct CapySaveState'+text.split('struct CapySaveState',1)[1].split('\n\t\t\tfor (const auto &update : updates)',1)[0]
done=text.split(').done([=](const auto &result, mtpRequestId id) {',1)[1].split('}).fail([=](const MTP::Error &, mtpRequestId id) {',1)[0]
fail=text.split('}).fail([=](const MTP::Error &, mtpRequestId id) {',1)[1].split('}).afterRequest(previousId).send();',1)[0]
program=r'''
#include <cassert>
#include <functional>
#include <iostream>
#include <memory>
#include <set>
#include <string>
#include <type_traits>
#define Assert(x) assert(x)
using mtpRequestId=int;
struct MTPBool { bool value; };
struct MTPUpdates {};
namespace MTP { struct Error {}; }
bool mtpIsTrue(MTPBool result) { return result.value; }
std::u16string operator""_q(const char16_t *value, size_t size) { return {value,size}; }
struct Language { bool startsWith(const std::u16string&) const { return true; } };
namespace Lang { Language Id() { return {}; } }
namespace Ui::Toast { int count=0; void Show(const std::u16string&) { ++count; } }
struct Ids:std::set<int> { void remove(int id) { erase(id); } };
struct Filters { int reloads=0; void reload() { ++reloads; } };
struct Api { int applied=0; void applyUpdates(MTPUpdates) { ++applied; } };
struct Session { Api instance; Api& api() { return instance; } };
struct Filter { int id() const { return 77; } };
using Next=std::function<void(Filter)>;
struct Callbacks {
    std::function<void(MTPBool,int)> boolean;
    std::function<void(MTPUpdates,int)> updates;
    std::function<void(MTP::Error,int)> failed;
    std::function<void()> finish;
};
Callbacks make(Session *session, Filters *filters, std::shared_ptr<Ids> ids, Next next) {
    const Filter updated;
    __STATE__
    const auto done=[=](const auto &result, mtpRequestId id) { __DONE__ };
    const auto failed=[=](const MTP::Error &, mtpRequestId id) { __FAIL__ };
    return {done,done,failed,checkFinished};
}
int main() {
    Session session; Filters filters; int continued=0;
    auto ids=std::make_shared<Ids>(); ids->insert(1); ids->insert(2);
    auto next=[&](Filter saved) { assert(saved.id()==77); ++continued; };
    auto callbacks=make(&session,&filters,ids,next);
    callbacks.boolean({true},2);
    assert(continued==0 && filters.reloads==0 && ids->size()==1);
    callbacks.updates({},1);
    assert(continued==1 && filters.reloads==1 && session.instance.applied==1 && ids->empty());
    callbacks.finish(); assert(continued==1 && filters.reloads==1);
    ids=std::make_shared<Ids>(); ids->insert(1); ids->insert(2);
    callbacks=make(&session,&filters,ids,next);
    callbacks.failed({},1); assert(continued==1 && ids->size()==1);
    callbacks.boolean({true},2); callbacks.finish();
    assert(continued==1 && filters.reloads==2 && Ui::Toast::count==1 && ids->empty());
    ids=std::make_shared<Ids>(); ids->insert(1); ids->insert(2);
    callbacks=make(&session,&filters,ids,next);
    callbacks.boolean({false},2); callbacks.failed({},1);
    assert(continued==1 && filters.reloads==3 && Ui::Toast::count==2 && ids->empty());
    callbacks=make(&session,&filters,std::make_shared<Ids>(),next);
    callbacks.finish(); callbacks.finish();
    assert(continued==2 && filters.reloads==4 && Ui::Toast::count==2);
    ids=std::make_shared<Ids>(); ids->insert(1);
    callbacks=make(&session,&filters,ids,{}); callbacks.boolean({true},1);
    assert(continued==2 && filters.reloads==5 && Ui::Toast::count==2 && ids->empty());
    std::cout << "CAPY_NATIVE_BULK_SAVE=PASS (reordered success, RPC rejection drains, mixed false/error, empty batch, no continuation)\n";
}
'''.replace('__STATE__',state).replace('__DONE__',done).replace('__FAIL__',fail)
with tempfile.TemporaryDirectory(prefix='capy-bulk-') as tmp:
    folder=Path(tmp);source=folder/'bulk.cpp';exe=folder/'bulk'
    source.write_text(program,encoding='utf-8')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
