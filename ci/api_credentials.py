# SPDX-License-Identifier: MIT
"""Validate application credentials without printing values or accepting shell code."""
import os
from pathlib import Path
import re

class CredentialError(ValueError):
    pass

def credentials(environ=None):
    env = os.environ if environ is None else environ
    api_id = env.get('CAPY_API_ID', '')
    api_hash = env.get('CAPY_API_HASH', '')
    if not isinstance(api_id, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', api_id):
        raise CredentialError('CAPY_API_ID must be a positive decimal application ID.')
    if int(api_id) > 2147483647:
        raise CredentialError('CAPY_API_ID exceeds the Telegram int32 range.')
    if not isinstance(api_hash, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', api_hash):
        raise CredentialError('CAPY_API_HASH must contain exactly 32 hexadecimal characters.')
    if api_id in {'6', '17349'}:
        raise CredentialError('Upstream sample application IDs are not accepted.')
    # Preserve the exact secret so CI masking also covers generated build inputs.
    return api_id, api_hash

def read_credentials_file(source):
    """Read only the exact user-specified file; values never go to stdout."""
    path = Path(source)
    if path.is_symlink() or not path.is_file():
        raise CredentialError('Credential file must be a regular file.')
    try:
        with path.open('rb') as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            raise CredentialError('Credential file is larger than expected.')
        encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        text = data.decode(encoding)
    except (OSError, UnicodeError):
        raise CredentialError('Cannot read credential file.') from None
    values = {}
    for line in text.splitlines():
        if not line.strip(): continue
        name, separator, value = line.partition('=')
        name = name.strip()
        if not separator or name not in {'api_id', 'api_hash'} or name in values:
            raise CredentialError('Expected exactly one api_id and one api_hash entry.')
        values[name] = value.strip()
    return credentials({'CAPY_API_ID':values.get('api_id',''), 'CAPY_API_HASH':values.get('api_hash','')})

def write_windows_cache(destination, environ=None):
    api_id, api_hash = credentials(environ)
    path = Path(destination)
    # Exclusive creation: never replace an existing user configuration.
    with path.open('x', encoding='ascii', newline='\n') as out:
        out.write('set(TDESKTOP_API_TEST OFF CACHE BOOL "" FORCE)\n')
        out.write('set(TDESKTOP_API_ID "' + api_id + '" CACHE STRING "" FORCE)\n')
        out.write('set(TDESKTOP_API_HASH "' + api_hash + '" CACHE STRING "" FORCE)\n')
    if os.name != 'nt':
        path.chmod(0o600)

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--windows-cache', type=Path)
    p.add_argument('--check-file', type=Path)
    args = p.parse_args()
    try:
        if args.check_file:
            if args.windows_cache: raise CredentialError('File validation does not generate build outputs.')
            read_credentials_file(args.check_file)
        elif args.windows_cache:
            write_windows_cache(args.windows_cache)
        else:
            credentials()
    except (CredentialError, OSError):
        print('REFUSED: missing/invalid credentials or unavailable private output file.')
        raise SystemExit(1)
    print('PASS: application credential format; server acceptance is not verified.')
