# SPDX-License-Identifier: MIT
"""Execute the native membership completion helper and success gate with fake UI."""
import argparse, importlib.util, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('patch',root/'prepare_windows_reconcile.py')
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
text=patch.plan(a.source)[patch.FILES[0]].decode('utf-8')
helper=text.split('const auto capyUpdateFinished = ',1)[1].split('\n\t\t};',1)[0]+'\n};'
start=text.index(')).done([=, chat = history->peer->name(), name = filter.title()]')
gate=text[start:].split('(const MTPBool &result) {',1)[1].split('const auto account =',1)[0]
failure=text[start:].split('}).fail(',1)[1].split('}).send();',1)[0]
assert 'capyUpdateFinished(false);' in failure and '.set(was)' not in failure
program=r'''
#include <cassert>
#include <functional>
#include <string>
#include <iostream>
struct MTPBool { bool value; };
bool mtpIsTrue(MTPBool result) { return result.value; }
std::u16string operator""_q(const char16_t *value, size_t size) { return {value,size}; }
struct Language { bool startsWith(const std::u16string&) const { return true; } };
namespace Lang { Language Id() { return {}; } }
namespace Ui::Toast { int errors=0; void Show(const std::u16string&) { ++errors; } }
struct Filters { int reloads=0; void reload() { ++reloads; } };
struct Owner { Filters filters; Filters& chatsFilters() { return filters; } };
struct History { Owner data; Owner& owner() { return data; } };
struct Callbacks { std::function<void(MTPBool)> done; std::function<bool(bool)> finished; };
Callbacks make(History *history, int *successes) {
    const auto capyUpdateFinished = __HELPER__
    auto done = [=](const MTPBool &result) {
        __GATE__
        ++*successes; // stand-in for native account/window toast UI only
    };
    return {done,capyUpdateFinished};
}
int main() {
    History history; int successes=0;
    auto callback=make(&history,&successes);
    callback.done({false});
    assert(successes==0 && history.data.filters.reloads==1 && Ui::Toast::errors==1);
    callback.done({true});
    assert(successes==1 && history.data.filters.reloads==2 && Ui::Toast::errors==1);
    assert(!callback.finished(false)); // same failure helper invoked by RPC fail
    assert(successes==1 && history.data.filters.reloads==3 && Ui::Toast::errors==2);
    std::cout << "CAPY_NATIVE_MEMBERSHIP=PASS (false response suppresses success, accepted response, failure refresh)\n";
}
'''.replace('__HELPER__',helper).replace('__GATE__',gate)
with tempfile.TemporaryDirectory(prefix='capy-membership-') as tmp:
    folder=Path(tmp);source=folder/'membership.cpp';exe=folder/'membership'
    source.write_text(program,encoding='utf-8')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
