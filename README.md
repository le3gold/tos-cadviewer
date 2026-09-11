# CAD Viewer — a TOS 7 Deb application

A TOS 7 Deb application that serves the Online 3D Viewer frontend from the TNAS
so that 3D models and CAD files can be inspected in a browser, entirely offline.

Packaging type: **Deb, single-package mode, WebUI External Open.**

## Repository layout

```
cadviewer/
├── config.ini                 # TOS application metadata
├── cadviewer.lang             # 14-language store listing text
├── cadviewer.env              # Environment variables for the systemd unit
├── bin/cadviewer              # Backend: Python 3 static file server
├── images/icons/cadviewer.svg # App icon (SVG, transparent background)
├── init.d/cadviewer.service   # systemd unit
├── nginx/cadviewer.conf       # nginx location block (external open)
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
python tools/verify_deb.py build/cadviewer_x86_64.deb
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
  `nginx/cadviewer.conf` are present.
- No text file ships with CRLF line endings.
- The publisher placeholders are gone (unless `--allow-placeholders` is given
  for a local test build).

`tools/verify_deb.py` re-reads the finished package independently: it checks
the `ar` member order, the `2.0` version marker, the control fields, the
per-file modes, the `md5sums` manifest, and that `webui.bz2` still contains a
loadable `index.html` and the OCCT WebAssembly decoder.

## Before submitting

- [ ] Replace `YOUR-ORG/YOUR-REPO` in `config.ini` and `DEBIAN/control` with the
      public repository that will host the Release assets.
- [ ] Confirm the publisher name in `config.ini`, `cadviewer.lang` and
      `DEBIAN/control`.
- [ ] Create the public repository, attach `cadviewer_x86_64.deb` and its
      `.sha256` as Release assets, and tag the Release `1.0.0` (must equal
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
with it and it matches the `open_path: true` example. `nginx/cadviewer.conf`
is shipped as well, so the nginx route works too. If the review team prefers
`"/cadviewer/"`, that one line in `config.ini` is the only change needed.

Related, a smaller question: the permission model (10.4) names `site/` as the
runtime directory for Web UI files, while the package structure (8.3.2) and the
lifecycle scripts only speak of `webui.bz2`. This package extracts the frontend
into `<app_dir>/webui/`, which is where `cadviewer.env` and `bin/cadviewer`
expect it. Renaming it to `site/` is a one-line change in those three files.

## Runtime layout on the TNAS

| Path | Purpose |
| --- | --- |
| `/usr/local/cadviewer/` | Install directory (read-only at runtime) |
| `/usr/local/cadviewer/webui/` | Frontend, extracted from `webui.bz2` at install time |
| `/var/lib/cadviewer/` | Application runtime state |
| `/var/log/cadviewer/` | Application logs |
| TCP 8686 | Backend HTTP port (see `important` in `cadviewer.lang`) |

`webui.bz2` is flat: `index.html` sits at the root of the archive, which is how
the guide builds it (`tar -cjf webui.bz2 -C webui/ .`). `postinst` extracts it
into `webui/` and `bin/cadviewer` serves it from there.

The service runs as the unprivileged system user `cadviewer`, with
`ProtectSystem=strict`, `NoNewPrivileges=true` and no privileged mode.
