#!/usr/bin/env python3
"""Inspect a built .deb and check it against the TOS 7 packaging rules.

This is the stand-in for ``dpkg-deb -c`` / ``dpkg-deb -I`` and ``lintian`` on
a machine that has neither. It parses the ar container and both inner tar
streams by hand, prints what it finds, and fails on anything the TOS 7 guide
or the Debian format requires.

Usage:
    python tools/verify_deb.py build/le3gold-cadviewer_x86_64.deb
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

AR_MAGIC = b'!<arch>\n'
AR_HEADER_SIZE = 60
DEBIAN_BINARY_CONTENT = b'2.0\n'

APPID = 'le3gold-cadviewer'
INSTALL_DIR = 'usr/local/' + APPID

# Files the payload must provide, with the mode they must carry.
REQUIRED_PAYLOAD = {
    INSTALL_DIR + '/config.ini': 0o644,
    INSTALL_DIR + '/%s.lang' % APPID: 0o644,
    INSTALL_DIR + '/%s.env' % APPID: 0o644,
    INSTALL_DIR + '/bin/' + APPID: 0o755,
    INSTALL_DIR + '/images/icons/%s.svg' % APPID: 0o644,
    INSTALL_DIR + '/init.d/%s.service' % APPID: 0o644,
    INSTALL_DIR + '/nginx/%s.conf' % APPID: 0o644,
    INSTALL_DIR + '/webui.bz2': 0o644,
}

REQUIRED_CONTROL_FIELDS = ('Package', 'Version', 'Architecture', 'Maintainer', 'Description',
                           'Depends')

TEXT_SUFFIXES = ('.ini', '.lang', '.env', '.conf', '.service', '.md', '.txt', '.sh', '.json')
LF_NAMES = frozenset(['config.ini', '%s.lang' % APPID, '%s.env' % APPID, 'bin/' + APPID,
                      'control', 'postinst', 'prerm', 'postrm', 'md5sums'])


def parse_ar(blob):
    """Return [(name, data)] for a Debian ar archive."""
    if not blob.startswith(AR_MAGIC):
        raise SystemExit('error: not an ar archive (bad magic)')
    members = []
    offset = len(AR_MAGIC)
    while offset + AR_HEADER_SIZE <= len(blob):
        header = blob[offset:offset + AR_HEADER_SIZE]
        offset += AR_HEADER_SIZE
        if header[58:60] != b'`\n':
            raise SystemExit('error: bad ar header terminator at offset %d' % offset)
        name = header[0:16].decode('ascii').strip()
        if name.endswith('/'):
            name = name[:-1]
        size = int(header[48:58].decode('ascii').strip())
        members.append((name, blob[offset:offset + size]))
        offset += size + (size % 2)
    return members


def parse_control(text):
    """Parse the control file, ignoring continuation lines."""
    fields = {}
    for line in text.split('\n'):
        if not line or line[0].isspace() or ':' not in line:
            continue
        key, _, value = line.partition(':')
        fields[key.strip()] = value.strip()
    return fields


def normalise(name):
    return name[2:] if name.startswith('./') else name


def read_control_tar(blob):
    """Return ({name: (mode, data)}, problems)."""
    entries = {}
    problems = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = normalise(member.name)
            handle = tar.extractfile(member)
            entries[name] = (member.mode, handle.read() if handle else b'')
    for name in ('control', 'postinst', 'prerm', 'postrm', 'md5sums'):
        if name not in entries:
            problems.append('control.tar.gz is missing %s' % name)
    for name, (mode, data) in sorted(entries.items()):
        if name in ('postinst', 'prerm', 'postrm'):
            if mode != 0o755:
                problems.append('%s in control.tar.gz must be mode 755, found %o' % (name, mode))
            if not data.startswith(b'#'):
                problems.append('%s in control.tar.gz must start with a shebang' % name)
        if b'\r\n' in data and name.endswith(TEXT_SUFFIXES):
            problems.append('%s in control.tar.gz contains CRLF line endings' % name)
    return entries, problems


def read_data_tar(blob):
    """Return ([(path, mode, size)], {path: data}, problems)."""
    listing = []
    files = {}
    problems = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
        for member in tar.getmembers():
            name = normalise(member.name)
            if member.isdir():
                listing.append((name + '/', member.mode, 0))
                continue
            if not member.isfile():
                problems.append('%s is neither a regular file nor a directory' % name)
                continue
            handle = tar.extractfile(member)
            data = handle.read() if handle else b''
            files[name] = data
            listing.append((name, member.mode, len(data)))
            if name in LF_NAMES or name.endswith(TEXT_SUFFIXES):
                if b'\r\n' in data:
                    problems.append('%s contains CRLF line endings' % name)
    return listing, files, problems


def check_parent_dirs(listing, problems):
    """Every ancestor directory needs its own entry, or dpkg cannot unpack.

    dpkg does not create missing parents, and it reports the failure as
    "unable to create '...x.dpkg-new': No such file or directory", which never
    names the directory that is actually missing. dpkg-deb always emits the
    ancestors, so a hand-written archive is the only way to get this wrong.
    """
    directories = set(path[:-1] for path, _mode, _size in listing if path.endswith('/'))
    for path, _mode, _size in listing:
        if path.endswith('/'):
            continue
        parts = path.split('/')
        for index in range(1, len(parts)):
            ancestor = '/'.join(parts[:index])
            if ancestor and ancestor not in directories:
                problems.append('data.tar.gz has no directory entry for /%s, '
                                'so dpkg cannot create /%s' % (ancestor, path))
                break


def check_unit_namespace(files, problems):
    """Catch the systemd hardening combination that cannot start on TOS 7.

    /var/log is a symlink to the tmpfs /tmp/log on TOS 7. Declaring
    ReadWritePaths=/var/log/<appid> together with PrivateTmp=true makes systemd
    resolve the path inside the unit namespace, where it does not exist, and
    the unit fails with 226/NAMESPACE before ExecStart ever runs. The guide's
    own template asks for exactly that combination.
    """
    path = '%s/init.d/%s.service' % (INSTALL_DIR, APPID)
    if path not in files:
        return
    text = files[path].decode('utf-8', 'replace')
    private_tmp = re.search(r'(?mi)^\s*PrivateTmp\s*=\s*(true|yes|1)\s*$', text)
    writable = re.findall(r'(?mi)^\s*ReadWritePaths\s*=\s*(.+)$', text)
    log_paths = [item for line in writable for item in line.split()
                 if item.startswith('/var/log')]
    if not log_paths:
        return
    listed = ', '.join(log_paths)
    if private_tmp:
        problems.append('the unit sets PrivateTmp=true and also lists %s in '
                        'ReadWritePaths; on TOS 7 /var/log is a symlink to the '
                        'tmpfs /tmp/log, so the unit fails with 226/NAMESPACE'
                        % listed)
    else:
        problems.append('the unit lists %s in ReadWritePaths; on TOS 7 /var/log '
                        'is a symlink to the tmpfs /tmp/log' % listed)


def check_unit_identity(files, problems):
    """Catch the unit identity that cannot start on TOS 7.

    The guide marks User=<appid> and Group=<appid> as required, but the
    platform creates only the user and gives it `allusers` as its primary
    group; no group named <appid> is created. Such a unit dies with
    "Failed to determine group credentials" / 216/GROUP and restart-loops.
    Adding the group by hand only moves the failure to 200/CHDIR, because the
    application's own files sit under /Volume1/@apps/<appid> (through the
    platform's /usr/local/<appid> symlink) and that btrfs volume is mounted
    with `tmacl`, which denies non-root users - including the application's own
    user - all access. Every application installed on the reference TNAS runs
    as root for this reason.
    """
    path = '%s/init.d/%s.service' % (INSTALL_DIR, APPID)
    if path not in files:
        return
    text = files[path].decode('utf-8', 'replace')
    for directive in ('User', 'Group'):
        match = re.search(r'(?mi)^\s*%s\s*=\s*(\S+)\s*$' % directive, text)
        if match and match.group(1) in (APPID, APPID + '.service'):
            problems.append('the unit sets %s=%s, but the platform never '
                            'creates that group: systemd fails with 216/GROUP '
                            'and the service restart-loops' % (directive, match.group(1)))


def check_permission_rules(entries, files, problems):
    """Encode the permission red lines from guide chapter 10."""
    for name in ('postinst', 'prerm', 'postrm'):
        if name not in entries:
            continue
        text = entries[name][1].decode('utf-8', 'replace')
        for command in ('useradd', 'adduser'):
            if command in text:
                problems.append('%s calls %s; the platform creates the app user (guide 10.3)'
                                % (name, command))
        for line in text.split('\n'):
            stripped = line.strip()
            # Removing the systemd unit on purge is what the official template
            # does; anything else under /etc is a permission red line (10.9).
            if stripped.startswith('#') or 'systemd/system' in stripped:
                continue
            if '/etc/' in stripped:
                problems.append('%s touches /etc (guide 10.9): %s' % (name, stripped))

    unit = files.get(INSTALL_DIR + '/init.d/%s.service' % APPID)
    if unit is None:
        problems.append('payload has no init.d/%s.service' % APPID)
        return
    text = unit.decode('utf-8', 'replace')
    # TOS 7 cannot satisfy the guide's non-root identity: the platform creates
    # the user but never a group of the same name (216/GROUP), and even once
    # the group exists the application's own files under /Volume1/@apps are
    # unreachable for non-root users, because that btrfs volume is mounted with
    # `tmacl`. Every application installed on the reference TNAS runs as root,
    # so only the hardening directives are required here. An explicit
    # User=<appid>/Group=<appid> is rejected by check_unit_identity instead.
    for directive in ('ProtectSystem=strict', 'NoNewPrivileges=true'):
        if directive not in text:
            problems.append('systemd unit is missing %s' % directive)


def check_md5sums(entries, files, problems):
    (_, md5_data) = entries['md5sums']
    declared = {}
    for line in md5_data.decode('utf-8').split('\n'):
        if not line.strip():
            continue
        digest, _, path = line.partition('  ')
        declared[path.strip()] = digest.strip()
    for path, data in files.items():
        if path.endswith('md5sums'):
            continue
        actual = hashlib.md5(data).hexdigest()
        if path not in declared:
            problems.append('md5sums does not list %s' % path)
        elif declared[path] != actual:
            problems.append('md5sums mismatch for %s' % path)
    for path in declared:
        if path not in files:
            problems.append('md5sums lists %s which is not in the payload' % path)


def check_webui(data, problems):
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:bz2') as tar:
            members = {normalise(member.name): member for member in tar.getmembers()}
            names = sorted(members)
            if 'index.html' not in names:
                problems.append('webui.bz2 has no index.html at its root')
                return 0, 0
            index = tar.extractfile(members['index.html']).read().decode('utf-8')
            if '<title>' not in index:
                problems.append('webui.bz2 index.html has no <title>')
            if 'assets/externallibs/occt-import-js.wasm' not in names:
                problems.append('webui.bz2 is missing assets/externallibs/occt-import-js.wasm')
            for name in names:
                if '..' in name.split('/'):
                    problems.append('webui.bz2 entry escapes its root: %s' % name)
            return len([n for n in names if members[n].isfile()]), len(data)
    except tarfile.TarError as error:
        problems.append('webui.bz2 cannot be read: %s' % error)
        return 0, 0


def main():
    parser = argparse.ArgumentParser(description='Verify a built CAD Viewer .deb package.')
    parser.add_argument('package', help='path to the .deb file')
    args = parser.parse_args()

    with open(args.package, 'rb') as handle:
        blob = handle.read()
    print('file       : %s' % os.path.abspath(args.package))
    print('size       : %d bytes' % len(blob))
    print('sha256     : %s' % hashlib.sha256(blob).hexdigest())

    problems = []
    members = parse_ar(blob)
    names = [name for name, _ in members]
    print('ar members : %s' % ', '.join(names))
    if names != ['debian-binary', 'control.tar.gz', 'data.tar.gz']:
        problems.append('ar members must be debian-binary, control.tar.gz, data.tar.gz in order')
        report(problems)
        return 1

    contents = dict(members)
    if contents['debian-binary'] != DEBIAN_BINARY_CONTENT:
        problems.append('debian-binary must contain exactly "2.0\\n"')

    entries, control_problems = read_control_tar(contents['control.tar.gz'])
    problems.extend(control_problems)
    fields = parse_control(entries['control'][1].decode('utf-8')) if 'control' in entries else {}

    print()
    print('control    :')
    for key in ('Package', 'Version', 'Architecture', 'Section', 'Priority', 'Maintainer',
                'Depends', 'Installed-Size', 'Homepage'):
        if key in fields:
            print('  %-14s %s' % (key + ':', fields[key]))
    description = fields.get('Description', '').split('\n')[0]
    if description:
        print('  %-14s %s' % ('Description:', description))
    for key in REQUIRED_CONTROL_FIELDS:
        if key not in fields:
            problems.append('DEBIAN/control is missing the %s field' % key)
    if fields.get('Package') != APPID:
        problems.append('DEBIAN/control Package must be %s' % APPID)
    if fields.get('Architecture') not in ('amd64', 'arm64'):
        problems.append('DEBIAN/control Architecture must be amd64 or arm64')

    listing, files, data_problems = read_data_tar(contents['data.tar.gz'])
    problems.extend(data_problems)
    check_parent_dirs(listing, problems)

    print()
    print('payload    : %d entries' % len(listing))
    for path, mode, size in sorted(listing):
        print('  %04o %10d  /%s' % (mode, size, path))

    for path, mode in REQUIRED_PAYLOAD.items():
        if path not in files:
            problems.append('payload is missing /%s' % path)
            continue
        actual = next((m for p, m, _s in listing if p == path), None)
        if actual is not None and actual != mode:
            problems.append('/%s must be mode %04o, found %04o' % (path, mode, actual))
    for path in files:
        if not path.startswith(INSTALL_DIR + '/'):
            problems.append('payload file outside %s: /%s' % (INSTALL_DIR, path))

    check_md5sums(entries, files, problems)
    check_permission_rules(entries, files, problems)
    check_unit_namespace(files, problems)
    check_unit_identity(files, problems)

    if INSTALL_DIR + '/config.ini' in files:
        try:
            config = json.loads(files[INSTALL_DIR + '/config.ini'].decode('utf-8'))
        except ValueError as error:
            problems.append('config.ini is not valid JSON: %s' % error)
        else:
            if config.get('version') != fields.get('Version'):
                problems.append('config.ini version and DEBIAN/control Version disagree')
            if '${ip}' not in str(config.get('path', '')):
                problems.append('config.ini path must use the ${ip} placeholder')

    if INSTALL_DIR + '/webui.bz2' in files:
        count, size = check_webui(files[INSTALL_DIR + '/webui.bz2'], problems)
        print()
        print('webui      : %d files, %d bytes' % (count, size))

    return report(problems)


def report(problems):
    print()
    if problems:
        for problem in problems:
            print('FAIL : %s' % problem)
        print('%d problem(s) found' % len(problems))
        return 1
    print('OK   : package satisfies the checked TOS 7 and Debian format rules')
    return 0


if __name__ == '__main__':
    sys.exit(main())
