# NAS file import for CAD Viewer

Status: approved by the product owner on 2026-09-23. Implementation follows.

## Problem

The viewer's toolbar opens the browser's native file dialog, so a model that
already lives on the TNAS has to be downloaded to the client and uploaded
again. The file is already on the device the application runs on.

The TOS 7 desktop ships exactly the control that is wanted: `x-upload-file`
renders the "local / from TNAS" pair and its TNAS branch opens `x-path-select`,
the platform's directory tree. Neither is available to a third-party
application:

- Both are global components of the TOS desktop SPA
  (`/usr/www/tos/js/global-comp-x-upload-file-vue.*.js`).
- The guide mentions "the file picker component" once
  (`08_Deb_Development.md:22`) and documents no API, no component name and no
  example.
- This application opens externally (`open_path = true`) on
  `http://<ip>:8686`, a different origin from the desktop, so the components
  are unreachable from its JavaScript. An iframe-mode application could only
  reach them through `window.parent`, which is unsupported and version fragile.

The application therefore provides its own NAS browser, and the platform gap is
recorded as a finding instead of being worked around silently.

## Scope

In scope: a two-item menu on the toolbar's open button, and a NAS browse and
import flow backed by the application's own service.

Out of scope: writing to the NAS, multi-select, upload in the other direction,
and the platform component itself.

## Design

### Menu

The toolbar's first button (`Open from your device`) calls
`OpenFileBrowserDialog()`. A capturing click listener replaces that with a
menu:

- `Import from this computer` -> `website.OpenFileBrowserDialog()`
- `Import from the NAS` -> the NAS browser dialog

### Backend API

Served by the service itself, same origin as the page, so there is no CORS
involved.

| Route | Purpose |
| --- | --- |
| `GET /api/fs/roots` | the browsable roots |
| `GET /api/fs/list?path=<abs>` | one directory level |
| `GET /api/fs/open/<share path>` | the file bytes |

`/api/fs/open` is path style, not query style, because the viewer derives the
file name and the extension by stripping everything after `?`
(`source/engine/io/fileutils.js:21`), which would leave the importer without an
extension.

The share path goes in as readable segments without its leading separator
(`/api/fs/open/Volume1/public/model.stp`), each segment percent-encoded on its
own. Two reasons, both from the viewer reading the URL as a file location:
percent-encoding the whole path makes the window title read
`%2FVolume1%2Fpublic%2Fmodel.stp`, and it moves the file's directory to the
route itself, so the sidecar files an OBJ or glTF import asks for (`.mtl`,
textures) resolve to the wrong place. A leading separator is optional; the
server restores it.

The frontend hands the URL to `website.LoadModelFromUrlList([url], settings)`,
the same code path the intro example links use, with the import settings the
website builds for its own hash based loads. Without that second argument the
loader throws on an undefined default colour before it starts. The file is
streamed from disk, so a 500 MB STEP model is never copied.

### Browsable roots

Discovered at request time: every `/VolumeN` directory, minus the entries that
start with `@` (platform internals such as `@apps`, `@system`, `@cache`) or `#`
(`#recycle`). What is left is the shared folders.

`/home` is deliberately not a root: the service runs with `ProtectHome=true`
and cannot read it anyway.

### Guard rails

- Every path is `realpath`-resolved and must sit under an allowed root, which
  also defeats `..` and symlink escapes.
- Directory listings hide dotfiles and `@` / `#` entries.
- `/api/fs/open` only serves extensions the viewer can import, plus the
  sidecars an OBJ or glTF import needs (`.mtl`, textures, `.zip`).
- Requests whose `Sec-Fetch-Site` is `cross-site` are refused, so a page on
  another site cannot use the user's browser to read the NAS.
- The site sets a session cookie when the page is loaded and `/api/fs/*`
  requires it.

### Response caching

Every file in the installed tree carries the same timestamp, pinned by the build
so that two runs produce the same archive. `Last-Modified` therefore cannot
tell one release from the next, and a client that revalidates after an upgrade
gets `304` and keeps running the previous bundle - observed on the device as a
"new service, old page" pair where the new frontend entry point was `undefined`.

Responses carry a release scoped `ETag` (`"<version>-<path>-<size>"`) and every
path is `no-cache`, so each load revalidates and an upgrade always wins.
Hashing the payload instead would mean reading the 7.7 MB OpenCascade build on
every request.

The build also stamps every local `script` and `stylesheet` reference in
`index.html` with its own content digest (`?v=<sha1>`). Upstream tags its two
bundles with the release number it was built from, which does not move when this
repository rebuilds them, and the bundles pull in more scripts at run time under
names nothing can tag by hand. The digest is what makes a rebuilt release a new
URL, and it is also what evicts entries an older release left behind with a
`max-age` of a day.

### Residual risk, and why it is a platform finding

The service has no way to authenticate a user. In external-open mode the
platform does not route the application through its nginx - this application
has no snippet in `/etc/nginx/conf.d/`, unlike the iframe-mode applications -
so no `X-Csrf-Token` and no session cookie is injected, and the browser talks
to port 8686 directly.

Anyone who can reach that port on the LAN can obtain the session cookie by
loading the page and then read the shared folders through the API. The controls
above stop cross-site attacks and naive scanning; they cannot stop an attacker
who can already reach the port.

The platform's own manual-install wizard is the counter-example: it is served
by the authenticated desktop, so it gets both the picker and the checks for
free. A third-party application that needs to read NAS files has no equivalent,
so it must either stay unauthenticated or not offer the feature.

## Verification

- Rebuild, `verify_deb.py`, install on the TNAS.
- Browse to a shared folder, open a `.stp` from the NAS, confirm the mesh loads.
- Confirm `/etc`, `/Volume1/@apps` and `/home` are refused.
- Confirm a cross-site request is refused.
