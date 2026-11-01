import pytest

from probe import guard, promptcheck


@pytest.mark.parametrize(
    "text",
    [
        "TIC 123456789",
        "tic123456789",
        "TOI-1234.01",
        "Kepler-10",
        "WASP-12 b",
        "J1555+2726",
        "ILTJ155500+272600",
        "NGC 6543",
        "M57",
        "a target at RA 238.853",
        "27.443",
        "15:55:24",
        "observed by TESS",
        "a LoTSS DR3 map",
        "from the MAST archive",
        "cutout.fits",
        "clip_0042.mp4",
        "https://example.org/x",
        "1234567",
        "ESP_012345_1234",
    ],
)
def test_refuses_what_could_identify_an_example(text):
    with pytest.raises(guard.LeakError):
        guard.check_text(text)


def test_error_names_the_kind_not_the_text():
    with pytest.raises(guard.LeakError) as e:
        guard.check_text("look at TIC 123456789")
    assert "object id" in str(e.value)
    assert "123456789" not in str(e.value)


@pytest.mark.parametrize(
    "text",
    [
        "Is there a ring-like structure in this radio image at 6 or 20 arcsec resolution?",
        "These two images show the same patch of sky in radio continuum, 6 arcminutes on a side.",
    ],
)
def test_passes_ordinary_prompts(text):
    assert guard.find_leak(text) is None


def test_promptcheck_finds_a_leak_in_code(tmp_path):
    source = 'MY_PROMPT = "what is TIC 123?"\nspec = make(prompt="fine")\nOTHER = "TIC 123"\n'
    assert {t for _, t in promptcheck.prompts_in(source)} == {"what is TIC 123?", "fine"}
    (tmp_path / "probe").mkdir()
    (tmp_path / "probe" / "bad.py").write_text(source)
    bad = promptcheck.problems(tmp_path)
    assert len(bad) == 1 and "probe/bad.py:1" in bad[0]


def test_promptcheck_is_clean_on_this_repo_and_guards_every_canary():
    assert promptcheck.problems() == []
