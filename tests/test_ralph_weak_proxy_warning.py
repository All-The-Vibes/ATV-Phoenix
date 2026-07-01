import pathlib
REPO  = pathlib.Path(__file__).parent.parent
RALPH = REPO / 'dist' / 'ralph' / 'phoenix-ralph.ps1'

def test_checks_backlog():
    src = RALPH.read_text(encoding='utf-8')
    assert 'done -eq' in src or '.done -eq' in src

def test_emits_warn_after_accept():
    src = RALPH.read_text(encoding='utf-8')
    i = src.find('done-check ACCEPTED')
    assert i != -1 and 'Warn' in src[i:]

def test_under_specified_in_warning():
    src = RALPH.read_text(encoding='utf-8')
    assert 'UNDER-SPECIFIED' in src or 'under-specified' in src

def test_absence_or_legacy():
    src = RALPH.read_text(encoding='utf-8').lower()
    assert 'absence' in src or 'legacy' in src or 'negative' in src

def test_warning_is_nonfatal():
    src = RALPH.read_text(encoding='utf-8')
    i = src.find('done-check ACCEPTED')
    post = src[i:i+1500]
    assert post.find('Warn') != -1 and post.find('break') > post.find('Warn')
