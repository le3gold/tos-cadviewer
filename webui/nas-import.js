/*
 * NAS import for the TOS 7 packaging of Online 3D Viewer.
 *
 * The toolbar's open button normally shows the browser's file dialog, so a
 * model that already lives on the device has to be downloaded to the client
 * and uploaded again. This replaces the button with a two item menu and adds a
 * browser for the shared folders.
 *
 * It talks to the file API of bin/le3gold-cadviewer. The platform's own picker
 * (x-upload-file / x-path-select) is a global component of the TOS desktop SPA
 * and is not reachable from an externally opened application; see
 * docs/superpowers/specs/2026-09-23-nas-file-import-design.md.
 *
 * Part of the TOS 7 packaging of Online 3D Viewer, see licenses/NOTICE.md.
 */

(function () {
    'use strict';

    var STRINGS = {
        'en': {
            menuComputer: 'Import from this computer',
            menuNas: 'Import from the NAS',
            title: 'Import from the NAS',
            shares: 'Shared folders',
            up: 'Up',
            empty: 'No importable model in this folder.',
            formats: 'Only file types the viewer can open are listed.',
            open: 'Open',
            cancel: 'Cancel',
            loading: 'Loading...',
            failed: 'Could not read the folder:'
        },
        'zh-cn': {
            menuComputer: '从电脑导入',
            menuNas: '从 NAS 导入',
            title: '从 NAS 导入',
            shares: '共享文件夹',
            up: '上一层',
            empty: '这个文件夹里没有可导入的模型。',
            formats: '这里只列出 Viewer 能打开的格式。',
            open: '打开',
            cancel: '取消',
            loading: '读取中...',
            failed: '读取文件夹失败：'
        },
        'zh-tw': {
            menuComputer: '從電腦匯入',
            menuNas: '從 NAS 匯入',
            title: '從 NAS 匯入',
            shares: '共享資料夾',
            up: '上一層',
            empty: '這個資料夾裡沒有可匯入的模型。',
            formats: '這裡只列出 Viewer 能打開的格式。',
            open: '開啟',
            cancel: '取消',
            loading: '讀取中...',
            failed: '讀取資料夾失敗：'
        }
    };

    // The viewer itself is upstream and always English, so there is no
    // in-app language setting to follow; the browser decides.
    var LANGUAGE = (function () {
        var value = (navigator.language || 'en').toLowerCase ();
        if (value.indexOf ('zh') === 0) {
            if (value.indexOf ('tw') !== -1 || value.indexOf ('hk') !== -1 || value.indexOf ('hant') !== -1) {
                return 'zh-tw';
            }
            return 'zh-cn';
        }
        return 'en';
    } ());

    function T (key)
    {
        var table = STRINGS[LANGUAGE] || STRINGS['en'];
        if (table[key] !== undefined) {
            return table[key];
        }
        return STRINGS['en'][key] !== undefined ? STRINGS['en'][key] : key;
    }

    function RequestJson (url)
    {
        return fetch (url, {
            credentials : 'same-origin',
            headers : { 'Accept' : 'application/json' }
        }).then (function (response) {
            return response.json ().catch (function () { return {}; }).then (function (payload) {
                if (!response.ok) {
                    throw new Error (payload.error || ('HTTP ' + response.status));
                }
                return payload;
            });
        });
    }

    function FormatSize (bytes)
    {
        if (!bytes) {
            return '';
        }
        var units = ['B', 'KB', 'MB', 'GB', 'TB'];
        var value = bytes;
        var unit = 0;
        while (value >= 1024 && unit < units.length - 1) {
            value = value / 1024;
            unit = unit + 1;
        }
        return (unit === 0 ? value : value.toFixed (value < 10 ? 1 : 0)) + ' ' + units[unit];
    }

    function CreateElement (tag, className, text)
    {
        var element = document.createElement (tag);
        if (className) {
            element.className = className;
        }
        if (text !== undefined && text !== null) {
            element.textContent = text;
        }
        return element;
    }

    function ShowMenu (anchor, items)
    {
        var menu = CreateElement ('div', 'o3dv_nas_menu');
        var closed = false;

        function Close ()
        {
            if (closed) {
                return;
            }
            closed = true;
            document.removeEventListener ('mousedown', OnOutside, true);
            document.removeEventListener ('keydown', OnKey, true);
            if (menu.parentNode) {
                menu.parentNode.removeChild (menu);
            }
        }

        function OnOutside (event)
        {
            if (!menu.contains (event.target)) {
                Close ();
            }
        }

        function OnKey (event)
        {
            if (event.key === 'Escape') {
                Close ();
            }
        }

        for (var i = 0; i < items.length; i++) {
            (function (item) {
                var button = CreateElement ('div', 'o3dv_nas_menu_item', item.label);
                button.addEventListener ('click', function (event) {
                    event.stopPropagation ();
                    Close ();
                    item.onPick ();
                });
                menu.appendChild (button);
            } (items[i]));
        }

        document.body.appendChild (menu);
        var box = anchor.getBoundingClientRect ();
        menu.style.left = Math.round (box.left) + 'px';
        menu.style.top = Math.round (box.bottom + 2) + 'px';

        document.addEventListener ('mousedown', OnOutside, true);
        document.addEventListener ('keydown', OnKey, true);
    }

    function BuildFileUrl (path)
    {
        // The viewer takes the file name, and the folder it looks for sidecar
        // files such as an OBJ material library in, straight off this URL, so
        // the share path goes in as plain segments without the leading
        // separator. Only the characters that would confuse a URL are escaped.
        var url = 'api/fs/open';
        var segments = path.split ('/');
        for (var i = 0; i < segments.length; i++) {
            if (segments[i].length > 0) {
                url += '/' + encodeURIComponent (segments[i]);
            }
        }
        return url;
    }

    function ShowNasDialog (onPick)
    {
        var selected = null;

        var overlay = CreateElement ('div', 'o3dv_nas_overlay');
        var panel = CreateElement ('div', 'o3dv_nas_panel');
        overlay.appendChild (panel);

        var header = CreateElement ('div', 'o3dv_nas_header');
        header.appendChild (CreateElement ('div', 'o3dv_nas_title', T ('title')));
        var closeButton = CreateElement ('div', 'o3dv_nas_close', '\u00d7');
        header.appendChild (closeButton);
        panel.appendChild (header);

        var bar = CreateElement ('div', 'o3dv_nas_bar');
        var upButton = CreateElement ('button', 'o3dv_nas_up', T ('up'));
        upButton.type = 'button';
        upButton.disabled = true;
        bar.appendChild (upButton);
        var pathLabel = CreateElement ('div', 'o3dv_nas_path');
        bar.appendChild (pathLabel);
        panel.appendChild (bar);

        var list = CreateElement ('div', 'o3dv_nas_list');
        panel.appendChild (list);

        var footer = CreateElement ('div', 'o3dv_nas_footer');
        footer.appendChild (CreateElement ('div', 'o3dv_nas_hint', T ('formats')));
        var buttons = CreateElement ('div', 'o3dv_nas_buttons');
        var cancelButton = CreateElement ('button', 'o3dv_nas_button', T ('cancel'));
        cancelButton.type = 'button';
        var openButton = CreateElement ('button', 'o3dv_nas_button o3dv_nas_button_primary', T ('open'));
        openButton.type = 'button';
        openButton.disabled = true;
        buttons.appendChild (cancelButton);
        buttons.appendChild (openButton);
        footer.appendChild (buttons);
        panel.appendChild (footer);

        function Close ()
        {
            document.removeEventListener ('keydown', OnKey, true);
            if (overlay.parentNode) {
                overlay.parentNode.removeChild (overlay);
            }
        }

        function OnKey (event)
        {
            if (event.key === 'Escape') {
                Close ();
            }
        }

        function SetSelected (entry)
        {
            selected = entry;
            openButton.disabled = (entry === null);
            var rows = list.querySelectorAll ('.o3dv_nas_row');
            for (var i = 0; i < rows.length; i++) {
                var isSelected = entry !== null && rows[i].getAttribute ('data-path') === entry.path;
                if (isSelected) {
                    rows[i].classList.add ('selected');
                } else {
                    rows[i].classList.remove ('selected');
                }
            }
        }

        function CreateRow (entry)
        {
            var row = CreateElement ('div', 'o3dv_nas_row');
            row.setAttribute ('data-path', entry.path);
            row.appendChild (CreateElement ('div',
                'o3dv_nas_icon ' + (entry.type === 'dir' ? 'o3dv_nas_icon_dir' : 'o3dv_nas_icon_file')));
            row.appendChild (CreateElement ('div', 'o3dv_nas_name', entry.name));
            row.appendChild (CreateElement ('div', 'o3dv_nas_size',
                entry.type === 'file' ? FormatSize (entry.size) : ''));
            row.addEventListener ('click', function () {
                if (entry.type === 'dir') {
                    Load (entry.path);
                } else {
                    SetSelected (entry);
                }
            });
            row.addEventListener ('dblclick', function () {
                if (entry.type === 'file') {
                    SetSelected (entry);
                    Confirm ();
                }
            });
            return row;
        }

        function ShowMessage (text)
        {
            list.textContent = '';
            list.appendChild (CreateElement ('div', 'o3dv_nas_empty', text));
        }

        function RenderShares (payload)
        {
            pathLabel.textContent = T ('shares');
            upButton.disabled = true;
            list.textContent = '';
            var volume = null;
            for (var i = 0; i < payload.roots.length; i++) {
                var share = payload.roots[i];
                if (share.volume !== volume) {
                    volume = share.volume;
                    list.appendChild (CreateElement ('div', 'o3dv_nas_group', volume));
                }
                list.appendChild (CreateRow ({
                    name : share.name, path : share.path, type : 'dir', size : 0
                }));
            }
            if (payload.roots.length === 0) {
                ShowMessage (T ('empty'));
            }
        }

        function RenderDirectory (payload)
        {
            pathLabel.textContent = payload.path;
            upButton.disabled = false;
            upButton.setAttribute ('data-parent', payload.parent === null ? '' : payload.parent);
            list.textContent = '';
            for (var i = 0; i < payload.entries.length; i++) {
                list.appendChild (CreateRow (payload.entries[i]));
            }
            if (payload.entries.length === 0) {
                ShowMessage (T ('empty'));
            }
        }

        function Load (path)
        {
            ShowMessage (T ('loading'));
            SetSelected (null);
            var url = path === null ? 'api/fs/roots'
                                    : 'api/fs/list?path=' + encodeURIComponent (path);
            RequestJson (url).then (function (payload) {
                if (path === null) {
                    RenderShares (payload);
                } else {
                    RenderDirectory (payload);
                }
            }).catch (function (error) {
                ShowMessage (T ('failed') + ' ' + error.message);
            });
        }

        function Confirm ()
        {
            if (selected === null) {
                return;
            }
            var url = BuildFileUrl (selected.path);
            Close ();
            onPick (url, selected.name);
        }

        closeButton.addEventListener ('click', Close);
        cancelButton.addEventListener ('click', Close);
        openButton.addEventListener ('click', Confirm);
        overlay.addEventListener ('mousedown', function (event) {
            if (event.target === overlay) {
                Close ();
            }
        });
        upButton.addEventListener ('click', function () {
            var parent = upButton.getAttribute ('data-parent');
            Load (parent ? parent : null);
        });
        document.addEventListener ('keydown', OnKey, true);

        document.body.appendChild (overlay);
        Load (null);
    }

    // A URL list load needs the import settings the website builds for its own
    // hash based loads: the loader reads the default colours off it and throws
    // on an undefined one. The website object exposes no factory for it, and
    // the class only ever carries these two fields.
    function CreateImportSettings (website)
    {
        return {
            defaultLineColor : website.settings.defaultLineColor,
            defaultColor : website.settings.defaultColor
        };
    }

    // A glTF that keeps its buffers and textures beside itself, and an OBJ that
    // names a material library, only mention those files inside themselves. The
    // importer asks the host for them by name while it reads the model, so they
    // have to be handed over in the same list as the model, or the import stops
    // with "One of the requested buffers is missing".
    function CompanionNames (extension, text)
    {
        var names = [];
        function add (uri)
        {
            if (typeof uri !== 'string' || uri.length === 0 || uri.indexOf ('data:') === 0) {
                return;
            }
            // Absolute URLs and protocol relative ones are not siblings.
            if (uri.indexOf ('//') !== -1 || uri.indexOf (':') !== -1) {
                return;
            }
            if (names.indexOf (uri) === -1) {
                names.push (uri);
            }
        }
        if (extension === '.gltf') {
            var json = null;
            try {
                json = JSON.parse (text);
            } catch (error) {
                json = null;
            }
            if (json === null) {
                return names;
            }
            (json.buffers || []).forEach (function (item) { add (item && item.uri); });
            (json.images || []).forEach (function (item) { add (item && item.uri); });
        } else if (extension === '.obj') {
            var lines = text.split ('\n');
            for (var i = 0; i < lines.length; i++) {
                var match = /^\s*mtllib\s+(.+?)\s*$/.exec (lines[i]);
                if (match !== null) {
                    add (match[1]);
                }
            }
        } else if (extension === '.mtl') {
            var mtlLines = text.split ('\n');
            for (var j = 0; j < mtlLines.length; j++) {
                var texture = /^\s*map_\w+\s+(.+?)\s*$/.exec (mtlLines[j]);
                if (texture !== null) {
                    add (texture[1]);
                }
            }
        }
        return names;
    }

    function ReadText (url)
    {
        return fetch (url).then (function (response) {
            return response.ok ? response.text () : '';
        }).catch (function () {
            return '';
        });
    }

    function SiblingUrl (url, name)
    {
        var directory = url.replace (/[^\/]*$/, '');
        return directory + name.split ('/').map (encodeURIComponent).join ('/');
    }

    function LoadWithCompanions (url, name, onUrls)
    {
        var extension = (name.match (/\.[^.]*$/) || [''])[0].toLowerCase ();
        if (extension !== '.gltf' && extension !== '.obj') {
            onUrls ([url]);
            return;
        }
        ReadText (url).then (function (text) {
            var urls = [url];
            var libraries = [];
            CompanionNames (extension, text).forEach (function (companion) {
                var sibling = SiblingUrl (url, companion);
                urls.push (sibling);
                if (extension === '.obj') {
                    libraries.push (sibling);
                }
            });
            // The material library names its textures, so one more round.
            Promise.all (libraries.map (function (library) {
                return ReadText (library).then (function (body) {
                    return CompanionNames ('.mtl', body);
                });
            })).then (function (lists) {
                lists.forEach (function (list) {
                    list.forEach (function (texture) {
                        urls.push (SiblingUrl (url, texture));
                    });
                });
                onUrls (urls);
            });
        });
    }

    function Install (website)
    {
        var toolbar = document.getElementById ('toolbar');
        if (!toolbar) {
            return;
        }
        var button = toolbar.querySelector ('.ov_toolbar_button');
        if (!button) {
            return;
        }
        // The listener sits on the toolbar rather than on the button: a
        // listener on the button itself would run after the one upstream
        // registered there. Capturing on the ancestor runs first and stops the
        // event before the native file dialog can open.
        toolbar.addEventListener ('click', function (event) {
            if (event.target !== button && !button.contains (event.target)) {
                return;
            }
            event.stopPropagation ();
            event.preventDefault ();
            ShowMenu (button, [
                {
                    label : T ('menuComputer'),
                    onPick : function () { website.OpenFileBrowserDialog (); }
                },
                {
                    label : T ('menuNas'),
                    onPick : function () {
                        ShowNasDialog (function (url, name) {
                            LoadWithCompanions (url, name, function (urls) {
                                website.LoadModelFromUrlList (urls, CreateImportSettings (website));
                            });
                        });
                    }
                }
            ]);
        }, true);
    }

    function Start (attempt)
    {
        if (window.o3dvWebsite) {
            Install (window.o3dvWebsite);
            return;
        }
        if ((attempt || 0) < 20) {
            setTimeout (function () { Start ((attempt || 0) + 1); }, 100);
        }
    }

    if (document.readyState === 'complete') {
        Start (0);
    } else {
        window.addEventListener ('load', function () { Start (0); });
    }
} ());
