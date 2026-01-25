import csv
from pathlib import Path

from src.csv_writer import append_row, load_template_headers


def test_csv_writer_headers(tmp_path: Path):
    template_path = tmp_path / "template.csv"
    output_path = tmp_path / "out.csv"

    headers = [
        "focus_keyword",
        "topic",
        "faq_text",
        "recipe_text",
        "model_name",
        "temperature",
        "target_words",
        "use_multi_call",
        "featured_image_prompt",
        "instructions_process_image_prompt",
        "serving_image_prompt",
        "WPRM_recipecard_image_prompt",
        "featured_image_generated_url",
        "instructions_process_image_generated_url",
        "serving_image_generated_url",
        "WPRM_recipe)card_url",
    ]

    with template_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)

    loaded_headers = load_template_headers(str(template_path))
    assert loaded_headers == headers

    row = {
        "focus_keyword": "test",
        "topic": "topic",
        "faq_text": "faq",
        "recipe_text": "recipe",
        "model_name": "gpt-4.1",
        "temperature": 0.6,
        "target_words": 1800,
        "use_multi_call": True,
        "featured_image_prompt": "prompt1",
        "instructions_process_image_prompt": "prompt2",
        "serving_image_prompt": "prompt3",
        "WPRM_recipecard_image_prompt": "prompt4",
        "featured_image_generated_url": "url1",
        "instructions_process_image_generated_url": "url2",
        "serving_image_generated_url": "url3",
        "WPRM_recipe)card_url": "url4",
    }

    append_row(str(output_path), headers, row)

    with output_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    assert rows[0] == headers
    assert rows[1] == [str(row.get(h, "")) for h in headers]
