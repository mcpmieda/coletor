"""Portable contract tests. Fake Win32 calls are NOT Windows desktop validation."""
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from coletor.tray_animation import (
    AnimationController, AnimationPolicy, FRAME_KEYS, IDLE_SEQUENCE,
    TrayPresenter, TrayState, WORKING_SEQUENCE, STATIC_FRAMES,
    icon_paths, resolve_icon_paths, tooltip_for,
)
from coletor.tray import WindowsTray, ID_OPEN, ID_QUIT, WM_REFRESH, WM_TRAY


class Clock:
    value = 0.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


class Sink:
    def __init__(self):
        self.calls = []
        self.fail_add = self.fail_modify = False
    def add(self, presentation):
        self.calls.append(("add", presentation))
        if self.fail_add: raise OSError("shell unavailable")
    def modify(self, presentation):
        self.calls.append(("modify", presentation))
        if self.fail_modify: raise OSError("shell unavailable")
    def remove(self): self.calls.append(("remove", None))


class AnimationTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.controller = AnimationController(clock=self.clock)

    def test_default_is_idle_not_a_sync_success(self):
        view = self.controller.snapshot()
        self.assertEqual(view.state, TrayState.IDLE)
        self.assertEqual(view.frame_key, "fox-idle")
        self.assertEqual(view.badge, "none")
        self.assertIn("Aguardando", view.tooltip)
        self.assertIn("Modo de teste", view.tooltip)
        self.assertIn("Coleta desligada", view.tooltip)
        self.assertNotIn("sincronizado", view.tooltip.lower())

    def test_working_has_four_distinct_frames_with_constant_badge(self):
        self.controller.set_state("working")
        frames = []
        for _ in range(4):
            view = self.controller.snapshot()
            frames.append(view.frame_key)
            self.assertEqual(view.badge, "progress")
            self.clock.advance(.6)
        self.assertEqual(tuple(frames), WORKING_SEQUENCE)
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-1")

    def test_idle_gestures_are_spaced_and_loop_to_rest(self):
        frames = []
        for _ in IDLE_SEQUENCE:
            frames.append(self.controller.snapshot().frame_key)
            self.clock.advance(.6)
        self.assertEqual(tuple(frames), IDLE_SEQUENCE)
        self.assertEqual(frames.count("fox-blink"), 3)  # one blink, then a double blink
        ear = frames.index("fox-ear")
        self.assertEqual(frames[ear:ear + 3], ["fox-ear", "fox-idle", "fox-ear"])  # ear twitch
        # Only head frames exist at icon size; every frame has a real asset.
        self.assertTrue(set(frames) <= {"fox-idle", "fox-blink", "fox-ear"})
        # Visible but calm (owner's request): the fox rests in at least 7 of 10 frames.
        self.assertGreaterEqual(frames.count("fox-idle") / len(frames), .7)
        self.assertEqual(self.controller.snapshot().frame_key, "fox-idle")

    def test_no_rapid_boundary_updates(self):
        self.controller.set_state("working")
        self.clock.value = .59
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-1")
        self.clock.value = 1.19
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-2")
        self.clock.value = 1.21
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-2")
        self.clock.value = 1.79
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-3")

    def test_delayed_tick_skips_frames_without_a_catch_up_burst(self):
        self.controller.set_state("working")
        self.clock.value = 6.0
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-3")
        for _ in range(20):
            self.assertEqual(self.controller.snapshot().frame_key, "fox-working-3")

    def test_same_state_and_detail_updates_do_not_reset_animation(self):
        self.controller.set_state("working")
        self.clock.advance(.6)
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-2")
        self.assertFalse(self.controller.set_state("working"))
        self.assertTrue(self.controller.set_state("working", "Prévia local"))
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-2")

    def test_state_change_resets_frame_immediately(self):
        self.controller.set_state("working")
        self.clock.advance(.6)
        self.controller.snapshot()
        self.controller.set_state("error")
        self.assertEqual(self.controller.snapshot().frame_key, "fox-error")
        self.controller.set_state("working")
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-1")

    def test_paused_and_error_never_flash(self):
        for state, badge in (("paused", "pause"), ("error", "exclamation")):
            self.controller.set_state(state)
            initial = self.controller.snapshot()
            self.assertEqual(initial.badge, badge)
            self.clock.advance(10000)
            self.assertEqual(self.controller.snapshot(), initial)

    def test_reduced_motion_and_disabled_keep_semantic_state(self):
        for policy in (AnimationPolicy(enabled=False), AnimationPolicy(reduced_motion=True)):
            self.controller.set_policy(policy)
            for state in TrayState:
                self.controller.set_state(state)
                initial = self.controller.snapshot()
                self.clock.advance(100)
                self.assertEqual(self.controller.snapshot(), initial)
                self.assertEqual(initial.state, state)

    def test_reenable_restarts_gently(self):
        self.controller.set_state("working")
        self.clock.advance(1.2)
        self.controller.snapshot()
        self.controller.set_policy(AnimationPolicy(enabled=False))
        self.clock.advance(100)
        self.controller.set_policy(AnimationPolicy())
        self.assertEqual(self.controller.snapshot().frame_key, "fox-working-1")
        self.assertFalse(self.controller.set_policy(AnimationPolicy()))

    def test_reject_unknown_states_and_invalid_policy(self):
        with self.assertRaises(ValueError): self.controller.set_state("synced")
        with self.assertRaises(TypeError): self.controller.set_state("idle", None)
        for interval in (0, .59, -1, float("nan"), float("inf"), 61):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                AnimationPolicy(frame_interval=interval)
        with self.assertRaises(TypeError): AnimationPolicy(enabled="yes")
        with self.assertRaises(TypeError): self.controller.set_policy(None)
        with self.assertRaises(TypeError): AnimationController(policy="yes")

    def test_clock_regression_does_not_animate_backwards(self):
        self.controller.set_state("working")
        self.clock.value = .6
        view = self.controller.snapshot()
        self.clock.value = -.5
        self.assertEqual(self.controller.snapshot(), view)

    def test_tooltip_is_redundant_clean_and_utf16_bounded(self):
        text = tooltip_for(TrayState.PAUSED, "Linha\ncom\x00controles " + "🦊" * 150)
        self.assertIn("Pausado", text)
        self.assertNotIn("\x00", text)
        self.assertNotIn("\n", text)
        self.assertLessEqual(len(text.encode("utf-16-le")), 254)
        self.assertNotIn("\ufffd", text)

    def test_manifest_contains_only_bounded_local_ico_paths(self):
        paths = icon_paths(Path("/synthetic/fox-icons"))
        self.assertEqual(set(paths), set(FRAME_KEYS))
        self.assertEqual(len(paths), len(FRAME_KEYS))
        for key, path in paths.items():
            self.assertEqual(path.parent, Path("/synthetic/fox-icons"))
            self.assertEqual(path.name, f"{key}.ico")

    def test_optional_frames_fall_back_without_losing_state_badges(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = icon_paths(Path(directory))
            for key in STATIC_FRAMES.values(): paths[key].touch()
            resolved = resolve_icon_paths(Path(directory))
            self.assertEqual(resolved["fox-blink"], paths["fox-idle"])
            self.assertEqual(resolved["fox-ear"], paths["fox-idle"])
            self.assertEqual(resolved["fox-working-4"], paths["fox-working-1"])
            self.assertEqual(resolved["fox-error"], paths["fox-error"])
            self.assertEqual(resolved["fox-paused"], paths["fox-paused"])

    def test_base_frames_remain_required(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = icon_paths(Path(directory))
            for path in paths.values(): path.touch()
            paths["fox-error"].unlink()
            with self.assertRaisesRegex(FileNotFoundError, "fox-error.ico"):
                resolve_icon_paths(Path(directory))


class PresenterTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.sink = Clock(), Sink()
        self.controller = AnimationController(clock=self.clock)
        self.presenter = TrayPresenter(self.controller, self.sink)

    def test_only_redraws_changed_presentation(self):
        self.assertTrue(self.presenter.update())
        self.assertFalse(self.presenter.update())
        self.clock.advance(.6)
        self.assertFalse(self.presenter.update())  # idle holds same pixels
        self.controller.set_state("working")
        self.assertTrue(self.presenter.update())
        self.assertEqual([c[0] for c in self.sink.calls], ["add", "modify"])

    def test_explorer_recovery_readds_current_state_and_tip(self):
        self.presenter.update()
        self.controller.set_state("paused", "Prévia")
        self.presenter.taskbar_created()
        self.assertEqual([c[0] for c in self.sink.calls], ["add", "add"])
        self.assertEqual(self.sink.calls[-1][1].state, TrayState.PAUSED)
        self.assertIn("Prévia", self.sink.calls[-1][1].tooltip)

    def test_failed_add_is_retried_without_losing_state(self):
        self.sink.fail_add = True
        with self.assertRaises(OSError): self.presenter.update()
        self.sink.fail_add = False
        self.assertTrue(self.presenter.update())
        self.assertEqual([c[0] for c in self.sink.calls], ["add", "add"])

    def test_failed_modify_invalidates_registration_and_retries_add(self):
        self.presenter.update()
        self.controller.set_state("error")
        self.sink.fail_modify = True
        with self.assertRaises(OSError): self.presenter.update()
        self.sink.fail_modify = False
        self.presenter.update()
        self.assertEqual([c[0] for c in self.sink.calls], ["add", "modify", "remove", "add"])

    def test_close_is_idempotent_and_closed_presenter_can_readd(self):
        self.presenter.close()
        self.presenter.update()
        self.presenter.close()
        self.presenter.close()
        self.assertEqual([c[0] for c in self.sink.calls], ["add", "remove"])
        self.presenter.update()
        self.assertEqual(self.sink.calls[-1][0], "add")


CON = SimpleNamespace(WM_CLOSE=16, WM_DESTROY=2, WM_TIMER=275, WM_NULL=0,
                      WM_LBUTTONDBLCLK=515, WM_CONTEXTMENU=123, WM_RBUTTONUP=517,
                      SM_CXSMICON=49, IMAGE_ICON=1, LR_LOADFROMFILE=16,
                      MF_STRING=0, MF_DISABLED=2, MF_SEPARATOR=2048,
                      TPM_RETURNCMD=256, TPM_NONOTIFY=128)


class FakeGui:
    error = OSError
    NIF_ICON, NIF_MESSAGE, NIF_TIP = 2, 1, 4
    NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION, NIM_SETFOCUS = range(5)

    def __init__(self):
        self.events, self.queue = [], queue.Queue()
        self.processed = queue.Queue()
        self.handles = 0
        self.alive = False
        self.command = ID_OPEN
        self.fail_on_load = None
    def WNDCLASS(self): return SimpleNamespace()
    def RegisterWindowMessage(self, name): return 49153
    def RegisterClass(self, wc):
        self.callback = wc.lpfnWndProc
        self.events.append(("register", wc.lpszClassName))
        return 1
    def UnregisterClass(self, name, instance): self.events.append(("unregister", name))
    def CreateWindow(self, *args):
        self.alive = True
        return 101
    def LoadImage(self, *args):
        self.handles += 1
        if self.handles == self.fail_on_load: raise OSError("test load failure")
        self.events.append(("load", self.handles))
        return self.handles
    def DestroyIcon(self, handle): self.events.append(("destroy_icon", handle))
    def Shell_NotifyIcon(self, operation, data):
        self.events.append(("shell", operation, data, threading.get_ident()))
    def PostMessage(self, *message): self.queue.put(message)
    def PostQuitMessage(self, code): self.queue.put(None)
    def PumpMessages(self):
        while True:
            message = self.queue.get(timeout=5)
            if message is None: return
            self.callback(*message)
            self.processed.put(message)
    def IsWindow(self, hwnd): return self.alive
    def DestroyWindow(self, hwnd):
        self.events.append(("destroy_window", hwnd))
        self.alive = False
        self.callback(hwnd, CON.WM_DESTROY, 0, 0)
    def DefWindowProc(self, *args): return 0
    def CreatePopupMenu(self): return 201
    def AppendMenu(self, *args): self.events.append(("menu_item", args))
    def GetCursorPos(self): return (10, 20)
    def SetForegroundWindow(self, hwnd): pass
    def TrackPopupMenu(self, *args): return self.command
    def DestroyMenu(self, menu): self.events.append(("destroy_menu", menu))


class WindowsAdapterContractTests(unittest.TestCase):
    def make_tray(self, **options):
        return WindowsTray(on_open=lambda: None, on_quit=lambda: None,
                           dispatch=lambda callback: None, **options)

    def test_construct_and_stop_do_not_create_threads_or_native_handles(self):
        before = set(threading.enumerate())
        tray = self.make_tray()
        tray.stop()
        tray.stop()
        self.assertFalse(tray.running)
        self.assertEqual(set(threading.enumerate()), before)
        self.assertIsNone(tray._gui)

    def test_disabled_by_default_even_on_windows(self):
        with patch("coletor.tray.sys.platform", "win32"):
            with self.assertRaisesRegex(RuntimeError, "desativada"):
                self.make_tray().start()

    def test_platform_guard_precedes_native_import_or_asset_access(self):
        with patch("coletor.tray.sys.platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "requer Windows"):
                self.make_tray(enabled=True).start()

    def test_missing_assets_fail_before_native_thread(self):
        with tempfile.TemporaryDirectory() as directory, patch("coletor.tray.sys.platform", "win32"):
            tray = self.make_tray(enabled=True, asset_directory=Path(directory))
            with self.assertRaisesRegex(FileNotFoundError, "fox-idle.ico"): tray.start()
            self.assertIsNone(tray._thread)

    def fake_runtime(self, directory, gui):
        for path in icon_paths(Path(directory)).values(): path.touch()
        api = SimpleNamespace(GetModuleHandle=lambda _: 1, GetSystemMetrics=lambda _: 16)
        timer = SimpleNamespace(
            SetTimer=lambda *a: gui.events.append(("timer_start", a)) or 1,
            KillTimer=lambda *a: gui.events.append(("timer_stop", a)) or 1)
        def prepare(tray): tray._user32 = timer
        return (patch("coletor.tray.sys.platform", "win32"),
                patch.dict(sys.modules, {"win32api": api, "win32con": CON, "win32gui": gui}),
                patch.object(WindowsTray, "_prepare_user32", prepare))

    def test_fake_native_lifecycle_cleans_every_handle_on_one_thread(self):
        gui = FakeGui()
        with tempfile.TemporaryDirectory() as directory:
            patches = self.fake_runtime(directory, gui)
            with patches[0], patches[1], patches[2]:
                tray = self.make_tray(enabled=True, asset_directory=Path(directory))
                tray.start()
                self.assertTrue(tray.running)
                with self.assertRaises(RuntimeError): tray.start()
                tray.stop()
                tray.stop()
                self.assertFalse(tray.running)
                with self.assertRaises(RuntimeError): tray.start()
        loaded = {e[1] for e in gui.events if e[0] == "load"}
        destroyed = {e[1] for e in gui.events if e[0] == "destroy_icon"}
        self.assertEqual(loaded, destroyed)
        self.assertEqual(len(loaded), len(FRAME_KEYS))
        shell_events = [e for e in gui.events if e[0] == "shell"]
        self.assertEqual([e[1] for e in shell_events], [gui.NIM_ADD, gui.NIM_SETVERSION, gui.NIM_DELETE])
        self.assertEqual(len({e[3] for e in shell_events}), 1)
        self.assertNotEqual(shell_events[0][3], threading.get_ident())
        self.assertLess(gui.events.index(shell_events[-1]),
                        next(i for i, e in enumerate(gui.events) if e[0] == "destroy_window"))
        self.assertTrue(any(e[0] == "timer_stop" for e in gui.events))
        self.assertTrue(any(e[0] == "unregister" for e in gui.events))

    def test_partial_native_start_failure_releases_loaded_icons_and_thread(self):
        gui = FakeGui()
        gui.fail_on_load = 3
        with tempfile.TemporaryDirectory() as directory:
            patches = self.fake_runtime(directory, gui)
            with patches[0], patches[1], patches[2]:
                tray = self.make_tray(enabled=True, asset_directory=Path(directory))
                with self.assertLogs("coletor.tray", level="WARNING"):
                    with self.assertRaisesRegex(RuntimeError, "Não foi possível"): tray.start()
                self.assertFalse(tray.running)
                self.assertEqual(tray.last_error, "native-loop-failed")
        self.assertEqual([e[1] for e in gui.events if e[0] == "destroy_icon"], [1, 2])

    def test_fallback_aliases_share_and_release_only_four_handles(self):
        gui = FakeGui()
        with tempfile.TemporaryDirectory() as directory:
            patches = self.fake_runtime(directory, gui)
            for key, path in icon_paths(Path(directory)).items():
                if key not in STATIC_FRAMES.values(): path.unlink()
            with patches[0], patches[1], patches[2]:
                tray = self.make_tray(enabled=True, asset_directory=Path(directory))
                tray.start()
                tray.stop()
        destroyed = [e[1] for e in gui.events if e[0] == "destroy_icon"]
        self.assertEqual(len(destroyed), 4)
        self.assertEqual(len(set(destroyed)), 4)

    def test_fake_taskbar_restart_reloads_handles_and_keeps_pause_state(self):
        gui = FakeGui()
        with tempfile.TemporaryDirectory() as directory:
            patches = self.fake_runtime(directory, gui)
            with patches[0], patches[1], patches[2]:
                tray = self.make_tray(enabled=True, asset_directory=Path(directory))
                tray.set_state("paused")
                tray.start()
                gui.PostMessage(101, 49153, 0, 0)
                self.assertEqual(gui.processed.get(timeout=2)[1], 49153)
                tray.stop()
        added = [e for e in gui.events if e[0] == "shell" and e[1] == gui.NIM_ADD]
        self.assertEqual(len(added), 2)
        self.assertTrue(all("Pausado" in e[2][5] for e in added))
        loaded = [e[1] for e in gui.events if e[0] == "load"]
        destroyed = [e[1] for e in gui.events if e[0] == "destroy_icon"]
        self.assertEqual(sorted(loaded), sorted(destroyed))
        self.assertEqual(len(loaded), 2 * len(FRAME_KEYS))

    def test_start_timeout_requests_stop_and_leaves_no_running_thread(self):
        gui = FakeGui()
        def waiting_start(tray): tray._stop_requested.wait(2)
        with tempfile.TemporaryDirectory() as directory:
            patches = self.fake_runtime(directory, gui)
            with patches[0], patches[1], patches[2], patch.object(WindowsTray, "_run", waiting_start):
                tray = self.make_tray(enabled=True, asset_directory=Path(directory))
                with self.assertRaises(TimeoutError): tray.start(timeout=.05)
                self.assertFalse(tray.running)
                self.assertTrue(tray._stop_requested.is_set())

    def test_stop_timeout_is_visible_and_does_not_allow_second_start(self):
        gui, blocked = FakeGui(), threading.Event()
        def slow_exit(tray):
            tray._ready.set()
            blocked.wait(2)
        with tempfile.TemporaryDirectory() as directory:
            patches = self.fake_runtime(directory, gui)
            with patches[0], patches[1], patches[2], patch.object(WindowsTray, "_run", slow_exit):
                tray = self.make_tray(enabled=True, asset_directory=Path(directory))
                tray.start()
                try:
                    with self.assertRaises(TimeoutError): tray.stop(timeout=.01)
                    self.assertTrue(tray.running)
                    with self.assertRaises(RuntimeError): tray.start()
                finally:
                    blocked.set()
                    tray.stop()
                self.assertFalse(tray.running)

    def test_cleanup_continues_when_one_owned_handle_fails(self):
        gui = FakeGui()
        original_destroy = gui.DestroyIcon
        def destroy(handle):
            original_destroy(handle)
            if handle == 1: raise OSError("synthetic handle failure")
        gui.DestroyIcon = destroy
        with tempfile.TemporaryDirectory() as directory:
            patches = self.fake_runtime(directory, gui)
            with patches[0], patches[1], patches[2]:
                tray = self.make_tray(enabled=True, asset_directory=Path(directory))
                tray.start()
                with self.assertLogs("coletor.tray", level="WARNING"): tray.stop()
                self.assertFalse(tray.running)
        self.assertEqual(len([e for e in gui.events if e[0] == "destroy_icon"]), len(FRAME_KEYS))
        self.assertTrue(any(e[0] == "unregister" for e in gui.events))

    def test_open_and_quit_callbacks_are_dispatched_without_launching_processes(self):
        gui, callbacks, called = FakeGui(), queue.Queue(), []
        with tempfile.TemporaryDirectory() as directory:
            patches = self.fake_runtime(directory, gui)
            with patches[0], patches[1], patches[2]:
                tray = WindowsTray(on_open=lambda: called.append("open"),
                                   on_quit=lambda: called.append("quit"), dispatch=callbacks.put,
                                   enabled=True, asset_directory=Path(directory))
                tray.start()
                gui.PostMessage(101, WM_TRAY, 0, CON.WM_LBUTTONDBLCLK)
                callbacks.get(timeout=2)()
                self.assertEqual(called, ["open"])
                gui.command = ID_QUIT
                gui.PostMessage(101, WM_TRAY, 0, CON.WM_CONTEXTMENU)
                callbacks.get(timeout=2)()
                tray.stop()
                self.assertEqual(called, ["open", "quit"])
                self.assertFalse(tray.running)
                self.assertIn(("destroy_menu", 201), gui.events)


if __name__ == "__main__": unittest.main()
