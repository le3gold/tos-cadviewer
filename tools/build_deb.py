#!/usr/bin/env python3
"""Build the CAD Viewer .deb package without dpkg-deb.

dpkg-deb is only available on Debian-derived systems, so this script writes
the Debian binary package format directly. A .deb is a plain Unix ``ar``
archive holding exactly three members, in this order:

    debian-binary     the text "2.0\\n"
    control.tar.gz    DEBIAN/control plus the maintainer scripts
    data.tar.gz       the payload, rooted at /

Everything the TOS 7 guide requires before packaging is checked here:
config.ini must be valid JSON and agree with DEBIAN/control, the icon and
webui.bz2 must exist, and every text file is written with LF line endings so
the shell scripts cannot break on a system with CRLF-unsafe shebangs.

Usage:
    python tools/build_deb.py                    # build for x86_64
    python tools/build_deb.py --platform aarch64
    python tools/build_deb.py --allow-placeholders
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import time

APPID = 'le3gold-cadviewer'
VERSION_FALLBACK = '1.1.3'

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_DIR = 'usr/local/' + APPID

# Relative to the project root. Directories are copied recursively.
PAYLOAD_FILES = (
    ('config.ini', 0o644),
    ('le3gold-cadviewer.lang', 0o644),
    ('le3gold-cadviewer.env', 0o644),
    ('README.md', 0o644),
    ('bin/le3gold-cadviewer', 0o755),
)
PAYLOAD_DIRS = (
    'images',
    'init.d',
    'nginx',
    'licenses',
)
# Produced by tools/make_webui.py, not committed.
PAYLOAD_GENERATED = (
    ('webui.bz2', 0o644),
)

# DEBIAN/<name> on disk -> <name> inside control.tar.gz, with its mode.
CONTROL_FILES = (
    ('DEBIAN/control', 'control', 0o644),
    ('DEBIAN/postinst', 'postinst', 0o755),
    ('DEBIAN/prerm', 'prerm', 0o755),
    ('DEBIAN/postrm', 'postrm', 0o755),
)

# Rewritten into DEBIAN/control for the requested platform.
ARCHITECTURES = {'x86_64': 'amd64', 'aarch64': 'arm64'}

# Suffixes that must be written with LF endings.
LF_SUFFIXES = ('.sh', '.ini', '.lang', '.env', '.conf', '.service', '.md', '.txt', '.json')
LF_NAMES = frozenset(['config.ini', 'le3gold-cadviewer.lang', 'le3gold-cadviewer.env', 'bin/le3gold-cadviewer',
                      'control', 'postinst', 'prerm', 'postrm', 'md5sums'])

# Reported before a real submission, never in a package that is uploaded.
PLACEHOLDER_PATTERNS = ('YOUR-ORG', 'YOUR-REPO', 'your.email@example.com', 'Your Name')

AR_MAGIC = b'!<arch>\n'
GLOBAL_AR_HEADER = '%-16s%-12d%-6d%-6d%-8o%-10d`\n'
AR_HEADER_SIZE = 60


def needs_lf(relpath):
    return relpath in LF_NAMES or relpath.endswith(LF_SUFFIXES) or os.path.basename(relpath).startswith('LICENSE')


def read_payload(path, relpath):
    with open(path, 'rb') as handle:
        data = handle.read()
    if needs_lf(relpath):
        data = data.replace(b'\r\n', b'\n')
    return data


def add_entry(tar, name, data, mode, epoch, is_dir=False):
    info = tarfile.TarInfo(name)
    info.mtime = epoch
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    info.mode = mode
    if is_dir:
        info.type = tarfile.DIRTYPE
        tar.addfile(info)
    else:
        info.type = tarfile.REGTYPE
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def collect_payload(root):
    """Return the payload as a sorted list of (path, mode, data) tuples."""
    entries = []
    for relpath, mode in PAYLOAD_FILES + PAYLOAD_GENERATED:
        full = os.path.join(root, relpath)
        if not os.path.isfile(full):
            raise SystemExit('error: missing payload file: %s' % relpath)
        entries.append((relpath, mode, read_payload(full, relpath)))
    for dirname in PAYLOAD_DIRS:
        base = os.path.join(root, dirname)
        if not os.path.isdir(base):
            raise SystemExit('error: missing payload directory: %s' % dirname)
        entries.append((dirname, 0o755, None))
        for current, dirs, files in os.walk(base):
            dirs.sort()
            for name in sorted(files):
                child = os.path.join(current, name)
                relpath = os.path.relpath(child, root).replace('\\', '/')
                entries.append((relpath, 0o644, read_payload(child, relpath)))
    entries.sort(key=lambda entry: entry[0])
    return entries


def add_ancestor_dirs(members):
    """Insert the directory entries dpkg needs but does not create on its own.

    dpkg does not create missing parents while unpacking. If data.tar.gz holds
    ./usr/local/myapp/bin/myapp but has no entry for ./usr/local/myapp/bin, the
    install dies at once with:

        unable to create '.../bin/myapp.dpkg-new': No such file or directory

    dpkg-deb always emits every ancestor directory, so a hand-written archive
    has to do the same. The result is sorted so a parent always precedes its
    children.
    """
    known = set(name for name, _data, _mode, is_dir in members if is_dir)
    added = []
    for name, _data, _mode, _is_dir in members:
        parts = name.split('/')
        for index in range(1, len(parts)):
            ancestor = '/'.join(parts[:index])
            if ancestor == '.':
                ancestor = './'
            if ancestor not in known:
                known.add(ancestor)
                added.append((ancestor, None, 0o755, True))
    return sorted(members + added, key=lambda member: member[0])


def build_md5sums(entries):
    lines = []
    for relpath, _mode, data in entries:
        if data is None:
            continue
        digest = hashlib.md5(data).hexdigest()
        lines.append('%s  %s/%s' % (digest, INSTALL_DIR, relpath))
    return ('\n'.join(sorted(lines)) + '\n').encode('utf-8')


def tar_gz(members, epoch):
    """members: iterable of (name, data, mode, is_dir)."""
    plain = io.BytesIO()
    with tarfile.open(fileobj=plain, mode='w', format=tarfile.GNU_FORMAT) as tar:
        for name, data, mode, is_dir in members:
            add_entry(tar, name, data, mode, epoch, is_dir)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=9, mtime=epoch) as handle:
        handle.write(plain.getvalue())
    return buf.getvalue()


def ar_member(name, data, epoch):
    header = GLOBAL_AR_HEADER % (name, epoch, 0, 0, 0o100644, len(data))
    assert len(header) == AR_HEADER_SIZE, 'ar header must be exactly 60 bytes'
    blob = header.encode('ascii') + data
    if len(data) % 2:
        blob += b'\n'  # members are padded to an even offset
    return blob


REQUIRED_CONFIG = ('id', 'icon', 'publisher', 'exec', 'version', 'category', 'platform',
                   'system_id', 'package', 'application_type', 'user', 'low_version',
                   'recommend', 'beta')


def read_control(root):
    with open(os.path.join(root, 'DEBIAN', 'control'), 'rb') as handle:
        text = handle.read().replace(b'\r\n', b'\n').decode('utf-8')
    fields = {}
    for line in text.split('\n'):
        if line[:1].isalpha() and ':' in line:
            key, _, value = line.partition(':')
            fields[key.strip()] = value.strip()
    return text, fields


def read_service(root, system_id):
    path = os.path.join(root, 'init.d', '%s.service' % system_id)
    if not os.path.isfile(path):
        return None
    with open(path, 'rb') as handle:
        return handle.read().decode('utf-8')


def preflight(root, config, control_text, control_fields):
    """Check everything the guide asks for: (errors, warnings, placeholders)."""
    errors = []
    warnings = []

    for key in REQUIRED_CONFIG:
        if key not in config:
            errors.append('config.ini is missing the required field "%s"' % key)

    if config.get('id') != APPID:
        errors.append('config.ini id is %r, expected %r' % (config.get('id'), APPID))
    if config.get('application_type') != 'deb':
        errors.append('config.ini application_type must be "deb"')
    if config.get('exec') is not True:
        errors.append('config.ini exec must be true for a service application')
    if config.get('open_path') is not True:
        errors.append('config.ini open_path must be true (WebUI external open)')
    if 'type' in config:
        errors.append('config.ini must not set "type" together with "open_path"')
    if '${ip}' not in str(config.get('path', '')):
        errors.append('config.ini path must use the ${ip} placeholder')
    if not config.get('category'):
        errors.append('config.ini needs at least one category')
    elif len(config['category']) > 3:
        errors.append('config.ini allows at most 3 categories')
    if config.get('recommend') is not False:
        errors.append('config.ini recommend must be false when submitting')
    if not config.get('low_version', '').startswith('TOS7'):
        errors.append('config.ini low_version must be TOS7.0 or higher')

    if config.get('package') != control_fields.get('Package'):
        errors.append('config.ini package (%r) must match DEBIAN/control Package (%r)'
                      % (config.get('package'), control_fields.get('Package')))
    if config.get('version') != control_fields.get('Version'):
        errors.append('config.ini version (%r) must match DEBIAN/control Version (%r)'
                      % (config.get('version'), control_fields.get('Version')))

    system_id = config.get('system_id')
    service = read_service(root, system_id)
    if service is None:
        errors.append('system_id %r has no init.d/%s.service' % (system_id, system_id))
    else:
        # The guide marks User=<appid> and Group=<appid> as required, but the
        # platform creates only the user: no group named <appid> exists, so
        # systemd aborts with 216/GROUP. Creating the group by hand only moves
        # the failure to 200/CHDIR, because the application's files live under
        # /Volume1/@apps/<appid> and that btrfs volume is mounted with `tmacl`,
        # which denies non-root users all access - the application's own user
        # included. Every application installed on the reference TNAS runs as
        # root, so an explicit identity is a defect, not a compliance item.
        uncommented = re.sub(r'(?mi)^\s*#.*$', '', service)
        for directive in ('User', 'Group'):
            match = re.search(r'(?mi)^\s*%s\s*=\s*(\S+)\s*$' % directive, uncommented)
            if match and match.group(1) == config.get('user'):
                errors.append('systemd unit sets %s=%s, but the platform creates no such group '
                              '(systemd fails with 216/GROUP, and the app user cannot read '
                              '/Volume1/@apps anyway): leave the identity unset'
                              % (directive, match.group(1)))
        if 'ProtectSystem=strict' not in service:
            warnings.append('systemd unit should set ProtectSystem=strict')
        if 'NoNewPrivileges=true' not in service:
            warnings.append('systemd unit should set NoNewPrivileges=true')
        if 'Restart=' not in service:
            warnings.append('systemd unit has no Restart= policy, the App Center cannot recover it')

    icon = str(config.get('icon', '')).lstrip('/')
    if not icon.startswith('images/icons/'):
        errors.append('config.ini icon must follow /images/icons/<id>.svg')
    elif not os.path.isfile(os.path.join(root, icon)):
        errors.append('icon file %s does not exist' % icon)
    if not os.path.isfile(os.path.join(root, 'nginx', '%s.conf' % APPID)):
        errors.append('external open requires nginx/%s.conf' % APPID)
    if not os.path.isfile(os.path.join(root, 'webui.bz2')):
        errors.append('webui.bz2 is missing, run tools/make_webui.py first')

    # Placeholders are reported separately: they must be gone before a real
    # submission, but a local test build is allowed to keep them.
    placeholders = []
    for token in PLACEHOLDER_PATTERNS:
        if token in control_text:
            placeholders.append('DEBIAN/control still contains %r' % token)
        for relative in ('config.ini', 'README.md'):
            with open(os.path.join(root, relative), 'rb') as handle:
                if token.encode('utf-8') in handle.read():
                    placeholders.append('%s still contains %r' % (relative, token))
    return errors, warnings, sorted(set(placeholders))


def load_config(root):
    path = os.path.join(root, 'config.ini')
    with open(path, 'rb') as handle:
        raw = handle.read()
    try:
        config = json.loads(raw.replace(b'\r\n', b'\n').decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise SystemExit('error: config.ini is not valid JSON: %s' % error)
    if not isinstance(config, dict):
        raise SystemExit('error: config.ini must contain a JSON object')
    return config


def prepare_control(control_text, platform, installed_size):
    text, count = re.subn(r'(?m)^Architecture:.*$', 'Architecture: %s' % ARCHITECTURES[platform],
                          control_text)
    if count != 1:
        raise SystemExit('error: DEBIAN/control needs exactly one Architecture field')
    if 'Installed-Size:' not in text:
        text, count = re.subn(r'(?m)^(Priority:.*)$', '\\1\nInstalled-Size: %d' % installed_size,
                              text, count=1)
        if count != 1:
            raise SystemExit('error: DEBIAN/control needs a Priority field to anchor Installed-Size')
    if not text.endswith('\n'):
        text += '\n'
    return text


def main():
    parser = argparse.ArgumentParser(description='Build the CAD Viewer TOS 7 .deb package.')
    parser.add_argument('--platform', choices=sorted(ARCHITECTURES), default='x86_64',
                        help='target platform (default: x86_64)')
    parser.add_argument('--out-dir', default=os.path.join(PROJECT_ROOT, 'build'),
                        help='directory for the built package (default: <project>/build)')
    parser.add_argument('--allow-placeholders', action='store_true',
                        help='build even though the publisher placeholders are still in the sources')
    parser.add_argument('--epoch', type=int,
                        default=int(os.environ.get('SOURCE_DATE_EPOCH') or '1704067200'),
                        help='timestamp stored in the archives; a fixed value keeps builds reproducible')
    args = parser.parse_args()

    root = PROJECT_ROOT
    config = load_config(root)
    control_text, control_fields = read_control(root)
    errors, warnings, placeholders = preflight(root, config, control_text, control_fields)

    for warning in warnings:
        print('warning : %s' % warning)
    for problem in errors:
        print('error   : %s' % problem)
    if errors:
        return 1
    for problem in placeholders:
        if args.allow_placeholders:
            print('warning : %s' % problem)
        else:
            print('error   : %s' % problem)
    if placeholders and not args.allow_placeholders:
        print('error   : replace the placeholders, or pass --allow-placeholders for a test build')
        return 1

    epoch = args.epoch
    entries = collect_payload(root)
    installed_size = -(-sum(len(data) for _p, _m, data in entries if data is not None) // 1024)

    data_members = [('./%s/%s' % (INSTALL_DIR, relpath),
                     0 if data is None else data, mode, data is None)
                    for relpath, mode, data in entries]
    data_members = add_ancestor_dirs(data_members)
    control_members = []
    for source, name, mode in CONTROL_FILES:
        target = name if name == 'control' else name
        if name == 'control':
            data = prepare_control(control_text, args.platform, installed_size).encode('utf-8')
        else:
            data = read_payload(os.path.join(root, source), name)
        control_members.append(('./' + target, data, mode, False))
    control_members.append(('./md5sums', build_md5sums(entries), 0o644, False))

    control_tar = tar_gz(control_members, epoch)
    data_tar = tar_gz(data_members, epoch)
    blob = (AR_MAGIC
            + ar_member('debian-binary/', b'2.0\n', epoch)
            + ar_member('control.tar.gz/', control_tar, epoch)
            + ar_member('data.tar.gz/', data_tar, epoch))

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    # The asset name carries the version: <appid>_<version>_<platform>.deb.
    # This is what the guide's quick start (03_Quick_Start.md:52), local testing
    # (13_Local_Testing.md:28), CI recipe (14_CICD_Guide.md:58), lintian step
    # (06_Development_Environment.md:193) and the official template's build.sh
    # all produce. Note that 15_Publishing_Process.md:39 says the opposite
    # ("Version numbers are not included in the file name") and 15:59 warns that
    # non-compliant names are rejected automatically, so the two halves of the
    # guide disagree; flip NAMING below if the platform ever enforces the
    # unversioned form.
    out_path = os.path.join(out_dir, '%s_%s_%s.deb' % (APPID, config.get('version'), args.platform))
    with open(out_path, 'wb') as handle:
        handle.write(blob)
    digest = hashlib.sha256(blob).hexdigest()
    with open(out_path + '.sha256', 'w', encoding='ascii', newline='\n') as handle:
        handle.write('%s  %s\n' % (digest, os.path.basename(out_path)))

    print('package : %s' % out_path)
    print('version : %s (%s)' % (config.get('version'), ARCHITECTURES[args.platform]))
    print('payload : %d files, %d kB installed' % (len(entries), installed_size))
    print('sizes   : control.tar.gz %d B, data.tar.gz %d B, .deb %d B'
          % (len(control_tar), len(data_tar), len(blob)))
    print('sha256  : %s' % digest)
    return 0


if __name__ == '__main__':
    sys.exit(main())
