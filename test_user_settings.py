import json
from pathlib import Path
from user_settings import get_search_mode, set_search_mode
import user_settings


def test_search_mode_persists_across_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(user_settings, 'SEARCH_MODES_FILE', tmp_path / 'search_modes.json')

    assert get_search_mode(111) is False
    set_search_mode(111, True)
    assert get_search_mode(111) is True
    assert get_search_mode(222) is False

    set_search_mode(111, False)
    assert get_search_mode(111) is False
    # כבוי = לא נשמר בקובץ
    data = json.loads(Path(tmp_path / 'search_modes.json').read_text(encoding='utf-8'))
    assert '111' not in data
