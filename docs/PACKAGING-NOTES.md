# Packaging notes — the measurements behind this package

This file is the evidence log for the non-obvious parts of `DEBIAN/postinst`,
`init.d/le3gold-cadviewer.service`, the nginx snippet and the runtime layout.
The README explains **what** the package does; this file records **why**, with
the commands and outputs that established it.

A generic, reusable version of this checklist is maintained separately by the
packager. This file stays specific to CAD Viewer so the implementation and the
evidence can be reviewed together.

## Test environment

| Item | Value |
| --- | --- |
| Device | TNAS F4-425 Plus |
| TOS | 7.0.1201 for the measurements below; 1.2.0 re-verified on 7.0.1278 |
| Application account | `le3gold-cadviewer` |
| Administrator | `test` |
| Normal user | `cadu` |
| Versions covered | 1.0.2 through 1.2.0 |

The application account is created by the platform from `config.ini` `user`.
The package must not create it.

## 1. `tmacl` denies an unprivileged account its own files

`/Volume*` is mounted with TerraMaster's rich ACL (`tmacl`). It is deny by
default at every directory level and does **not** fall back to the POSIX mode
bits. Measured on TOS 7.0.1201:

```sh
$ tmacltool get-perm /Volume1 $(id -u le3gold-cadviewer)
max_permission: -------------

$ su -s /bin/sh le3gold-cadviewer -c 'ls /Volume1/@apps'
ls: cannot open directory '/Volume1/@apps': Permission denied

$ su -s /bin/sh le3gold-cadviewer -c 'wc -c /usr/local/le3gold-cadviewer/bin/le3gold-cadviewer'
wc: /usr/local/le3gold-cadviewer/bin/le3gold-cadviewer: Permission denied
```

`/usr/local/le3gold-cadviewer` is a symlink into `/Volume1/@apps/`, so the whole
install tree inherits this. A directory being mode 755 does not help.

**Implementation:** `postinst` stages the executable, the environment file and
the extracted frontend into `/var/lib/le3gold-cadviewer/runtime/`, which lives on
the system volume and carries no `tmacl` entries. The unit executes that copy.

**Verification:** §6 below, and the `Runtime layout on the TNAS` table in the
README.

## 2. The platform runs `postinst` before it creates the account

Captured during the first install of a brand-new application:

```
19:13:05 application: CreateAppFolder: owner lookup failed, using root
19:13:06 systemd: le3gold-cadviewer.service: Failed to determine user credentials:
         No such file or directory                       (status=217/USER)
19:13:57 systemd: le3gold-cadviewer.service: Start request repeated too quickly.
19:14:22 platform creates the application account
```

Every `postinst` step that names the account — `chown`, `usermod`, `tmacltool`,
`install -o` — therefore fails on a first install, silently. With the default
systemd start limit (5 attempts in 60 s), the unit was already dead when the
account appeared. The application only came up because it was installed a second
time.

**Implementation:**

- `StartLimitIntervalSec=0` in the unit, so systemd keeps retrying.
- `ExecStartPre=-+/usr/lib/le3gold-cadviewer/runtime-fixup.sh` runs as root on
  every start and reapplies what `postinst` could not.
- `postinst` chooses `0750` when the account exists and `0755` when it does not,
  so the service can start either way.
- The fixup hook tightens the mode to `0750` once the tree is really owned by the
  account.

**Verification:** §6.1 and §6.2.

## 3. The platform creates the user but not a group of the same name

`config.ini` `user` makes the platform create the account, but its primary group
is `allusers` (997). A unit with `Group=le3gold-cadviewer` then dies with:

```
Failed to determine group credentials (status=216/GROUP)
```

**Implementation:** `postinst` creates the group only when it is absent:

```sh
getent group "$APPID" >/dev/null 2>&1 || groupadd "$APPID" 2>/dev/null || true
```

The guide says not to create users or groups, but it also requires
`Group=<appid>`. On this platform both cannot be true at once; the measured
resolution is to let the platform own the user and fill in the missing group.

**Verification:** `systemctl show -p User -p Group le3gold-cadviewer` reports
both as `le3gold-cadviewer`.

## 4. `/var/log` is a tmpfs, and `PrivateTmp=true` turns that into 226/NAMESPACE

On TOS 7:

```sh
$ ls -ld /var/log
lrwxrwxrwx 1 root root 8 ... /var/log -> /tmp/log/
$ mount | grep ' /tmp '
tmpfs on /tmp type tmpfs ...
```

A unit that combines `PrivateTmp=true` with
`ReadWritePaths=/var/log/le3gold-cadviewer` makes systemd resolve the path inside
the unit namespace, where it does not exist:

```
Failed to set up mount namespacing:
  /run/systemd/unit-root/tmp/log/le3gold-cadviewer: No such file or directory
Main process exited, code=exited, status=226/NAMESPACE
```

The process never started.

**Implementation:** no `/var/log` in `ReadWritePaths`; logs go to stdout and are
read with `journalctl -u le3gold-cadviewer`. `ReadWritePaths` contains only
`/var/lib/le3gold-cadviewer`.

**Verification:** `systemctl show -p ReadWritePaths le3gold-cadviewer` and
`journalctl -u le3gold-cadviewer`.

## 5. The platform does not load the package's nginx snippet

The package carries `nginx/le3gold-cadviewer.conf`, but nothing under
`/etc/nginx/conf.d/` points at it. Without an explicit copy, the portal route
`/<appid>/` does not exist and only the bare port works.

**Implementation:**

- `postinst` installs the snippet as `/etc/nginx/conf.d/le3gold-cadviewer.conf`
  and reloads nginx.
- `prerm` removes it and reloads nginx again, so nginx never proxies to a dead
  port.
- The `location` prefix, `config.ini` `path` and the backend's `URL_PREFIX` are
  all `/le3gold-cadviewer/`.

**Verification:** §6.3.

## 6. `webui.bz2` is flat and is extracted into `runtime/webui/`

Measured on the device: the archive contains `./index.html` at its root, and the
platform extracts it into `<app_dir>/webui/`. The package does the same into
`/var/lib/le3gold-cadviewer/runtime/webui/` so the service can read it without
`tmacl`.

`tools/make_webui.py` writes a deterministic archive: sorted entries, fixed
timestamp, uid/gid 0.

## 7. A hand-written `data.tar.gz` must contain parent directories

`dpkg` does not create missing parent directories while unpacking. The first
build of this package omitted `./usr/`, `./usr/local/`,
`./usr/local/le3gold-cadviewer/` and `.../bin/`, and failed with:

```
dpkg: error processing archive ... (--unpack):
 unable to create '/usr/local/le3gold-cadviewer/bin/le3gold-cadviewer.dpkg-new'
 (while processing './usr/local/le3gold-cadviewer/bin/le3gold-cadviewer'):
 No such file or directory
```

The message looks like a permission problem; it is a missing directory entry.

**Implementation:** `tools/build_deb.py` collects every path and adds all
ancestors; `tools/verify_deb.py` checks the result before the package is shipped.

## 8. File access follows the signed-in user, not the application account

The application account is a member of `allusers`, so reading `/Volume*` with it
sees more than the signed-in user is allowed to see. The platform's file service
is session-authenticated and answers for the signed-in user:

```
GET /v2/fileManage/homeList
GET /v2/fileManage/list?path=<abs>
GET /v2/fileManage/fileDownload?paths=<abs>
```

`homeList` and `list` require `X-Csrf-Token`, whose value is the cookie of the
same name. `fileDownload` does not. A successful response has `code_num == 0`.

The service must not connect to `/var/api/file-manage.sock` directly:
`/var/api` is a symlink into `/tmp/api`, and `PrivateTmp=true` hides it. The
working route is `http://127.0.0.1:8181/v2/fileManage/*`, the same nginx
location over TCP.

**Measured result for 1.2.0:** the administrator's root list fell from 37 shares
to three (`10GB`, `CADViewer`, `test`); revoking `10GB` for the application
account removed it immediately, and restoring it brought it back without a
restart. For the normal user `cadu`, only the personal folder is returned.

**Implementation:** `bin/le3gold-cadviewer` proxies these endpoints and builds
its roots from:

1. the signed-in user's personal folder (`is_home == 1`);
2. the shared folders the application account can actually list.

The `homes` container is never listed. If the service ever runs as root, it
fails closed to the folders owned by the application account.

## 9. Implementation map

| Measured constraint | Implementation | Verification |
| --- | --- | --- |
| `tmacl` denies the install tree | `postinst` stages `/var/lib/<appid>/runtime` | `su -s /bin/sh <appid> -c 'ls .../runtime/bin'` |
| Account exists after `postinst` | `StartLimitIntervalSec=0` + `runtime-fixup.sh` | `systemctl show -p StartLimitIntervalUSec` |
| No same-name group | `groupadd` in `postinst` | `systemctl show -p Group` |
| `/var/log` is tmpfs | no `/var/log` in `ReadWritePaths` | `systemctl show -p ReadWritePaths` |
| nginx snippet is inert | copy to `/etc/nginx/conf.d/` + reload | `curl 127.0.0.1:8181/<appid>/` |
| `webui.bz2` is flat | extract into `runtime/webui/` | `ls runtime/webui/index.html` |
| tar needs parent entries | `add_ancestor_dirs()` | `verify_deb.py` |
| per-user file access | proxy `/v2/fileManage/*` | normal-user A/B in §6 |

## 10. Verification commands

### 10.1 Installation and identity

```sh
dpkg -l | grep le3gold-cadviewer
systemctl status le3gold-cadviewer --no-pager
systemctl show -p User -p Group -p MainPID -p StartLimitIntervalUSec le3gold-cadviewer
ps -eo user,pid,args | grep le3gold-cadviewer
```

Expected: `User` and `Group` are `le3gold-cadviewer`, `StartLimitIntervalUSec=0`,
`MainPID` is non-zero, and the process command starts with
`/var/lib/le3gold-cadviewer/runtime/bin/le3gold-cadviewer`.

### 10.2 Ports and portal route

```sh
ss -ltnp | grep 17868
curl --noproxy '*' -sS http://127.0.0.1:17868/health
curl --noproxy '*' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8181/le3gold-cadviewer/
```

`--noproxy '*'` matters: the device shell exports `http_proxy`, and without it
the request goes to the proxy and returns 502 even though the service is healthy.

### 10.3 Logs

```sh
journalctl -u le3gold-cadviewer -n 100 --no-pager
tail -50 /var/log/dpkg.log
cat /var/lib/le3gold-cadviewer/install.log
```

### 10.4 Normal-user A/B

Sign in as a non-administrator and check, in this order:

1. Before the administrator grants the application: no icon in the desktop or
   application list.
2. Direct URL access still returns 200. This is a platform limitation: the
   third-party application has no `auth_request` gate, so hiding the icon is not
   an access control.
3. After the administrator grants the application: the icon appears.
4. In `Import from the NAS`, only the personal folder and the folders granted to
   the application account are listed.
5. Opening a file from a folder the user cannot read returns a permission error,
   not the file.

## 11. Packaging checklist

- `config.ini` parses as JSON; no comments, no single quotes, no trailing commas.
- `id`, `version`, `package`, `system_id`, `user` agree with `DEBIAN/control`
  and the unit filename.
- `path` and the nginx `location` prefix are identical.
- The icon exists at the path in `config.ini`.
- `webui.bz2` contains `index.html` at its root.
- Every text file is UTF-8 without BOM and LF-only.
- `data.tar.gz` contains every parent directory.
- No ELF binary in the data package.
- `md5sums` is present.
- `build/<appid>_<version>_<platform>.deb.sha256` matches the package.

## 12. Known platform limitations that affect this application

These are platform-side behaviours, not package defects. They are listed here so
support can recognize them quickly.

| Behaviour | Effect on this application |
| --- | --- |
| A brand-new app id can fail App Center manual install at 0% | Validate a first install with `dpkg -i`, or keep an existing install record |
| Application permissions only hide the icon | A user who knows the URL can still open the application |
| No API returns the folders granted to the application account | The service probes with the application account's own `listdir` |
| A normal user's folder grant does not reach the web file service | The user still sees only the personal folder after being granted a share |
| Release assets can be briefly empty after publishing | Wait and refresh before re-uploading |

## 13. Measurement history

| Version | Change | Reason |
| --- | --- | --- |
| 1.0.2 | Removed the non-root identity | The account could not read the install tree under `tmacl` |
| 1.1.4 | Ran as root | Same constraint; rejected by review item V1 |
| 1.1.5 | Staged the runtime outside the volume, opened through the portal route | Run non-root without `tmacl` |
| 1.1.6 | Added `StartLimitIntervalSec=0` and `runtime-fixup.sh` | First install ran before the account existed |
| 1.1.7 | `</br>` in `release_note` | Detail page renders the field as HTML |
| 1.1.8 | All 14 languages; `all_user_display: false` | Store copy and per-user authorization |
| 1.1.9 | Proxied `/v2/fileManage/*` | Stop reading disks as the application account |
| 1.2.0 | Roots limited to granted folders | The picker listed all 37 shares |

## 14. Reusing this checklist

The reusable, project-independent version covers selection, package layout,
build reproducibility, first-install timing, `tmacl`, nginx, permissions,
localization and review. When starting a new GitHub-to-TOS package, use that
handbook for the generic steps and this file as the worked example for CAD
Viewer.