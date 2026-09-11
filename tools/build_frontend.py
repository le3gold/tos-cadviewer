#!/usr/bin/env python3
"""Build the CAD Viewer web frontend from upstream Online 3D Viewer.

The package ships a prebuilt frontend, so this script only has to be run when
the upstream version is bumped or one of the patches changes. It is kept in
the repository so the bundle inside the .deb is reproducible from source.

What it does:

  1. clones kovacsv/Online3DViewer and checks out the pinned commit;
  2. rewrites the importers to load their payload libraries from the package
     instead of the jsDelivr CDN - a NAS is often offline, and jsDelivr is
     unreliable from mainland China, so a CDN dependency would leave the
     browser unable to open STEP, IGES, IFC or Rhino files;
  3. builds the engine and website bundles with the pinned esbuild;
  4. runs the upstream packaging script and copies the result into the stage
     directory consumed by tools/make_webui.py;
  5. vendors the four payload libraries at their pinned versions.

Requires: git, node/npm, and network access for the clone and the npm
packages. Everything else is pinned.

Usage:
    python tools/build_frontend.py --work-dir D:/work/_vendor --stage D:/work/_vendor/webui_stage
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile

UPSTREAM_REPO = 'https://github.com/kovacsv/Online3DViewer.git'
# Merge commit on main, the 0.19.0 development state. Update deliberately.
UPSTREAM_COMMIT = 'd025663dcdd101527e87971d9ae2cf16f02949b4'

# The viewer loads these at runtime. Upstream fetches them from
# cdn.jsdelivr.net; the package ships them instead. Version, path inside the
# npm tarball, and the file name the patched source expects.
EXTERNAL_LIBS = (
    ('occt-import-js', '0.0.22', 'package/dist/occt-import-js.js', 'occt-import-js.js'),
    ('occt-import-js', '0.0.22', 'package/dist/occt-import-js.wasm', 'occt-import-js.wasm'),
    ('occt-import-js', '0.0.22', 'package/dist/occt-import-js-worker.js', 'occt-import-js-worker.js'),
    ('rhino3dm', '8.17.0', 'package/rhino3dm.min.js', 'rhino3dm.min.js'),
    ('web-ifc', '0.0.68', 'package/web-ifc-api-iife.js', 'web-ifc-api-iife.js'),
    # draco3d's npm package ships no browser build of the decoder, so take
    # the self-contained JS build from three.js. A version of None means
    # "whatever the upstream package.json pins".
    ('three', None, 'package/examples/jsm/libs/draco/draco_decoder.js', 'draco_decoder.js'),
)

# Applied to source/engine/import/importerutils.js. Each pair is an exact
# match; the build fails if upstream has moved the code.
IMPORTER_ANCHOR = 'let occtWorkerUrl = null;\n'
SOURCE_EDITS = (
    (IMPORTER_ANCHOR,
     IMPORTER_ANCHOR
     + "\nconst EXTERNAL_LIB_DIR = 'assets/externallibs/';\n"
       "\n"
       "export function GetExternalLibBaseUrl ()\n"
       "{\n"
       "\treturn new URL (EXTERNAL_LIB_DIR, document.baseURI).href;\n"
       "}\n"),
    ("let baseUrl = 'https://cdn.jsdelivr.net/npm/occt-import-js@0.0.22/dist/';",
     'let baseUrl = GetExternalLibBaseUrl ();'),
    ("'https://cdn.jsdelivr.net/npm/rhino3dm@8.17.0/rhino3dm.min.js'",
     "GetExternalLibBaseUrl () + 'rhino3dm.min.js'"),
    ("'https://cdn.jsdelivr.net/npm/web-ifc@0.0.68/web-ifc-api-iife.js'",
     "GetExternalLibBaseUrl () + 'web-ifc-api-iife.js'"),
    ("'https://cdn.jsdelivr.net/npm/draco3d@1.5.7/draco_decoder_nodejs.min.js'",
     "GetExternalLibBaseUrl () + 'draco_decoder.js'"),
)
SOURCE_REL = os.path.join('source', 'engine', 'import', 'importerutils.js')

BUNDLES = (
    ('source/engine/main.js', 'build/engine/o3dv.min.js', ()),
    ('source/website/index.js', 'build/website/o3dv.website.min.js',
     ('--loader:.ttf=file', '--loader:.woff=file', '--loader:.svg=file')),
)


def tool(name):
    """Absolute path of an external command, with a clear error if missing."""
    path = shutil.which(name)
    if path is None:
        raise SystemExit('error: %s is required but was not found in PATH' % name)
    return path


def run(command, cwd=None):
    # npm and git are batch shims on Windows and cannot be spawned directly.
    if os.name == 'nt' and command[0].lower().endswith(('.cmd', '.bat')):
        command = [os.environ.get('COMSPEC', 'cmd.exe'), '/c'] + list(command)
    print('  $ %s' % ' '.join(command))
    subprocess.check_call(command, cwd=cwd)


def ensure_checkout(work_dir):
    root = os.path.join(work_dir, 'o3dv')
    git = tool('git')
    if os.path.isdir(os.path.join(root, '.git')):
        print('== reusing upstream checkout in %s' % root)
        run([git, 'fetch', '--tags', 'origin'], cwd=root)
    else:
        run([git, 'clone', UPSTREAM_REPO, root])
    # A forced checkout discards the patches of a previous run; they are
    # applied again below, so the result never depends on the checkout state.
    run([git, 'checkout', '--force', UPSTREAM_COMMIT], cwd=root)
    return root


def apply_source_edits(root):
    path = os.path.join(root, SOURCE_REL)
    with open(path, 'r', encoding='utf-8', newline='') as handle:
        # Normalise first: the checkout's core.autocrlf setting must not
        # decide whether the anchors below match.
        text = handle.read().replace('\r\n', '\n')
    for old, new in SOURCE_EDITS:
        if old not in text:
            raise SystemExit('error: %s no longer contains:\n%s\n'
                             'Upstream changed; update SOURCE_EDITS in %s.'
                             % (SOURCE_REL, old, os.path.basename(__file__)))
        text = text.replace(old, new, 1)
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(text)
    print('== patched %s to load libraries locally' % SOURCE_REL)


def build_bundles(root, skip_npm):
    npm = tool('npm')
    node = tool('node')
    modules = os.path.join(root, 'node_modules')
    if skip_npm and os.path.isdir(modules):
        print('== reusing node_modules')
    else:
        run([npm, 'install', '--no-audit', '--no-fund'], cwd=root)
    # main.js is a generated barrel file; it has to be regenerated so that
    # GetExternalLibBaseUrl is exported to the bundler.
    run([sys.executable, os.path.join('tools', 'update_engine_exports.py')], cwd=root)
    esbuild = os.path.join(modules, 'esbuild', 'bin', 'esbuild')
    for source, target, extra in BUNDLES:
        run([node, esbuild, source, '--bundle', '--minify', '--global-name=OV']
            + list(extra) + ['--outfile=' + target], cwd=root)
    run([sys.executable, os.path.join('tools', 'create_package.py')], cwd=root)
    return os.path.join(root, 'build', 'package', 'website')


def stage_frontend(website_dir, stage):
    if not os.path.isdir(website_dir):
        raise SystemExit('error: upstream build did not produce %s' % website_dir)
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    shutil.copytree(website_dir, stage)
    print('== staged frontend in %s' % stage)


def vendor_libraries(work_dir, stage, root):
    """Copy the pinned payload libraries out of their npm tarballs."""
    npm = tool('npm')
    target = os.path.join(stage, 'assets', 'externallibs')
    os.makedirs(target, exist_ok=True)
    cache = os.path.join(work_dir, 'npm-pack')
    os.makedirs(cache, exist_ok=True)
    with open(os.path.join(root, 'package.json'), 'r', encoding='utf-8') as handle:
        upstream_dependencies = json.load(handle)['dependencies']
    for package, version, member, name in EXTERNAL_LIBS:
        version = version or upstream_dependencies[package]
        tarball = os.path.join(cache, '%s-%s.tgz' % (package, version))
        if not os.path.isfile(tarball):
            run([npm, 'pack', '%s@%s' % (package, version), '--pack-destination', cache], cwd=work_dir)
        if not os.path.isfile(tarball):
            raise SystemExit('error: npm pack did not produce %s' % tarball)
        with tarfile.open(tarball, 'r:gz') as tar:
            handle = tar.extractfile(member)
            if handle is None:
                raise SystemExit('error: %s does not contain %s' % (tarball, member))
            data = handle.read()
        with open(os.path.join(target, name), 'wb') as out:
            out.write(data)
        print('  vendored %-26s %9d bytes' % (name, len(data)))


def main():
    parser = argparse.ArgumentParser(description='Build the CAD Viewer web frontend from upstream.')
    parser.add_argument('--work-dir', required=True,
                        help='directory holding (or receiving) the upstream clone and npm cache')
    parser.add_argument('--stage', required=True, help='stage directory to write the frontend into')
    parser.add_argument('--skip-npm', action='store_true', help='reuse node_modules from an earlier run')
    args = parser.parse_args()

    work_dir = os.path.abspath(args.work_dir)
    stage = os.path.abspath(args.stage)
    os.makedirs(work_dir, exist_ok=True)

    print('== upstream %s @ %s' % (UPSTREAM_REPO, UPSTREAM_COMMIT[:12]))
    root = ensure_checkout(work_dir)
    apply_source_edits(root)
    stage_frontend(build_bundles(root, args.skip_npm), stage)
    vendor_libraries(work_dir, stage, root)
    print('== %s is ready; run tools/make_webui.py --stage %s' % (stage, stage))
    return 0


if __name__ == '__main__':
    sys.exit(main())
