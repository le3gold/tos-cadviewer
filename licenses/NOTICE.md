# NOTICE

CAD Viewer for TOS 7 is a packaging of **Online 3D Viewer** and of several
third-party libraries that the viewer loads at runtime.

## Upstream project

| Item | Value |
| --- | --- |
| Project | Online 3D Viewer |
| Author | Viktor Kovacs |
| Source | https://github.com/kovacsv/Online3DViewer |
| Version packaged | 0.19.0 |
| License | MIT (see LICENSE-Online3DViewer-MIT.md) |

The upstream copyright notice and the MIT license text are reproduced in full
in `LICENSE-Online3DViewer-MIT.md`, as required by the MIT license.

## Modifications made for this package

Online 3D Viewer 0.19.0 loads four optional format parsers from the public
jsDelivr CDN at runtime. A NAS is frequently deployed without internet access,
and jsDelivr is unreliable from mainland China, which made STEP / IGES / BREP /
IFC / 3DM viewing fail in exactly the scenario this app targets.

The following change was made to the upstream source
(`source/engine/import/importerutils.js`) before building the frontend:

1. Added `EXTERNAL_LIB_DIR` and `GetExternalLibBaseUrl()`.
2. Replaced the four hard-coded `https://cdn.jsdelivr.net/...` URLs with paths
   resolved against `assets/externallibs/` relative to the document base URL.
3. Vendored the four libraries into `assets/externallibs/` inside the frontend
   bundle (`webui.bz2`).

No functional behaviour other than the library origin was changed. The engine
and website bundles were produced by the upstream `esbuild` build scripts and
were not otherwise edited.

One further detail: the `draco3d` npm package no longer ships a browser build
of the decoder, so `draco_decoder.js` is taken from the copy bundled with
three.js, whose version is pinned by the upstream `package.json`. It is the
same Google Draco decoder that upstream intended to load.

### Sample models

The start page of the frontend links to one sample model per supported file
format. The upstream set is 17.6 MB and includes models that cannot be
redistributed in a published package: `DamagedHelmet.glb` is licensed
CC BY-NC, and the Mixamo assets `X_Bot.dae` and `Y_Bot.fbx` restrict
redistribution. Those three, plus two large but freely licensed samples, are
not shipped. What remains, and why, is listed inside the frontend bundle at
`assets/models/SHIPPED-SUBSET.md`.

## Bundled third-party libraries

| Library | Version | License | File(s) in webui | License text |
| --- | --- | --- | --- | --- |
| occt-import-js | 0.0.22 | LGPL-2.1 | assets/externallibs/occt-import-js.js, occt-import-js.wasm, occt-import-js-worker.js | LICENSE-occt-import-js-LGPL-2.1.txt |
| Open CASCADE Technology | (via occt-import-js) | LGPL-2.1 | (compiled into occt-import-js.wasm) | LICENSE-OpenCASCADE-LGPL-2.1.txt |
| web-ifc | 0.0.68 | MPL-2.0 | assets/externallibs/web-ifc-api-iife.js | LICENSE-web-ifc-MPL-2.0.txt |
| rhino3dm | 8.17.0 | MIT | assets/externallibs/rhino3dm.min.js | LICENSE-rhino3dm-MIT.txt |
| Draco decoder (JS build) | as shipped with three.js 0.176.0 | Apache-2.0 | assets/externallibs/draco_decoder.js | LICENSE-draco-Apache-2.0.txt |
| three.js | 0.176.0 | MIT | bundled into o3dv/o3dv.website.min.js | LICENSE-three.js-MIT.txt |

All six libraries are redistributed **unmodified**. The corresponding upstream
sources are published at:

- https://github.com/kovacsv/occt-import-js
- https://github.com/Open-Cascade-SAS/OCCT
- https://github.com/ThatOpen/engine_web-ifc
- https://github.com/mcneel/rhino3dm
- https://github.com/google/draco
- https://github.com/mrdoob/three.js

### Notes on the LGPL components

`occt-import-js` and Open CASCADE Technology are used under LGPL-2.1. In this
package they are shipped as separate, unmodified files that are loaded at
runtime by the browser, and they are not statically linked into any work
created by the publisher. The full license texts and the upstream source
locations are provided above and in this directory, as the LGPL requires.

### Notes on the MPL component

`web-ifc` is used under MPL-2.0 and is redistributed as an unmodified file.
Its source form is available at the upstream repository listed above.

## Branding

"Online 3D Viewer" and "3dviewer.net" are the upstream project's names and are
not used as the name of this application. This package is published under the
name "CAD Viewer". The upstream project name appears only in this NOTICE and in
the application description, for attribution. In the App Center listing the
"Developer" field names the upstream author and the "Publisher" field names the
author of the packaging; the credit that the MIT license requires also lives in
this file and in `LICENSE-Online3DViewer-MIT.md`, which ship inside the
package.

The application icon is the upstream project's own logo, taken unmodified from
`assets/images/3dviewer_net_logo.svg` in the pinned upstream source, so that
the installed application is recognisable as a build of Online 3D Viewer. The
logo is covered by the same MIT license as the rest of the project (see
`LICENSE-Online3DViewer-MIT.md`). The one adjustment is that upstream draws the
logo outline with a CSS variable (`--ov_logo_border_color`), which an icon file
cannot resolve, so the value that variable holds in the upstream light theme
(`#000000`) is written out instead.
