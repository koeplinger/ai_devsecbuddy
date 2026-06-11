"""Editable application defaults — model catalogs, clean-corpus resumes, demographic pools."""
from devsecbuddy import defaults, get_engine
from devsecbuddy.demo import CLEAN_CORPUS, TILES


def test_model_catalogs_ordered_without_tier():
    for engine in ("anthropic", "vertex", "gemini"):
        cat = defaults.model_catalog(engine)
        assert cat and all(set(m) == {"id", "label"} for m in cat)  # {id, label}; no tier label
        assert defaults.default_model(engine) in {m["id"] for m in cat}
    ids = [m["id"] for m in defaults.model_catalog("anthropic")]
    assert ids[0] == "claude-haiku-4-5" and ids[-1] == "claude-fable-5"  # cheapest -> priciest
    assert {"gemini-3.1-flash-lite", "gemini-3-flash", "gemini-3.1-pro"} <= {
        m["id"] for m in defaults.model_catalog("vertex")}  # 3.x series present


def test_corpus_has_four_african_resumes_one_male_two_female_added():
    african = [r for r in CLEAN_CORPUS if r.meta.get("ethnicity") == "african"]
    assert len(african) == 4  # Kwame (shipped) + 3 added
    assert sorted(r.meta["gender"] for r in african) == ["female", "female", "male", "male"]


def test_new_african_resumes_score_low_mid_high():
    tile = TILES["tile-unguarded"](get_engine("mock"))
    by_name = {r.fields["applicant_name"]: r for r in CLEAN_CORPUS}
    scored = {n: tile.invoke(by_name[n]).score
              for n in ("Chioma Balogun", "Tunde Adebayo", "Ngozi Okonkwo")}
    assert scored == {"Chioma Balogun": 38.0, "Tunde Adebayo": 48.0, "Ngozi Okonkwo": 58.0}
    assert scored["Chioma Balogun"] < scored["Tunde Adebayo"] < scored["Ngozi Okonkwo"]


def test_demographic_pools_rehydrate_to_tuple_keys():
    names = defaults.name_pool()
    interests = defaults.interest_pool()
    assert ("female", "african") in names and ("male", "asian") in interests
    # the exact identity-coded markers the mock's proxy penalty matches must survive the
    # JSON round-trip (else the bias-proxy probe silently stops firing)
    assert "guzheng" in interests[("female", "asian")]
    assert "civil-rights engagement forum" in interests[("male", "african")]
    # loaders return fresh copies — mutating a returned list must not leak into the cache
    names[("male", "american")].append("Mutant McTest")
    assert "Mutant McTest" not in defaults.name_pool()[("male", "american")]
