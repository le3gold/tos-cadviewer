# CAD Viewer — a TOS 7 Deb application

A TOS 7 Deb application that serves the Online 3D Viewer frontend from the TNAS
so that 3D models and CAD files can be inspected in a browser, entirely offline.

Packaging type: **Deb, single-package mode, WebUI External Open.**

## Repository layout

```
le3gold-cadviewer/
├── config.ini                 # TOS application metadata
├── le3gold-cadviewer.lang             # 14-language store listing text
├── le3gold-cadviewer.env              # Environment variables for the systemd unit
├── bin/le3gold-cadviewer              # Backend: Python 3 static file server
├── images/icons/le3gold-cadviewer.svg # App icon (SVG, transparent background)
├── init.d/le3gold-cadviewer.service   # systemd unit
├── nginx/le3gold-cadviewer.conf       # nginx location block (external open)
├── licenses/                  # Upstream and third-party license texts
│   └── NOTICE.md              # Attribution and list of modifications
├── DEBIAN/                    # control + lifecycle scripts
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
python tools/verify_deb.py build/le3gold-cadviewer_x86_64.deb
```

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
- `open_path` and `type` are not both set, and `path` uses `${ip}`.
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
- [ ] Confirm the publisher name in `config.ini`, `le3gold-cadviewer.lang` and
      `DEBIAN/control`.
- [ ] Create the public repository, attach `le3gold-cadviewer_x86_64.deb` and its
      `.sha256` as Release assets, and tag the Release `1.0.1` (must equal
      `config.ini.version` and `DEBIAN/control` `Version`).
- [ ] Verify TCP port 8686 does not conflict with an application that is
      already listed in the TOS App Center.
- [ ] Run `bash -n DEBIAN/postinst DEBIAN/prerm DEBIAN/postrm` on a Linux host.
- [ ] Test install/uninstall with `dpkg -i` and `dpkg --purge`.

## Open question for the review team

The guide gives two different values for `config.ini.path` in Deb WebUI
external-open mode:

- the field reference (8.4.2), the minimal configuration (8.3.2) and
  Template 2 (8.4.1) all use `http://${ip}:8686`, the backend port directly;
- the "path field value quick reference" table at the end of 8.4.3 uses
  `/<app_id>/`, the platform nginx route.

This package follows the first reading, because three of the four places agree
with it and it matches the `open_path: true` example. `nginx/le3gold-cadviewer.conf`
is shipped as well, so the nginx route works too. If the review team prefers
`"/le3gold-cadviewer/"`, that one line in `config.ini` is the only change needed.

Related, a smaller question: the permission model (10.4) names `site/` as the
runtime directory for Web UI files, while the package structure (8.3.2) and the
lifecycle scripts only speak of `webui.bz2`. This package extracts the frontend
into `<app_dir>/webui/`, which is where `le3gold-cadviewer.env` and `bin/le3gold-cadviewer`
expect it. Renaming it to `site/` is a one-line change in those three files.

## Runtime layout on the TNAS

| Path | Purpose |
| --- | --- |
| `/usr/local/le3gold-cadviewer/` | Install directory (read-only at runtime) |
| `/usr/local/le3gold-cadviewer/webui/` | Frontend, extracted from `webui.bz2` at install time |
| `/var/lib/le3gold-cadviewer/` | Application runtime state |
| `/var/log/le3gold-cadviewer/` | Application logs |
| TCP 8686 | Backend HTTP port (see `important` in `le3gold-cadviewer.lang`) |

`webui.bz2` is flat: `index.html` sits at the root of the archive, which is how
the guide builds it (`tar -cjf webui.bz2 -C webui/ .`). `postinst` extracts it
into `webui/` and `bin/le3gold-cadviewer` serves it from there.

The service runs as the unprivileged system user `le3gold-cadviewer`, with
`ProtectSystem=strict`, `NoNewPrivileges=true` and no privileged mode.
