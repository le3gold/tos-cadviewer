#!/bin/sh
# Runtime repair hook for CAD Viewer on TOS 7.
#
# Why this file exists
# --------------------
# The platform executes DEBIAN/postinst BEFORE it provisions the application
# account. Everything postinst wants to do with that account therefore fails on
# a fresh install, and the failure is silent: the calls simply return non-zero.
# Captured on a real TNAS, TOS 7.0.1201, first install of a brand new
# application (journal):
#
#   19:13:05 application: CreateAppFolder: owner lookup failed, using root
#   19:13:06 systemd: le3gold-cadviewer.service: Failed to determine user
#                      credentials: No such file or directory   (217/USER)
#   19:13:57 systemd: le3gold-cadviewer.service: Start request repeated too
#                      quickly.
#
# The account appeared a few seconds later. Because the unit had already burnt
# its start-limit budget, the application stayed dead until it was installed a
# second time - which is the reason this hook and the unit's
# StartLimitIntervalSec=0 exist.
#
# systemd runs this script with the "+" prefix, so it runs as root while the
# service itself keeps running as the unprivileged application account. It
# performs the three repairs postinst could not, and it is idempotent, silent
# when there is nothing to do, and always exits 0: it must never be the reason
# a service fails to start.
set -u

APPID="le3gold-cadviewer"
APP_ROOT="/usr/local/${APPID}"
DATA_ROOT="/var/lib/${APPID}"
RUNTIME="${DATA_ROOT}/runtime"
SHARE_FOLDER="CADViewer"

log() { echo "${APPID}: runtime-fixup: $*"; }

# Nothing can be repaired before the account exists. The unit keeps retrying
# (StartLimitIntervalSec=0), so this case resolves itself within one restart
# interval of the platform creating the account.
if ! getent passwd "${APPID}" >/dev/null 2>&1; then
    log "application account ${APPID} does not exist yet; waiting"
    chmod 0755 "${DATA_ROOT}" 2>/dev/null || true
    exit 0
fi

APP_UID="$(id -u "${APPID}" 2>/dev/null || echo '')"

# 1. Ownership and modes of the staged runtime.
#
#    The runtime is copied out of the install tree because /Volume* is guarded
#    by tmacl and denies the unprivileged account even its own application
#    directory. postinst stages it, but could not own it on the first install.
#    The ownership test keeps the common path free of a recursive chown.
if [ -d "${DATA_ROOT}" ] && [ -n "${APP_UID}" ]; then
    if [ "$(stat -c '%u' "${DATA_ROOT}" 2>/dev/null || echo '')" != "${APP_UID}" ]; then
        chown -R "${APPID}:${APPID}" "${DATA_ROOT}" 2>/dev/null || true
        log "repaired ownership of ${DATA_ROOT}"
    fi
    if [ "$(stat -c '%u' "${DATA_ROOT}" 2>/dev/null || echo '')" = "${APP_UID}" ]; then
        chmod 0750 "${DATA_ROOT}" 2>/dev/null || true
    else
        # The chown did not take. Keep the tree traversable so the service can
        # still start; nothing in it is writable by the account.
        chmod 0755 "${DATA_ROOT}" 2>/dev/null || true
    fi
    [ -d "${RUNTIME}" ] && chmod 0755 "${RUNTIME}" 2>/dev/null || true
    [ -d "${RUNTIME}/bin" ] && chmod 0755 "${RUNTIME}/bin" 2>/dev/null || true
    [ -d "${RUNTIME}/webui" ] && chmod -R a+rX "${RUNTIME}/webui" 2>/dev/null || true
fi

# 2. Membership of allusers, the group the platform shares folders with.
if ! id -nG "${APPID}" 2>/dev/null | tr ' ' '\n' | grep -qx allusers; then
    usermod -aG allusers "${APPID}" >/dev/null 2>&1 && log "added ${APPID} to allusers" || true
fi

# 3. tmacl entries: traversal on the volume roots, read-write on the
#    application's own shared folder. Both need the account to exist, which is
#    why postinst's identical calls failed on the first install.
if command -v tmacltool >/dev/null 2>&1; then
    for VOL in /Volume[0-9]*; do
        [ -d "${VOL}" ] || continue
        if ! tmacltool get "${VOL}" 2>/dev/null | grep -q "user:${APPID}:"; then
            tmacltool modify "${VOL}" "user:${APPID}:allow:r-x:--" >/dev/null 2>&1 \
                && log "granted ${APPID} traversal on ${VOL}" || true
        fi
    done

    SHARE_PATH=""
    for VOL in /Volume[0-9]*; do
        if [ -d "${VOL}/${SHARE_FOLDER}" ]; then
            SHARE_PATH="${VOL}/${SHARE_FOLDER}"
            break
        fi
    done

    if [ -n "${SHARE_PATH}" ]; then
        if ! tmacltool get "${SHARE_PATH}" 2>/dev/null | grep -q "user:${APPID}:"; then
            tmacltool modify "${SHARE_PATH}" "user:${APPID}:allow:rwxpdDaARWc:fd" >/dev/null 2>&1 \
                && log "granted ${APPID} access to ${SHARE_PATH}" || true
        fi
        if [ -n "${APP_UID}" ] \
           && [ "$(stat -c '%u' "${SHARE_PATH}" 2>/dev/null || echo '')" != "${APP_UID}" ]; then
            # Non-recursive on purpose: the models the user keeps in there must
            # not change owner.
            chown "${APPID}:${APPID}" "${SHARE_PATH}" 2>/dev/null || true
        fi
    fi
fi

exit 0
