#!/usr/bin/env python3
"""Build webui.bz2 for the CAD Viewer TOS 7 application package.

TOS 7 ships an application's whole web frontend as a single ``webui.bz2``
archive, which the package postinst script extracts to
``/usr/local/le3gold-cadviewer/webui`` at install time.

Input is a *staged* copy of the upstream Online 3D Viewer build (see
tools/build_frontend.py). On top of a plain "tar the directory" step this
script:

  1. ships only the sample models that are small and whose licence allows
     redistribution - the upstream demo set is 17.6 MB and contains models
     that must not go into a published package (see KEEP_MODELS);
  2. rewrites the HTML entry points so that nothing links to a file that is
     no longer shipped, or to a public website the NAS cannot reach;
  3. writes a deterministic archive - sorted entries, fixed timestamps and
     permissions, uid/gid 0 - so the same frontend always produces the same
     webui.bz2, and therefore the same .deb.

Usage:
    python tools/make_webui.py --stage D:/work/_vendor/webui_stage --out webui.bz2
"""

import argparse
import io
import os
import re
import sys
import tarfile

MODELS_REL = 'assets/models'

# Sample models kept from the upstream demo set. Every one of them is either
# MIT/BSD/CC0/LGPL licensed or a fixture from a public file-format test suite.
# Dropped on purpose:
#   DamagedHelmet.glb         CC BY-NC - non-commercial only, cannot be shipped
#   X_Bot.dae, Y_Bot.fbx      Mixamo assets - redistribution restricted
#   haus.ifc, RhinoLogo.3dm   fine to ship, but 2.5 MB / 0.9 MB of demo data
#   christmas_challenge.*, logo.*   not referenced by the frontend
KEEP_MODELS = frozenset([
    'ArchDetail.FCStd',
    'MultipleMeshes.bim',
    'README.md',
    'as1_pe_203.brep',
    'as1_pe_203.igs',
    'as1_pe_203.stp',
    'car.glb',
    'cow.ply',
    'cube.off',
    'cubes.3ds',
    'extrusion3.wrl',
    'rhombicuboctahedron.3mf',
    'rook.amf',
    'solids.mtl',
    'solids.obj',
    'texture.png',
    'utah_teapot.stl',
])

# The start page lists one example file per supported format. The glTF entry
# points at a model that is no longer shipped, so send it to another sample
# instead of dropping the entry.
MODEL_ALIASES = {'gltf': 'assets/models/car.glb'}

# Written into the archive next to the upstream models README so that the
# difference between the upstream demo set and what this package ships is
# recorded where a reviewer will look for it.
SUBSET_NOTE_PATH = 'assets/models/SHIPPED-SUBSET.md'
SUBSET_NOTE = """# Sample models shipped in this package

This package ships a subset of the upstream Online 3D Viewer demo models. The
packaging step dropped the rest:

| File | Reason |
|---|---|
| `DamagedHelmet.glb` | CC BY-NC - non-commercial only, not redistributable |
| `X_Bot.dae`, `Y_Bot.fbx` | Mixamo assets - redistribution restricted |
| `haus.ifc`, `RhinoLogo.3dm` | redistributable, dropped to keep the package small |
| `christmas_challenge.*`, `logo.*` | not referenced by the frontend |

The glTF example link on the start page therefore opens `car.glb` instead of
`DamagedHelmet.glb`. Every remaining sample is unchanged from upstream and
keeps the licence recorded in `README.md`.
"""

# Text files are normalised to LF. The frontend is served by our own HTTP
# server, so CRLF would not break anything, but it bloats the archive and
# makes the build output depend on the checkout's line-ending settings.
TEXT_SUFFIXES = ('.html', '.css', '.js', '.mjs', '.json', '.svg', '.txt', '.md')

CANONICAL_RE = re.compile(r'[ \t]*<link[^>]*rel="canonical"[^>]*>[ \t]*\r?\n', re.I)
TITLE_RE = re.compile(r'<title>[^<]*</title>')
EXAMPLE_LINK_RE = re.compile(r'([ \t]*)<a href="#model=([^"]+)">([^<]+)</a>[ \t]*\r?\n')

# Appended to index.html and run on window load, i.e. after the bundled
# OV.StartWebsite() handler has filled in the start page text. If every
# example link was dropped there is nothing left to show, so remove the
# whole block instead of leaving a dangling "Check an example file:" title.
AUTO_HIDE_SCRIPT = """    <script type="text/javascript">
        window.addEventListener ('load', () => {
            let formats = document.querySelector ('.intro_formats');
            if (formats !== null && formats.querySelector ('.intro_file_formats a') === null) {
                formats.parentNode.removeChild (formats);
            }
        });
    </script>
"""


def rewrite_example_links(text):
    """Drop the start page links whose model files are not shipped."""
    def replace(match):
        indent, urls, label = match.group(1), match.group(2), match.group(3)
        if label in MODEL_ALIASES:
            urls = MODEL_ALIASES[label]
        for url in [u.strip() for u in urls.split(',') if u.strip()]:
            if os.path.dirname(url).replace('\\', '/') != MODELS_REL:
                continue
            if os.path.basename(url) not in KEEP_MODELS:
                return ''
        return '%s<a href="#model=%s">%s</a>\n' % (indent, urls, label)
    return EXAMPLE_LINK_RE.sub(replace, text)


def patch_html(relpath, text):
    """Apply the packaging patch to one HTML entry point."""
    # The canonical URLs of the public website would tell a search engine to
    # index the upstream site instead of this appliance, and are wrong here.
    text = CANONICAL_RE.sub('', text)
    if relpath == 'index.html':
        text = TITLE_RE.sub('<title>CAD Viewer</title>', text, count=1)
        text = rewrite_example_links(text)
        text = text.replace('</body>', AUTO_HIDE_SCRIPT + '</body>')
    elif relpath == 'embed.html':
        text = TITLE_RE.sub('<title>CAD Viewer</title>', text, count=1)
        text = text.replace(
            'href="https://3dviewer.net" target="_blank" title="Open in 3dviewer.net"',
            'href="index.html" target="_blank" title="Open in CAD Viewer"')
    elif relpath.startswith('info/'):
        text = TITLE_RE.sub('<title>CAD Viewer - Documentation</title>', text, count=1)
        text = text.replace('https://3dviewer.net', 'https://github.com/kovacsv/Online3DViewer')
        text = text.replace('3dviewer.net', 'Online 3D Viewer')
    return text


# The sharing dialog builds links to the public 3dviewer.net website. That
# website cannot reach a model stored on the user's NAS, so the link is dead
# on an appliance. Point it at this installation instead. Both replacements
# are exact matches on the minified bundle and therefore fail loudly when an
# upstream update changes the code, instead of silently shipping dead links.
SHARE_LINK_MARKER = '"https://3dviewer.net/#"'
JS_PATCHES = (
    (SHARE_LINK_MARKER, 'location.origin+location.pathname+"#"'),
    ('https://3dviewer.net/embed.html#', "'+location.origin+location.pathname+'embed.html#"),
)


def patch_js(relpath, text):
    if SHARE_LINK_MARKER not in text:
        return text
    for old, new in JS_PATCHES:
        if old not in text:
            raise SystemExit('error: %s: patch target not found: %s' % (relpath, old))
        text = text.replace(old, new)
    return text


def iter_entries(stage):
    """Yield (relpath, absolute path, is_dir) in a stable order."""
    for root, dirs, files in os.walk(stage):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d != '__pycache__')
        rel_root = os.path.relpath(root, stage).replace('\\', '/')
        rel_root = '' if rel_root == '.' else rel_root
        if rel_root:
            yield rel_root, root, True
        for name in sorted(files):
            if name.startswith('.'):
                continue
            rel = '%s/%s' % (rel_root, name) if rel_root else name
            yield rel, os.path.join(root, name), False


def is_dropped(relpath):
    if relpath.startswith(MODELS_REL + '/'):
        return os.path.basename(relpath) not in KEEP_MODELS
    return False


def read_text(path):
    with open(path, 'rb') as handle:
        raw = handle.read()
    return raw.replace(b'\r\n', b'\n').decode('utf-8')


def build_archive(stage, out_path, epoch):
    kept = dropped = 0
    raw_bytes = 0
    def add_file(tar, relpath, data):
        nonlocal kept, raw_bytes
        info = tarfile.TarInfo('./' + relpath)
        info.mtime = epoch
        info.uid = info.gid = 0
        info.uname = info.gname = 'root'
        info.type = tarfile.REGTYPE
        info.mode = 0o644
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        kept += 1
        raw_bytes += len(data)

    with tarfile.open(out_path, 'w:bz2', format=tarfile.GNU_FORMAT) as tar:
        for relpath, full_path, is_dir in iter_entries(stage):
            if is_dropped(relpath):
                dropped += 1
                continue
            if is_dir:
                info = tarfile.TarInfo('./' + relpath)
                info.mtime = epoch
                info.uid = info.gid = 0
                info.uname = info.gname = 'root'
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
                continue
            if relpath.endswith('.html'):
                data = patch_html(relpath, read_text(full_path)).encode('utf-8')
            elif relpath.endswith('.js'):
                data = patch_js(relpath, read_text(full_path)).encode('utf-8')
            else:
                with open(full_path, 'rb') as handle:
                    data = handle.read()
                if relpath.endswith(TEXT_SUFFIXES):
                    data = data.replace(b'\r\n', b'\n')
            add_file(tar, relpath, data)
        add_file(tar, SUBSET_NOTE_PATH, SUBSET_NOTE.encode('utf-8'))
    return kept, dropped, raw_bytes


DEFAULT_EPOCH = 1704067200  # 2024-01-01T00:00:00Z


def main():
    parser = argparse.ArgumentParser(description='Build webui.bz2 for the CAD Viewer TOS 7 package.')
    parser.add_argument('--stage', required=True, help='staged frontend directory')
    parser.add_argument('--out', default='webui.bz2', help='output archive (default: webui.bz2)')
    parser.add_argument('--epoch', type=int, default=DEFAULT_EPOCH,
                        help='mtime stored for every entry; a fixed value keeps the build reproducible')
    args = parser.parse_args()

    stage = os.path.abspath(args.stage)
    if not os.path.isfile(os.path.join(stage, 'index.html')):
        raise SystemExit('error: %s does not look like a staged frontend (no index.html)' % stage)
    if not os.path.isdir(os.path.join(stage, 'assets', 'externallibs')):
        raise SystemExit('error: %s has no assets/externallibs, run tools/build_frontend.py first' % stage)

    out_path = os.path.abspath(args.out)
    kept, dropped, raw_bytes = build_archive(stage, out_path, args.epoch)
    size = os.path.getsize(out_path)

    print('stage    : %s' % stage)
    print('output   : %s' % out_path)
    print('files    : %d kept, %d demo models dropped' % (kept, dropped))
    print('payload  : %.1f MB uncompressed, %.1f MB in the archive' % (raw_bytes / 1048576.0, size / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
