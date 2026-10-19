"""Tray on pywebview's existing WinForms thread; no extra dependency or agent.

Reuses the existing fox icons and animation controller. Idle/error have no timer.
Only an actual local read may animate, at 600 ms or slower. Imports are lazy.
"""
import threading
from .tray_animation import AnimationController, AnimationPolicy, TrayState, resolve_icon_paths
TEXT = {"idle": "Aguardando arquivo", "reading": "Lendo arquivo local", "error": "Arquivo precisa de atenção"}
COLLECTOR_TEXT = {"ready": "Coleta ativa", "reserve": "Reserva", "collecting": "Coletando",
                  "paused": "Coleta pausada", "login-required": "Entrar no Smecel", "error": "Precisa de atenção"}


def offline(collector):
    """No network for a moment (the runtime reports it as a 'reserve' wait):
    the fox keeps its calm motion and says it is trying again. The catch-all
    'unavailable' is a real fault and keeps the attention badge."""
    return bool(collector and collector.get("code") == "ACCESS_UNAVAILABLE")


def tray_text(collector, activity):
    """Notification-area tooltip (63 characters at most on .NET Framework)."""
    if offline(collector) and collector.get("active"):
        return "Coletor de Frequência · Sem conexão, tentando de novo"
    if collector and collector.get("active") and collector.get("state") in COLLECTOR_TEXT:
        return "Coletor de Frequência · " + COLLECTOR_TEXT[collector["state"]]
    return "Coletor · Coleta desligada · " + TEXT[activity]


def hides_on_close(user_closing, quitting, collector, registered):
    """The window's X keeps an active collection running beside the clock.

    Sair in the tray menu, Windows shutdown/logoff and an inactive collector close normally.
    """
    return bool(user_closing and not quitting and registered and collector and collector.get("active"))


class WindowsFormsTray:
    def __init__(self, window, state):
        self._window, self._form, self._state = window, window.native, state
        self._controller = AnimationController(AnimationPolicy(enabled=False))
        self._icons = {}
        self._notify = self._menu = self._timer = self._poll = self._fox_menu = None
        self.status_provider = None
        # Set by the desktop bridge: actions run off the UI thread.
        self.collect_action = self.pause_action = None
        self.theme_provider = None
        self.notifications_provider = self.notifications_action = self.logs_action = None
        self._current_activity = "idle"
        self._disposed = False
        self._last_icon = self._window_icon = None
        self._frame_updates = 0
        self._quitting = self._told_hidden = False

    def _invoke(self, callback):
        from System import Action
        if self._form.IsDisposed: return
        if self._form.InvokeRequired: self._form.Invoke(Action(callback))
        else: callback()

    def _enqueue_refresh(self):
        from System import Action, ObjectDisposedException, InvalidOperationException
        if not self._disposed and not self._form.IsDisposed:
            try: self._form.BeginInvoke(Action(self._refresh))
            except (ObjectDisposedException, InvalidOperationException): pass  # Window closed between the checks.

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
            # Drawn like the Atualizador's menu, in the fox's colours.
            from .tray_menu import FoxMenu
            self._menu = ContextMenuStrip()
            self._fox_menu = FoxMenu(self._menu)
            self._status_item = ToolStripMenuItem(); self._status_item.Enabled = False
            self._open_item = ToolStripMenuItem("Abrir painel")
            self._collect_item = ToolStripMenuItem("Coletar agora")
            self._pause_item = ToolStripMenuItem("Pausar a coleta")
            self._notify_item = ToolStripMenuItem("Mostrar notificações")
            self._logs_item = ToolStripMenuItem("Abrir pasta de logs")
            self._quit_item = ToolStripMenuItem("Encerrar coletor")
            self._open_item.Click += self._open
            self._collect_item.Click += self._collect
            self._pause_item.Click += self._toggle_pause
            self._notify_item.Click += self._toggle_notifications
            self._logs_item.Click += self._open_logs
            self._quit_item.Click += self._quit
            # Same composition as the Atualizador's menu.
            for item, kind, icon in ((self._status_item, "header", ""), (ToolStripSeparator(), "separator", ""),
                                     (self._open_item, "item", "open"), (self._collect_item, "item", "sync"),
                                     (self._pause_item, "item", "pause"), (self._notify_item, "toggle", "bell"),
                                     (self._logs_item, "item", "folder"),
                                     (ToolStripSeparator(), "separator", ""), (self._quit_item, "danger", "power")):
                self._fox_menu.add(item, kind, icon)
            self._menu.Opening += self._menu_opening
            self._notify = NotifyIcon()
            from System.Reflection import BindingFlags
            # Visible is only a requested state. On the targeted .NET Framework
            # 4.8, added records Shell_NotifyIcon's real registration result.
            flags = BindingFlags.Instance | BindingFlags.NonPublic
            self._registration_field = self._notify.GetType().GetField("added", flags)
            if self._registration_field is None:
                raise RuntimeError("Notification registration cannot be verified")
            self._notify.ContextMenuStrip = self._menu
            def mouse(sender, event):
                if event.Button == MouseButtons.Left: self._open()
            self._mouse = mouse
            self._notify.MouseClick += mouse
            self._notify.MouseDoubleClick += mouse
            self._notify.BalloonTipClicked += self._open
            self._timer = Timer(); self._timer.Interval = 600
            self._timer.Tick += self._tick
            # The collector runs in its own threads; its state reaches the tooltip here.
            self._poll = Timer(); self._poll.Interval = 5000
            self._poll.Tick += self._poll_tick
            self._poll.Start()
            self._refresh()
            self._notify.Visible = True
            self._form.FormClosing += self._closing
            self._form.FormClosed += self._closed
            self._form.VisibleChanged += self._visibility_changed
            self._form.Resize += self._visibility_changed
        except Exception:
            self._dispose()
            raise

    def _refresh(self):
        if self._disposed or self._notify is None: return
        snapshot = self._state.snapshot()
        activity, fox = self._effective_activity(snapshot), snapshot["fox"]
        # The fox rests with an occasional blink/ear twitch and works while
        # collecting; error stays still. Reduced motion or a hidden fox stops it.
        animated = activity in {"idle", "reading"} and fox["show"] and fox["animate"] and not snapshot["reduced_motion"]
        self._controller.set_policy(AnimationPolicy(enabled=animated, reduced_motion=snapshot["reduced_motion"]))
        self._controller.set_state({"idle": TrayState.IDLE, "reading": TrayState.WORKING, "error": TrayState.ERROR}[activity])
        self._current_activity = activity
        self._update_text()
        if animated: self._timer.Start()
        else: self._timer.Stop()
        self._paint_icon()
        self._visibility_changed()

    def _effective_activity(self, snapshot):
        """Window activity, plus the unattended collection the window does not drive."""
        activity = snapshot["activity"]
        status = self._collector_status() or {}
        state = status.get("state")
        if state == "collecting": return "reading"
        if activity == "idle" and state in {"error", "login-required"} and not offline(status): return "error"
        return activity

    def _menu_opening(self, *_):
        if self.theme_provider: self._fox_menu.set_theme(self.theme_provider())
        status = self._collector_status() or {}
        active, paused = bool(status.get("active")), bool(status.get("localPaused"))
        text = COLLECTOR_TEXT.get(status.get("state"), "Coleta desligada") if active else "Coleta desligada"
        if active and paused: text = "Pausada neste computador"
        if active and offline(status): text = "Sem conexão, tentando de novo"
        trouble = (not active) or (status.get("state") in {"error", "login-required"} and not offline(status))
        if active and not trouble and not paused:
            # Like the Atualizador's "Ativo · 1 tarefa(s)": what this PC collects.
            chosen = status.get("selectedClasses")
            text += " · todas as turmas" if status.get("classesMode", "all") == "all" or chosen is None else f" · {chosen} turma(s)"
        self._status_item.Text = "Coletor de Frequência\n" +("!" if trouble else "") + text
        self._collect_item.Enabled = active and not paused and status.get("state") != "collecting" and self.collect_action is not None
        self._pause_item.Text = "Retomar a coleta" if paused else "Pausar a coleta"
        self._pause_item.Enabled = active and self.pause_action is not None
        self._fox_menu.set_icon(self._pause_item, "play" if paused else "pause")
        self._notify_item.Checked = bool(self.notifications_provider()) if self.notifications_provider else True
        self._logs_item.Enabled = self.logs_action is not None

    def _toggle_notifications(self, *_):
        show = not self._notify_item.Checked
        self._notify_item.Checked = show
        if self.notifications_action:
            threading.Thread(target=self.notifications_action, args=(show,), daemon=True, name="tray-notifications").start()

    def _open_logs(self, *_):
        if self.logs_action:
            try: self.logs_action()
            except Exception: pass

    def _collect(self, *_):
        if self.collect_action: threading.Thread(target=self.collect_action, daemon=True, name="tray-collect").start()

    def _toggle_pause(self, *_):
        paused = bool((self._collector_status() or {}).get("localPaused"))
        if self.pause_action: threading.Thread(target=self.pause_action, args=(not paused,), daemon=True, name="tray-pause").start()

    def _collector_status(self):
        try:
            return self.status_provider() if self.status_provider else None
        except Exception:
            return None

    def _update_text(self):
        text = tray_text(self._collector_status(), self._current_activity)
        # The menu header reads the live status itself when the menu opens.
        if self._notify.Text != text: self._notify.Text = text

    def _poll_tick(self, *_):
        if self._disposed or self._notify is None: return
        if self._effective_activity(self._state.snapshot()) != self._current_activity: self._refresh()
        else: self._update_text()

    def notify(self, title, text, icon="Warning"):
        """Balloon beside the clock; clicking it opens the window."""
        def show():
            from System.Windows.Forms import ToolTipIcon
            if self._disposed or self._notify is None: return
            self._notify.ShowBalloonTip(10000, title, text, getattr(ToolTipIcon, icon))
        try: self._invoke(show)
        except Exception: pass

    def _paint_icon(self):
        key = self._controller.snapshot().frame_key if self._state.snapshot()["fox"]["show"] else "neutral"
        if key != self._last_icon:
            self._notify.Icon = self._neutral if key == "neutral" else self._icons[key]
            # The window and taskbar button follow the resting gestures and state
            # changes. Form.Icon rebuilds its small icon on every set, so the fast
            # working frames (0.6 s) stay on the tray only and keep their cadence.
            window_key = key if key in self._icons else "fox-idle"
            if window_key.startswith("fox-working-"): window_key = "fox-working-1"
            if window_key != self._window_icon and not self._form.IsDisposed:
                self._form.Icon = self._icons[window_key]
                self._window_icon = window_key
            self._last_icon = key
            self._frame_updates += 1

    def _tick(self, *_):
        if not self._disposed: self._paint_icon()

    def _visibility_changed(self, *_):
        if self._disposed: return
        from System.Windows.Forms import FormWindowState
        self._open_item.Enabled = True
        # WebView2 on this host keeps document.hidden=false when Form.Hide runs.
        # Send a boolean-only signal without waiting for JavaScript on the UI
        # thread. Also pause the panel while the native window is minimized.
        core = self._form.browser.webview.CoreWebView2
        if core is not None:
            visible = bool(self._form.Visible) and self._form.WindowState != FormWindowState.Minimized
            core.ExecuteScriptAsync("window.__coletorWindowVisible=" + str(visible).lower()
                + ";window.dispatchEvent(new Event('coletorwindowvisibility'));true")

    def _open(self, *_):
        from System.Windows.Forms import FormWindowState
        if self._disposed: return
        self._form.Show()
        if self._form.WindowState == FormWindowState.Minimized: self._form.WindowState = FormWindowState.Normal
        self._form.Activate()

    def _hide(self, *_):
        if not self._disposed and self._registration_field.GetValue(self._notify): self._form.Hide()

    def hide(self):
        if self._disposed: return {"error": "A bandeja não está disponível. A janela continua aberta."}
        result = {"error": "A bandeja não está disponível. A janela continua aberta."}
        def safely_hide():
            if self._registration_field.GetValue(self._notify):
                self._hide()
                result.clear(); result["hidden"] = True
        self._invoke(safely_hide)
        return result

    def available(self):
        if self._disposed: return False
        result = []
        self._invoke(lambda: result.append(bool(self._registration_field.GetValue(self._notify))))
        return bool(result and result[0])

    def _closing(self, sender, event):
        from System.Windows.Forms import CloseReason
        if self._disposed or event.Cancel: return
        if not hides_on_close(event.CloseReason == CloseReason.UserClosing, self._quitting,
                              self._collector_status(), self._registration_field.GetValue(self._notify)): return
        event.Cancel = True
        self._form.Hide()
        if not self._told_hidden:
            self._told_hidden = True
            self.notify("Coletor de Frequência", "A coleta continua. Para encerrar, use Sair neste ícone.", "Info")

    def _quit(self, *_):
        if self._disposed: return
        self._quitting = True
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
            self._form.FormClosing -= self._closing
            self._form.FormClosed -= self._closed
            self._form.VisibleChanged -= self._visibility_changed
            self._form.Resize -= self._visibility_changed
            self._timer.Tick -= self._tick
            self._poll.Tick -= self._poll_tick
            self._notify.BalloonTipClicked -= self._open
            self._notify.MouseClick -= self._mouse
            self._notify.MouseDoubleClick -= self._mouse
            self._open_item.Click -= self._open
            self._quit_item.Click -= self._quit
            self._collect_item.Click -= self._collect
            self._pause_item.Click -= self._toggle_pause
            self._notify_item.Click -= self._toggle_notifications
            self._logs_item.Click -= self._open_logs
            self._menu.Opening -= self._menu_opening
        if self._notify is not None and self._timer is not None: resources.append(detach_events)
        if self._timer: resources += [self._timer.Stop, self._timer.Dispose]
        if self._poll: resources += [self._poll.Stop, self._poll.Dispose]
        if self._notify: resources += [lambda: setattr(self._notify, "Visible", False), self._notify.Dispose]
        if self._menu: resources += [self._menu.Dispose]
        if self._fox_menu: resources += [self._fox_menu.dispose]
        resources += [icon.Dispose for icon in set(self._icons.values())]
        if hasattr(self, "_neutral"): resources += [self._neutral.Dispose]
        self._cleanup_ok = True
        for action in resources:
            try: action()
            except Exception: self._cleanup_ok = False
        self._icons.clear()

    def stop(self):
        if not self._disposed: self._invoke(self._dispose)
