import pin_extract


def test_extract_keywords_handles_polish_characters():
    keywords = pin_extract.extract_keywords("Gołąbki z kapustą i mięsem")
    tokens = {token.strip() for token in keywords.split(",") if token.strip()}

    assert "gołąbki" in tokens
    assert "kapustą" in tokens
    assert "mięsem" in tokens


def test_normalize_openai_keywords_handles_unicode_terms():
    keywords = pin_extract.normalize_openai_keywords(
        ["Sernik", "Żurawina", "i", "Sernik"]
    )

    assert keywords == ["sernik", "żurawina"]


def test_openai_prompt_requires_original_language():
    prompt = pin_extract.build_openai_prompt({"pin_title": "Sernik"})
    lowered = prompt.lower()

    assert "original language" in lowered
    assert "do not translate" in lowered
