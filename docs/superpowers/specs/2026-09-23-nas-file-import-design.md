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

The application therefore provides its own NAS browser. What it browses with is
the platform's file service (the one the desktop file manager talks to,
`/v2/fileManage/*` -> `/var/api/file-manage.sock`), so the folders a user sees
and the files a user may open follow that user's own permissions; the picker
*component* stays out of reach and is recorded as a finding.

## Scope

In scope: a two-item menu on the toolbar's open button, and a NAS browse and
import flow served by the application's own service but answered by the
platform's file service under the session of the user who is looking at the
page.

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
involved. Every route is a thin proxy: the service adds the caller's cookies to
the platform's file service call (`/v2/fileManage/homeList`,
`/v2/fileManage/list`, `/v2/fileManage/fileDownload`) and passes the answer back
in the shape below. It never touches the filesystem, so the application
account's own rights never widen what the browser offers.

The platform answers that route on the desktop's web server, which proxies it to
`/var/api/file-manage.sock`. The socket cannot be used directly from here: on
TOS 7 `/var/api` is a symlink into `/tmp` and this unit runs with
`PrivateTmp=true`, so the socket does not exist in the unit's namespace.
`FILE_SERVICE_URL` overrides the address if a device ever differs; it defaults
to `http://127.0.0.1:8181`.

| Route | Purpose |
| --- | --- |
| `GET /api/fs/roots` | the roots of this user: the shares plus the personal folder |
| `GET /api/fs/list?path=<abs>` | one directory level |
| `GET /api/fs/open/<share path>` | the file bytes, streamed from the platform's answer |

The platform wants its anti-forgery cookie back in an `X-Csrf-Token` header on
the two listing calls; the browser holds that cookie as well, so the service
reads it out of the `Cookie` header and passes both on. The download call needs
no header, and is the one the viewer itself fetches - which is why the model
URLs stay path shaped, see below.

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

Whatever the platform's file service answers to `homeList` for this session:
the shared folders this user may open, plus that user's personal folder. A
share the user has no permission on is not in the answer and therefore cannot
be offered; neither can `/home` of another account, `/Volume1/@apps` or any
other path the desktop file manager hides from that user.

Hidden entries (`@apps`, `#recycle`, dotfiles) are filtered out of the listing
as well. The parent of a root is never offered as "up": `/`, `/home` and the
volume roots are container levels, not folders the user may open.

### Guard rails

- Path resolution, permission and identity belong to the platform's file
  service; the application asks and passes the answer on.
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

### What this says about the platform

The application serves the page through the platform's own nginx snippet
(1.1.5 and later), so the browser holds the platform session cookies and the
file service can authenticate the user from them. What the guide still does not
describe is any of this: `10_Permission_Model.md` describes granting the
*application account* access to shared folders, and never says that a
third-party application can ask the *platform* for the files of the user who is
looking at it. The route, the socket, the `X-Csrf-Token` requirement and the
`homeList` / `list` / `fileDownload` parameter names were all found by reading
the desktop's own JavaScript and the device. The picker component itself remains
unreachable, which is what this application works around.

Anyone who can reach the bare port can still load the viewer, but no longer the
shares: the file service refuses a request without a session.

## Verification

- Rebuild, `verify_deb.py`, install on the TNAS.
- Browse to a shared folder, open a `.stp` from the NAS, confirm the mesh loads.
- Sign in as an ordinary user, open the application and confirm the browser
  offers only that user's folders; open a model from that user's own folder.
- Confirm a folder the user has no permission on is not offered, and that
  fetching it directly through `/api/fs/open/...` is refused by the platform.
- Confirm a cross-site request is refused.
