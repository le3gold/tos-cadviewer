# CAD Viewer — a TOS 7 Deb application

A TOS 7 Deb application that serves the Online 3D Viewer frontend from the TNAS
so that 3D models and CAD files can be inspected in a browser, entirely offline.

Packaging type: **Deb, single-package mode, WebUI External Open.**

## Repository layout

```
le3gold-cadviewer/
├── config.ini                 # TOS application metadata
├── PRIVACY.md                 # Privacy policy (review item C3)
├── le3gold-cadviewer.lang             # 14-language store listing text
├── le3gold-cadviewer.env              # Environment variables for the systemd unit
├── bin/le3gold-cadviewer              # Backend: Python 3 static file server
├── images/icons/le3gold-cadviewer.svg # App icon: the upstream project's logo
├── init.d/le3gold-cadviewer.service   # systemd unit
├── nginx/le3gold-cadviewer.conf       # nginx location block (external open)
├── licenses/                  # Upstream and third-party license texts
│   └── NOTICE.md              # Attribution and list of modifications
├── DEBIAN/                    # control + lifecycle scripts
├── webui/                     # Source of the files this repository adds to the frontend
│   ├── nas-import.js          # "Import from the NAS" menu, browser and dialog
│   └── nas-import.css
├── docs/superpowers/specs/    # Design notes, including the file API and its guards
├── webui.bz2                  # Frontend bundle (generated, not in git)
├── build/                     # Build output (generated, not in git)
└── tools/
    ├── build_frontend.py      # Builds the frontend from pinned upstream source
    ├── make_webui.py          # Packs the staged frontend into webui.bz2
    ├── build_deb.py           # Builds the .deb without dpkg-deb
    └── verify_deb.py          # Inspects a built .deb
```

## Requirements

- Python 3.8+ to build the package (the target system runs Python 3.10)
- git, Node.js and npm, plus network access, only when rebuilding the frontend

`dpkg-deb` is **not** required: `tools/build_deb.py` writes the `ar` archive
directly, so the package can be built on Windows, macOS or Linux.

## Build

```bash
# 1. Rebuild the frontend from upstream. Needs network; skip this step when a
#    staged frontend already exists.
python tools/build_frontend.py --work-dir D:/work/_vendor --stage D:/work/_vendor/webui_stage

# 2. Pack the staged frontend into webui.bz2.
python tools/make_webui.py --stage D:/work/_vendor/webui_stage --out webui.bz2

# 3. Build and check the package.
python tools/build_deb.py
python tools/verify_deb.py build/le3gold-cadviewer_1.1.5_x86_64.deb
```

### Release asset naming

`tools/build_deb.py` writes `<appid>_<version>_<platform>.deb` and a matching
`.sha256`. The versioned form is what the guide itself produces everywhere it
shows a command - quick start (03:52), lintian (06:193), local testing (13:28),
the CI recipe (14:58) and the official template's `build.sh` - while
`15_Publishing_Process.md:39` states that the version must *not* appear in the
file name and 15:59 says non-compliant names are rejected automatically. Both
cannot be right; the builder follows the majority reading and the version is
also carried by the Release tag, so switching back is a one-line change in
`tools/build_deb.py`.

`tools/build_frontend.py` pins the upstream commit, the esbuild options and the
version of every library vendored into the bundle, so the same inputs produce
the same frontend. `tools/make_webui.py` writes a deterministic archive
(sorted entries, fixed timestamps, uid/gid 0) and `tools/build_deb.py` uses a
fixed timestamp as well, so rebuilding the same sources yields a byte-identical
`.deb` — which is what makes the published SHA-256 meaningful.

### What `build_deb.py` checks before it writes anything

- `config.ini` parses as JSON and carries every field the guide requires.
- `id`, `version`, `package`, `system_id` and `user` agree with
  `DEBIAN/control` and `init.d/<system_id>.service`.
- `open_path` and `type` are not both set, and `path` is the portal route
  `/<appid>/` that `nginx/<appid>.conf` serves.
- The icon exists at the path `config.ini` names, and `webui.bz2` and
  `nginx/le3gold-cadviewer.conf` are present.
- No text file ships with CRLF line endings.
- The publisher placeholders are gone (unless `--allow-placeholders` is given
  for a local test build).

`tools/verify_deb.py` re-reads the finished package independently: it checks
the `ar` member order, the `2.0` version marker, the control fields, the
per-file modes, the `md5sums` manifest, and that `webui.bz2` still contains a
loadable `index.html` and the OCCT WebAssembly decoder.

## Before submitting

- [x] `config.ini` (`help`, `official`) and `DEBIAN/control` (`Homepage`) point at
      `le3gold/tos-cadviewer`, the public repository that hosts the Release assets.
- [x] Attribution is split the way it should be for a repackaged open source
      application: `auth` in `le3gold-cadviewer.lang` (the field the App Center
      shows as the developer) names the upstream author, `Viktor Kovacs`; the
      `publisher` in `config.ini` and the `Maintainer` in `DEBIAN/control` name
      the packager, `lee3gold`. Neither may carry the platform vendor's name: an
      application shipped with `auth = "TerraMaster"` is credited to TerraMaster
      instead of to its author.
- [x] `PRIVACY.md` is published and `config.ini` `help` links to it, so the
      privacy policy has a public URL (review items C3, C7 and C8).
- [ ] Create the public repository, attach `le3gold-cadviewer_<version>_x86_64.deb`
      and its `.sha256` as Release assets, and tag the Release with the same
      string as `config.ini.version` / `DEBIAN/control` `Version`.
- [ ] Verify TCP port 17868 does not conflict with an application that is
      already listed in the TOS App Center.
- [ ] Run `bash -n DEBIAN/postinst DEBIAN/prerm DEBIAN/postrm` on a Linux host.
- [ ] Test install/uninstall with `dpkg -i` and `dpkg --purge`.
- [ ] Confirm the service runs as its own account: `systemctl show -p User -p
      Group <appid>` and `ps -eo user,args | grep <appid>`.

## Importing a model that already lives on the NAS

The toolbar's import button offers two entries: **Import from this computer**,
which is upstream's own file dialog, and **Import from the NAS**, which opens a
browser for the shared folders. A model picked there is streamed straight from
disk into the viewer - nothing is copied and no temporary file is created, which
is what makes a multi-hundred-megabyte STEP file practical.

The platform has a NAS file picker of its own (the one the App Center install
wizard uses), but it is a component of the desktop page and an externally opened
application is a different origin, so an application in this mode cannot reach
it. The backend therefore serves a small file API of its own:

| Route | Purpose |
| --- | --- |
| `GET /api/fs/roots` | the shared folders, grouped by volume |
| `GET /api/fs/list?path=<abs>` | one directory level |
| `GET /api/fs/open/<share path>` | the file bytes, streamed |

Scope and guards, in short: only the first level under each `/VolumeN` is
exposed - never a volume root, never `@apps` - every path is `realpath`
resolved and must stay under an allowed root (which also defeats `..` and
symlinks), only extensions the viewer can import are served, cross-site requests
are refused, the page hands out a session cookie the API requires, and directory
listings are off. The residual risk is honest and unchanged by the guards: in
external-open mode the platform provides no authentication for the port, so
anyone who can reach it on the LAN can load the page and browse the shares.

Responses carry a release scoped `ETag` and are `no-cache`, and the build
stamps every local script and stylesheet reference in `index.html` with its own
content digest. The installed tree carries a pinned timestamp, so
`Last-Modified` cannot tell one release from the next; without those two
measures a browser keeps the previous frontend after an upgrade.

`docs/superpowers/specs/2026-09-23-nas-file-import-design.md` has the full
design, including why the file URL is path shaped and why its segments are
encoded one by one.

## Why `path` is the portal route

Version 1.1.4 shipped `"path": "http://${ip}:8686"` and the store review
rejected it (item C21). The guide does contain that value: the field reference
(8.4.2), the minimal configuration (8.3.2) and Template 2 (8.4.1) all show it.
But the "path field value quick reference" table at the end of 8.4.3, and the
two core requirements printed directly above the templates, both say `path` must
correspond to the nginx route. On the device only the route reading works end to
end: with `http://${ip}:8686` the platform never publishes
`/etc/nginx/conf.d/<appid>.conf`, so the application is reachable only on its
bare port, which the guide forbids pointing `path` at.

The package therefore ships three files that have to agree, and a mismatch in
any one of them breaks the route:

| File | Field |
| --- | --- |
| `config.ini` | `"path": "/le3gold-cadviewer/"` |
| `nginx/le3gold-cadviewer.conf` | `location /le3gold-cadviewer/` |
| `le3gold-cadviewer.env` | `URL_PREFIX=/le3gold-cadviewer` |

The platform does not load the snippet out of `/usr/local/<appid>/nginx/` on its
own. Guide 8.3.2 implies that it does ("the platform Nginx `include` directive
loads configurations in alphabetical order"), the official `postrm` template
deletes `/etc/nginx/conf.d/<appid>.conf`, and every route that actually exists on
the device has a file or a symlink there. `postinst` copies the snippet in and
`prerm` removes it.

The third question is about attribution, and it is the one that cannot be worked
around at runtime. The guide describes both fields as the name shown in the App
Center:

- 8.5.3 says `auth` in the `.lang` file is the "Developer/organization name";
- 8.4.2 says `publisher` in `config.ini` is "the developer or organization name
  displayed in the App Center", and 11.2 repeats that `publisher` "is displayed
  to users".

On TOS 7.0.1201 they are two different fields in the App Center UI: the `.lang`
`auth` value is rendered as the **Developer** line, and the `config.ini`
`publisher` value is rendered as the **Publisher** line. This was verified by
installing both 1.0.2 (`auth = "TerraMaster"`, `publisher = "le3gold"`) and 1.0.3
(`auth = "Viktor Kovacs"`, `publisher = "le3gold"`) on the same device: the
Developer line followed `auth` in both cases, the Publisher line followed
`publisher` in both cases.

For a repackaged open source application that distinction matters, because the
Developer line is the one readers and upstream maintainers look at. This package
therefore credits the upstream author through `auth` and the packager through
`publisher` and the `DEBIAN/control` `Maintainer`. If the guide really does
intend `publisher` to be the Developer line, then the documentation and the
7.0.1201 UI disagree, and one of them should be corrected before the next
application copies this pattern.

## Runtime layout on the TNAS

| Path | Purpose |
| --- | --- |
| `/usr/local/le3gold-cadviewer/` | Install directory, a symlink into `/Volume*/@apps/` |
| `/var/lib/le3gold-cadviewer/runtime/` | What the service actually executes: `bin/` plus the extracted frontend |
| `/var/lib/le3gold-cadviewer/runtime/webui/` | Frontend, extracted from `webui.bz2` at install time |
| `/var/lib/le3gold-cadviewer/install.log` | Lifecycle-script log, for when the `dpkg -i` output is gone |
| `/Volume1/CADViewer/` | The application shared folder. **Never deleted**, not even on purge |
| `/etc/nginx/conf.d/le3gold-cadviewer.conf` | Portal route, installed by `postinst` |
| `/var/log/le3gold-cadviewer/` | **Not used.** `/var/log` is a symlink to the tmpfs `/tmp/log`, so anything written there is erased at every reboot. Logs go to the journal instead |
| TCP 17868 | Backend HTTP port (see `important` in `le3gold-cadviewer.lang`) |

`webui.bz2` is flat: `index.html` sits at the root of the archive, which is how
the guide builds it (`tar -cjf webui.bz2 -C webui/ .`). `postinst` extracts it
into `runtime/webui/` and `bin/le3gold-cadviewer` serves it from there.

## Running as a non-root account (review item V1)

The guide marks `User=<appid>` and `Group=<appid>` as required (8.13.2), and
running as root is an automatic rejection (10.9), so review item V1 rejects a
package whose service runs as root. Version 1.1.4 ran as root, because on TOS 7
an unprivileged account could not read a single one of its own files:

- `/Volume*` is mounted with `tmacl`, a rich ACL that is deny-by-default at
  every level and does not fall back to the POSIX mode bits. Measured on TOS
  7.0.1201, an account with no entry on a directory is refused even when that
  directory is mode 755, and `tmacltool get-perm /Volume1 <uid>` reports
  `max_permission: -------------`.
- `/usr/local/<appid>` is a symlink into `/Volume1/@apps/<appid>`, so the install
  tree inherits that. The service account cannot read its own `bin/<appid>`.
- The platform creates the user named by `config.ini` `user` but no group of the
  same name, and the official unit template asks for `Group=<appid>`, which
  systemd refuses with `216/GROUP`.

The fix is to run from outside the volume. `postinst` stages the executable, the
environment file and the extracted frontend into `/var/lib/<appid>/`, which is on
the system volume and therefore not under `tmacl`, owns that tree to the account,
and creates the missing group. The unit executes that copy. The package also
grants the account traversal (`r-x`) on each volume root and read-write on its own
shared folder, which is the minimum needed to reach a shared folder the
administrator has opened to it.

Verified on TOS 7.0.1201, both as an upgrade and as a clean install:

```
$ ps -eo user,args | grep le3gold-cadviewer
le3gold+  ...  /usr/bin/python3 /var/lib/le3gold-cadviewer/runtime/bin/le3gold-cadviewer
$ systemctl show -p User -p Group le3gold-cadviewer
User=le3gold-cadviewer
Group=le3gold-cadviewer
```

Logs go to the journal (`journalctl -u le3gold-cadviewer`), never to
`/var/log/<appid>`.

## Privacy

`PRIVACY.md` is the full policy, and `config.ini` `help` links to it so the store
listing has a public URL (review items C3, C7 and C8). In short: the application
makes no outbound network connection, bundles no analytics and calls no
third-party service. The only network traffic is the HTTP request the browser
makes to the TNAS itself, and the only files it reads are the shared folders the
administrator has opened.
