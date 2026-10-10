"""Tray on pywebview's existing WinForms thread; no extra dependency or agent.

Reuses the existing fox icons and animation controller. Idle/error have no timer.
Only an actual local read may animate, at 600 ms or slower. Imports are lazy.
"""
from .tray_animation import AnimationController, AnimationPolicy, TrayState, resolve_icon_paths
TEXT = {"idle": "Aguardando arquivo", "reading": "Lendo arquivo local", "error": "Arquivo precisa de atenção"}


class WindowsFormsTray:
    def __init__(self, window, state):
        self._window, self._form, self._state = window, window.native, state
        self._controller = AnimationController(AnimationPolicy(enabled=False))
        self._icons = {}
        self._notify = self._menu = self._timer = None
        self._disposed = False
        self._last_icon = None
        self._frame_updates = 0

    def _invoke(self, callback):
        from System import Action
        if self._form.IsDisposed: return
        if self._form.InvokeRequired: self._form.Invoke(Action(callback))
        else: callback()

    def _enqueue_refresh(self):
        from System import Action
        if not self._disposed and not self._form.IsDisposed:
            self._form.BeginInvoke(Action(self._refresh))

    def start(self):
        self._invoke(self._create)
        self._state._changed = self._enqueue_refresh

    def _create(self):
        from System import Drawing
        from System.Windows.Forms import NotifyIcon, ContextMenuStrip, ToolStripMenuItem, ToolStripSeparator, Timer, MouseButtons
        try:
            by_path = {}
            for key, path in resolve_icon_paths().items():
                if path not in by_path: by_path[path] = Drawing.Icon(str(path))
                self._icons[key] = by_path[path]
            # A neutral icon keeps window controls available when the fox is hidden.
            self._neutral = Drawing.SystemIcons.Application.Clone()
            self._menu = ContextMenuStrip()
            self._status_item = ToolStripMenuItem(); self._status_item.Enabled = False
            self._open_item = ToolStripMenuItem("Mostrar janela")
            self._hide_item = ToolStripMenuItem("Ocultar janela")
            self._quit_item = ToolStripMenuItem("Sair")
            self._open_item.Click += self._open
            self._hide_item.Click += self._hide
            self._quit_item.Click += self._quit
            for item in (self._status_item, ToolStripSeparator(), self._open_item, self._hide_item, ToolStripSeparator(), self._quit_item):
                self._menu.Items.Add(item)
            self._notify = NotifyIcon()
            self._notify.ContextMenuStrip = self._menu
            def mouse(sender, event):
                if event.Button == MouseButtons.Left: self._open()
            self._mouse = mouse
            self._notify.MouseClick += mouse
            self._notify.MouseDoubleClick += mouse
            self._timer = Timer(); self._timer.Interval = 600
            self._timer.Tick += self._tick
            self._refresh()
            self._notify.Visible = True
            self._form.FormClosed += self._closed
            self._form.VisibleChanged += self._visibility_changed
        except Exception:
            self._dispose()
            raise

    def _refresh(self):
        if self._disposed or self._notify is None: return
        snapshot = self._state.snapshot()
        activity, fox = snapshot["activity"], snapshot["fox"]
        animated = activity == "reading" and fox["show"] and fox["animate"] and not snapshot["reduced_motion"]
        self._controller.set_policy(AnimationPolicy(enabled=animated, reduced_motion=snapshot["reduced_motion"]))
        self._controller.set_state({"idle": TrayState.IDLE, "reading": TrayState.WORKING, "error": TrayState.ERROR}[activity])
        self._current_activity = activity
        self._notify.Text = "Coletor · Teste · Coleta desligada · " + TEXT[activity]
        self._status_item.Text = TEXT[activity] + " · Coleta desligada"
        if animated: self._timer.Start()
        else: self._timer.Stop()
        self._paint_icon()
        self._visibility_changed()

    def _paint_icon(self):
        key = self._controller.snapshot().frame_key if self._state.snapshot()["fox"]["show"] else "neutral"
        if key != self._last_icon:
            self._notify.Icon = self._neutral if key == "neutral" else self._icons[key]
            self._last_icon = key
            self._frame_updates += 1

    def _tick(self, *_):
        if not self._disposed: self._paint_icon()

    def _visibility_changed(self, *_):
        if self._disposed: return
        self._open_item.Enabled = True
        self._hide_item.Enabled = bool(self._form.Visible)

    def _open(self, *_):
        from System.Windows.Forms import FormWindowState
        if self._disposed: return
        self._form.Show()
        if self._form.WindowState == FormWindowState.Minimized: self._form.WindowState = FormWindowState.Normal
        self._form.Activate()

    def _hide(self, *_):
        if not self._disposed: self._form.Hide()

    def hide(self):
        if self._disposed: return {"error": "A bandeja não está disponível. A janela continua aberta."}
        self._invoke(self._hide)
        return {"hidden": True}

    def _quit(self, *_):
        if self._disposed: return
        self._dispose()
        self._form.Close()

    def _closed(self, *_):
        self._dispose()

    def _dispose(self):
        if self._disposed: return
        self._disposed = True
        self._state._changed = lambda: None
        resources = []
        # pythonnet event delegates retain Python objects after Dispose unless
        # detached explicitly. Release every subscription before CLR shutdown.
        def detach_events():
            self._form.FormClosed -= self._closed
            self._form.VisibleChanged -= self._visibility_changed
            self._timer.Tick -= self._tick
            self._notify.MouseClick -= self._mouse
            self._notify.MouseDoubleClick -= self._mouse
            self._open_item.Click -= self._open
            self._hide_item.Click -= self._hide
            self._quit_item.Click -= self._quit
        if self._notify is not None and self._timer is not None: resources.append(detach_events)
        if self._timer: resources += [self._timer.Stop, self._timer.Dispose]
        if self._notify: resources += [lambda: setattr(self._notify, "Visible", False), self._notify.Dispose]
        if self._menu: resources += [self._menu.Dispose]
        resources += [icon.Dispose for icon in set(self._icons.values())]
        if hasattr(self, "_neutral"): resources += [self._neutral.Dispose]
        self._cleanup_ok = True
        for action in resources:
            try: action()
            except Exception: self._cleanup_ok = False
        self._icons.clear()

    def stop(self):
        if not self._disposed: self._invoke(self._dispose)
