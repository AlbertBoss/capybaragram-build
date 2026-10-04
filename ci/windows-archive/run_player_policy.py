# SPDX-License-Identifier: MIT
"""Real decoder/URL policy probe with synthetic media, never Telegram profiles."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import threading
import urllib.request

here = Path(__file__).resolve().parent
root = Path(os.environ['RUNNER_TEMP']) / 'capy-archive-player-policy'
root.mkdir(exist_ok=False)
report = here / 'player-policy-results'
report.mkdir(exist_ok=False)
manifest_path = here / 'windows-archive-hashes.json'
manifest = json.loads(manifest_path.read_text())
source_path = 'Telegram/SourceFiles/ffmpeg/ffmpeg_utility.cpp'
source_sha = manifest['source_sha']
url = 'https://raw.githubusercontent.com/telegramdesktop/tdesktop/' + source_sha + '/' + source_path
with urllib.request.urlopen(url, timeout=60) as response:
    source = response.read(131073).replace(b'\r\n', b'\n')
assert len(source) <= 131072
assert hashlib.sha256(source).hexdigest() == manifest['pre'][source_path]
assert manifest['pre'][source_path] == manifest['post'][source_path]
source_text = source.decode('utf-8')
matches = re.findall(r'void RestrictToCustomIO\(AVFormatContext \*format\) \{\n.*?\n\}', source_text, re.S)
assert len(matches) == 1
function = matches[0]
assert 'av_opt_set(format, "protocol_whitelist", "", 0);' in function
# Preserve the upstream notice on its exact generated function. No native policy
# is reimplemented in the scaffold; FFmpeg executes the production guard body.
notice = source_text[:source_text.index('#include')]
(root / 'pinned_policy.inc').write_text(notice + '\nnamespace FFmpeg {\n' + function + '\n}\n', encoding='utf-8')

voice = root / 'voice.ogg'
video = root / 'video.mp4'
segment = root / 'segment.ts'
def ffmpeg(args):
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', *args], check=True, timeout=60)
ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-ac', '1', '-ar', '48000', '-c:a', 'libopus', str(voice)])
ffmpeg(['-f', 'lavfi', '-i', 'color=c=green:s=64x64:r=12:d=1', '-f', 'lavfi', '-i',
    'sine=frequency=880:duration=1', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-shortest', str(video)])
ffmpeg(['-i', str(video), '-c', 'copy', '-f', 'mpegts', str(segment)])
requests = []
segment_bytes = segment.read_bytes()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append(self.path)
        self.send_response(200 if self.path == '/segment.ts' else 404)
        self.send_header('Content-Type', 'video/mp2t')
        self.send_header('Content-Length', str(len(segment_bytes) if self.path == '/segment.ts' else 0))
        self.end_headers()
        if self.path == '/segment.ts':
            self.wfile.write(segment_bytes)
    def log_message(self, *args):
        pass
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
def playlist(uri):
    return '#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1,\n' + uri + '\n#EXT-X-ENDLIST\n'
http = root / 'nested-http.m3u8'
local = root / 'nested-file.m3u8'
http.write_text(playlist('http://127.0.0.1:' + str(server.server_port) + '/segment.ts'), encoding='utf-8')
local.write_text(playlist(segment.as_uri()), encoding='utf-8')
flags = shlex.split(subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt6Core', 'libavformat', 'libavcodec', 'libavutil'],
    capture_output=True, text=True, check=True, timeout=30).stdout)
exe = root / 'player-policy-probe.exe'
try:
    subprocess.run(['g++', '-std=c++20', '-Wall', '-Wextra', '-Werror', '-I' + str(root),
        str(here / 'player_policy_probe.cpp'), '-o', str(exe)] + flags, check=True, timeout=180)
    run = subprocess.run([str(exe), str(video), str(voice), str(http), str(local)],
        capture_output=True, encoding='utf-8', errors='replace', timeout=60)
    (report / 'runtime-result.txt').write_text(run.stdout + run.stderr, encoding='utf-8')
    match = re.fullmatch(r'CAPY_ARCHIVE_PLAYER_POLICY=PASS checks=([0-9]+) avformat=([0-9]+)\s*', run.stdout)
    if run.returncode or not match:
        raise RuntimeError('Archive decoder policy probe failed; inspect artifact')
    assert requests and all(path == '/segment.ts' for path in requests)
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
result = {
    'result': 'PASS', 'checks': int(match.group(1)), 'avformat_version': int(match.group(2)),
    'commit': os.environ['GITHUB_SHA'], 'upstream_commit': source_sha,
    'upstream_guard_file': source_path, 'upstream_guard_file_sha256': hashlib.sha256(source).hexdigest(),
    'extracted_guard_sha256': hashlib.sha256(function.encode('utf-8')).hexdigest(),
    'http_control_requests': len(requests),
    'source_sha256': {p.name: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        for p in (Path(__file__), here / 'player_policy_probe.cpp', manifest_path)},
    'fixture_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (voice, video, segment)},
    'scope': 'Real FFmpeg decode and exact pinned upstream external-resource guard with allowed/denied controls',
    'native_ui_compiled': False, 'speaker_playback_tested': False, 'real_telegram_tested': False,
    'dependencies': 'Official MSYS2 test-only Qt/FFmpeg; not production vendored libraries'}
(report / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(run.stdout, flush=True)
