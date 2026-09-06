# SPDX-License-Identifier: MIT
"""Execute the actual patched response closures against a controlled transport fixture."""
import argparse,importlib.util,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('patch',root/'prepare_windows_mutations.py')
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
text=patch.plan(a.source)[patch.FILES[0]].decode('utf-8').split('const auto saveFilter =',1)[1]
failed=text.split('const auto capyFailed = ',1)[1].split('\n\t\t};',1)[0]+'\n};'
done=text.split(')).done(',1)[1].split(').fail(capyFailed).send();',1)[0]
program=r'''
#include <cassert>
#include <functional>
#include <string>
#include <utility>
#include <iostream>
struct MTPBool { bool value; };
bool mtpIsTrue(MTPBool value) { return value.value; }
std::u16string operator""_q(const char16_t *value, size_t size) { return {value,size}; }
struct Language { bool startsWith(const std::u16string&) const { return true; } };
namespace Lang { Language Id() { return {}; } }
namespace Ui::Toast { int count=0; void Show(const std::u16string&) { ++count; } }
struct Filters { int reloads=0; void reload() { ++reloads; } };
struct DataOwner { Filters filters; Filters& chatsFilters() { return filters; } };
struct Session { DataOwner owner; DataOwner& data() { return owner; } };
struct Filter { int id; };
using Next=std::function<void(Filter)>;
using Done=std::function<void(MTPBool)>;
using Fail=std::function<void()>;
std::pair<Done,Fail> make(Session *session, Next next) {
    Filter result{77};
    const auto capyFailed = __FAILED__
    Done done = __DONE__;
    result.id=99;
    return {done,capyFailed};
}
int main() {
    Session session;
    int continued=0, savedId=0;
    auto callbacks=make(&session,[&](Filter saved) { ++continued; savedId=saved.id; });
    assert(continued==0 && session.owner.filters.reloads==0); // no early share
    callbacks.first({true});
    assert(continued==1 && savedId==77 && session.owner.filters.reloads==1);
    assert(Ui::Toast::count==0); // completed save, captured result outlives editor
    callbacks=make(&session,[&](Filter) { ++continued; });
    callbacks.first({false});
    assert(continued==1 && session.owner.filters.reloads==2 && Ui::Toast::count==1);
    callbacks=make(&session,[&](Filter) { ++continued; });
    callbacks.second();
    assert(continued==1 && session.owner.filters.reloads==3 && Ui::Toast::count==2);
    callbacks=make(&session,{});
    callbacks.first({true});
    assert(continued==1 && session.owner.filters.reloads==4 && Ui::Toast::count==2);
    std::cout << "CAPY_NATIVE_SAVE_SHARE=PASS (deferred continuation, accepted result copy, false Bool, RPC failure, empty continuation)\n";
}
'''.replace('__FAILED__',failed).replace('__DONE__',done)
with tempfile.TemporaryDirectory(prefix='capy-save-share-') as tmp:
    folder=Path(tmp);source=folder/'response.cpp';exe=folder/'response'
    source.write_text(program,encoding='utf-8')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
