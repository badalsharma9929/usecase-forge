from usecase_forge.tools import datasets
from usecase_forge.tools.datasets import keyword_variants
from usecase_forge.tools.web import clean_markdown
from usecase_forge.schemas import DatasetCandidate


def test_clean_markdown_keeps_text_and_drops_urls():
    raw = (
        "Title: Learn\n\n"
        "[![Image 4](https://cdn.x.com/a.png)](https://shop.x.com/?utm=1) Book a [FREE class](https://x.com/book)\n\n"
        "![logo](https://cdn.x.com/logo.svg)\n\n"
        "Visit https://x.com/about?ref=home today\n\n\n\n|  |"
    )
    cleaned = clean_markdown(raw)
    assert "http" not in cleaned and "![" not in cleaned
    assert "Book a FREE class" in cleaned
    assert "Visit today" in cleaned
    assert "\n\n\n" not in cleaned and not cleaned.endswith("|")


def test_keyword_variants_drop_filler_and_add_windows():
    assert keyword_variants("lead conversion dataset") == ["lead conversion"]
    assert keyword_variants("time series slot prediction") == [
        "time series slot prediction", "time series", "series slot", "slot prediction",
    ]
    assert keyword_variants("data") == []


def test_search_falls_back_to_shorter_variant(monkeypatch):
    tried = []

    def fake_hf(keyword, limit):
        tried.append(keyword)
        if keyword == "slot prediction":
            return [DatasetCandidate(source="Hugging Face", name="a/b", url="u", keyword=keyword)]
        return []

    monkeypatch.setattr(datasets, "search_huggingface", fake_hf)
    monkeypatch.setattr(datasets, "search_kaggle", lambda k, l: [])
    found = datasets.search_datasets("time series slot prediction")
    assert [d.name for d in found] == ["a/b"]
    assert tried == ["time series slot prediction", "time series", "series slot", "slot prediction"]
