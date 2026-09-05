# SPDX-License-Identifier: MIT
"""Install CI signing inputs and verify the public certificate, without logging secrets."""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess

ALIAS = 'capybaragram-preview'
PASSWORD_ENV = 'CAPY_ANDROID_KEYSTORE_PASSWORD'

def run_keytool(keytool, args, environ):
    launcher = [str(keytool), '-J-Xmx128m', '-J-XX:ActiveProcessorCount=2']
    # This host's keytool.exe launcher times out while java.exe from the same
    # verified JDK works. Invoke that JDK's identical built-in tool main class.
    java = Path(keytool).with_name('java.exe')
    if os.name == 'nt' and java.is_file():
        launcher = [str(java), '-Xmx128m', '-XX:ActiveProcessorCount=2', 'sun.security.tools.keytool.Main']
    result = subprocess.run([*launcher, *map(str, args)],
                            env=environ, stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise ValueError('Signing keystore verification failed.')
    return result.stdout

def certificate_digest(keytool, path, environ):
    certificate = run_keytool(keytool, ['-exportcert', '-keystore', path,
        '-storetype', 'PKCS12', '-alias', ALIAS, '-storepass:env', PASSWORD_ENV], environ)
    if not certificate or len(certificate) > 16384:
        raise ValueError('Unexpected signing certificate.')
    return hashlib.sha256(certificate).hexdigest()

def inputs(environ=None):
    env = os.environ if environ is None else environ
    encoded = env.get('CAPY_ANDROID_KEYSTORE_BASE64', '')
    password = env.get(PASSWORD_ENV, '')
    fingerprint = env.get('CAPY_ANDROID_CERT_SHA256', '')
    if not isinstance(encoded, str) or not 100 <= len(encoded) <= 45000:
        raise ValueError('Missing or invalid signing material.')
    if not isinstance(password, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', password):
        raise ValueError('Invalid signing password format.')
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise ValueError('Invalid certificate fingerprint.')
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ValueError('Invalid signing material encoding.') from None
    if not 100 <= len(content) <= 32768:
        raise ValueError('Unexpected keystore size.')
    return content, fingerprint

def install(path, keytool='keytool', environ=None):
    env = dict(os.environ if environ is None else environ)
    content, expected = inputs(env)
    # New runner-temp path owned by this workflow. Never replace a previous key.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(content)
    if certificate_digest(keytool, path, env) != expected:
        raise ValueError('Signing certificate does not match the pinned identity.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--keytool', default='keytool')
    args = parser.parse_args()
    try:
        if args.destination:
            install(args.destination, args.keytool)
        else:
            inputs()
    except (ValueError, OSError, subprocess.SubprocessError):
        print('REFUSED: signing inputs or certificate verification failed. No values logged.')
        raise SystemExit(1)
    print('PASS: signing input validation' + (' and pinned certificate.' if args.destination else '.'))
