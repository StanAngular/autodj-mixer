"""Тесты smart_mixer (пока точечно). resolve_camelot: curated primary, detect fallback."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import smart_mixer as m


class TestResolveCamelot:
    def test_curated_wins(self):
        assert m.resolve_camelot("8A", "5A") == "8A"        # курированный primary
    def test_empty_curated_falls_to_detected(self):
        assert m.resolve_camelot("", "5A") == "5A"
        assert m.resolve_camelot(None, "5A") == "5A"
    def test_unknown_curated_falls_to_detected(self):
        assert m.resolve_camelot("?", "5A") == "5A"         # '?' не валиден
    def test_whitespace_curated_falls_to_detected(self):
        assert m.resolve_camelot("  ", "5A") == "5A"


class TestA1FSnapBar:
    # сетка: intro(0-1) verse(2-3) break(4-5) chorus(6-7) outro(8-9)
    LABELS = ["intro", "intro", "verse", "verse", "break", "break", "chorus", "chorus", "outro", "outro"]

    def test_snaps_exit_to_outro_start(self):
        bar, lab = m.a1f_snap_bar(9, self.LABELS, m.A1F_EXIT_LABELS, window=4)
        assert bar == 8 and lab == "outro"            # начало outro рядом с энергетич. bar9
    def test_snaps_exit_to_break(self):
        bar, lab = m.a1f_snap_bar(5, self.LABELS, m.A1F_EXIT_LABELS, window=2)
        assert bar == 4 and lab == "break"            # начало break
    def test_entry_snaps_to_intro(self):
        bar, lab = m.a1f_snap_bar(1, self.LABELS, m.A1F_ENTRY_LABELS, window=2)
        assert bar == 0 and lab == "intro"
    def test_no_match_in_window_keeps_anchor(self):
        bar, lab = m.a1f_snap_bar(3, self.LABELS, m.A1F_EXIT_LABELS, window=0)
        assert bar == 3 and lab is None               # окно 0, на verse — не трогаем
    def test_none_labels_keeps_anchor(self):
        assert m.a1f_snap_bar(5, None, m.A1F_EXIT_LABELS) == (5, None)
    def test_none_bar(self):
        assert m.a1f_snap_bar(None, self.LABELS, m.A1F_EXIT_LABELS) == (None, None)
    def test_picks_nearest_boundary(self):
        # outro начинается в 8; verse-как-prefer нет; ближайший break(4) от bar6 vs outro(8) → break ближе? нет: |4-6|=2,|8-6|=2 → break (first found, d равны → break т.к. меньший индекс не гарантирован; проверим что вернулась валидная граница)
        bar, lab = m.a1f_snap_bar(6, self.LABELS, m.A1F_EXIT_LABELS, window=2)
        assert lab in ("break", "outro") and bar in (4, 8)
