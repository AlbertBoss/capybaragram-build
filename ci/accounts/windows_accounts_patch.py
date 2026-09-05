# SPDX-License-Identifier: MIT
"""Ten local account slots on the pinned native Desktop source; no Premium spoofing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
PREFIX = 'Telegram/SourceFiles/'
FILES = [PREFIX + name for name in (
    'main/main_domain.h', 'main/main_domain.cpp',
    'boxes/premium_preview_box.cpp', 'boxes/premium_limits_box.cpp')]

def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Reviewed Desktop source anchor differs.')
    return text.replace(old, new)

def transform(name, text):
    if name == FILES[0]:
        text = replace(text, 'static constexpr auto kMaxAccounts = 3;',
                       'static constexpr auto kMaxAccounts = 10;')
        return replace(text, 'static constexpr auto kPremiumMaxAccounts = 6;',
                       'static constexpr auto kPremiumMaxAccounts = kMaxAccounts;')
    if name == FILES[1]:
        old = '''int Domain::maxAccounts() const {
	const auto premiumCount = ranges::count_if(accounts(), [](
			const Main::Domain::AccountWithIndex &d) {
		return d.account->sessionExists()
			&& (d.account->session().premium()
				|| d.account->session().isTestMode());
	});
	return std::min(int(premiumCount) + kMaxAccounts, kPremiumMaxAccounts);
}'''
        return replace(text, old, '''int Domain::maxAccounts() const {
	return kMaxAccounts;
}''')
    if name == FILES[2]:
        start = '\tconst auto nextMax = session->domain().maxAccounts() + 1;\n'
        end = '\t{\n\t\tconst auto premium = limits.similarChannelsPremium();'
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError('Premium account entry anchors differ.')
        first, last = text.index(start), text.index(end)
        if first >= last:
            raise ValueError('Premium entry source order differs.')
        return text[:first] + text[last:]
    if name == FILES[3]:
        start = 'void AccountsLimitBox(\n'
        end = 'QString LimitsPremiumRef(const QString &addition) {'
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError('Account limit box anchors differ.')
        first, last = text.index(start), text.index(end)
        if first >= last:
            raise ValueError('Account limit box source order differs.')
        new = '''void AccountsLimitBox(
		not_null<Ui::GenericBox*> box,
		not_null<Main::Session*> session) {
	box->setWidth(st::boxWideWidth);
	box->setTitle(tr::lng_accounts_limit_title());
	box->verticalLayout()->add(
		object_ptr<Ui::FlatLabel>(
			box,
			tr::lng_accounts_limit1(
				lt_count,
				rpl::single<float64>(session->domain().accounts().size()),
				tr::rich),
			st::aboutRevokePublicLabel),
		st::boxPadding);
	box->addButton(tr::lng_box_ok(), [=] {
		box->closeBox();
	});
}

'''
        return text[:first] + new + text[last:]
    raise ValueError('Unexpected Desktop account patch target.')

def hashes():
    data = json.loads(Path(__file__).with_name('windows-account-input-hashes.json').read_text())
    if set(data['patch']) != set(FILES):
        raise ValueError('Desktop patch allowlist differs.')
    return data

def plan(source):
    root = Path(source).resolve(strict=True)
    expected = hashes()['patch']
    result = {}
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Desktop source path escapes checkout.')
        raw = path.read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != expected[name]:
            raise ValueError('Desktop source differs from pinned input.')
        result[name] = transform(name, raw.decode('utf-8')).encode('utf-8')
    return result

def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], check=True,
                            capture_output=True, timeout=30)
    return result.stdout

def prepare(source, check=False):
    root = Path(source).resolve(strict=True)
    if git(root, 'rev-parse', 'HEAD').decode().strip() != SOURCE_SHA:
        raise ValueError('Desktop checkout revision differs.')
    if check:
        expected = hashes()['patch']
        for name in FILES:
            original = git(root, 'show', 'HEAD:' + name).replace(b'\r\n', b'\n')
            if hashlib.sha256(original).hexdigest() != expected[name]:
                raise ValueError('Committed Desktop input differs.')
            path = root / name
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
                raise ValueError('Desktop source path escapes checkout.')
            actual = path.read_bytes().replace(b'\r\n', b'\n')
            if actual != transform(name, original.decode('utf-8')).encode('utf-8'):
                raise ValueError('Prepared Desktop account code differs.')
    else:
        prepared = plan(root)  # Validate all files before writing any of them.
        for name, raw in prepared.items():
            (root / name).write_bytes(raw.replace(b'\n', b'\r\n') if os.name == 'nt' else raw)
    return len(FILES)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    count = prepare(args.source, args.check)
    print('PASS:', count, 'Desktop account files', 'verified' if args.check else 'prepared')
