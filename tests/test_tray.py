"""Portable contract tests of the tray animation and presenter (no Windows needed)."""
from pathlib import Path
import tempfile
import unittest

from coletor.tray_animation import (
    AnimationController, AnimationPolicy, FRAME_KEYS, IDLE_SEQUENCE,
    TrayPresenter, TrayState, WORKING_SEQUENCE, STATIC_FRAMES,
    icon_paths, resolve_icon_paths, tooltip_for,
)


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
        self.assertGreaterEqual(frames.count("fox-blink"), 4)
        for gesture in ("fox-ear", "fox-ear-right", "fox-ears", "fox-bob"):
            self.assertIn(gesture, frames)
        # Only head frames exist at icon size; every frame has a real asset.
        self.assertTrue(set(frames) <= {"fox-idle", "fox-blink", "fox-ear", "fox-ear-right",
                                        "fox-ears", "fox-bob"})
        # Lively, not frantic: more than half the beats rest on the neutral face.
        self.assertGreaterEqual(frames.count("fox-idle") / len(frames), 0.5)
        # Frequent but calm gestures: at most 1.8 seconds of rest,
        # including the loop boundary, without speeding up individual frames.
        rest = 0
        for frame in frames + frames:
            rest = rest + 1 if frame == "fox-idle" else 0
            self.assertLessEqual(rest, 3)
        self.assertEqual(frames.index("fox-blink"), 2)
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
            self.assertEqual(resolved["fox-bob"], paths["fox-idle"])
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



if __name__ == "__main__": unittest.main()
