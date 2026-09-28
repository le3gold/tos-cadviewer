# CAD Viewer - Privacy Policy

Applies to the TerraMaster TOS application **CAD Viewer** (app ID
`le3gold-cadviewer`), packaged by **lee3gold** from the open-source project
Online 3D Viewer by Viktor Kovacs.

Last updated: 2026-09-28

## Summary

CAD Viewer has no account system, no telemetry, no analytics and no cloud
component. It does not collect, transmit or store personal data. Every model
file it opens is parsed on the TNAS itself.

## What the application handles

| Data | Where it lives | Why |
|---|---|---|
| Model files you open (STEP, IGES, IFC, STL, glTF, OBJ, ...) | The shared folder or device you opened them from | They are the document being displayed |
| The same files' contents | Memory, for as long as the page is open | Parsing and rendering happen in the browser |

Nothing is uploaded. The application makes **no outbound network connections**
at any point: the viewer, its parsers and every asset it loads are served by
the application itself from the TNAS.

## Third-party services and APIs

**None.** The application calls no third-party API, no remote endpoint and no
external CDN, and sends no data anywhere. There is therefore no data transfer
to any destination or region.

Two things are worth stating precisely, because they are the only network
traffic the application produces:

- It listens on one TCP port on the TNAS so that the TOS portal can serve its
  interface to your browser. That traffic stays between the browser and the
  TNAS.
- The open-source libraries it bundles (three.js, occt-import-js, web-ifc,
  rhino3dm, draco) are compiled into the package. None of them contacts a
  network.

## User data rights

The application keeps no personal data, so there is nothing for it to show,
correct or delete on your behalf. Concretely:

- **Access / correct**: the only files involved are the model files you chose
  to open. They are yours, they stay where you put them, and the application
  never modifies them.
- **Delete**: the application stores no copy of your files. To remove
  everything it did create, uninstall it from App Center - that deletes
  `/var/lib/le3gold-cadviewer` (its staged runtime and state) and its portal
  route. Files you placed in the application's shared folder
  (`/Volume*/CADViewer`) are **not** deleted, because they are your data; delete
  them yourself through File Manager if you want them gone. Uninstalling also
  removes the folder access rights the package granted the application account.
- **Requests and questions**: open an issue at
  <https://github.com/le3gold/tos-cadviewer/issues>, or use the contact address
  in the package's `Maintainer` field. This is also the channel for any
  privacy question or complaint.

## Permissions the application asks for

- A dedicated unprivileged system account (`le3gold-cadviewer`), which is
  required of every TOS 7 application. It runs with no capabilities and cannot
  write anywhere except its own state directory.
- Its own shared folder, `/Volume*/CADViewer`, so there is a place to put
  models that the application is guaranteed to be able to read.
- Read access to any other shared folder **only** if an administrator grants
  the application account access to it in TOS's shared folder settings. The
  application cannot grant itself access to your folders and does not try to.

## Changes

Any change to this policy is published in this file in the public repository,
before the version carrying it is submitted for review.

## Upstream

CAD Viewer is a packaging of Online 3D Viewer (MIT licence, Viktor Kovacs).
Attribution for the upstream project and every bundled library is in
`licenses/NOTICE.md`.
