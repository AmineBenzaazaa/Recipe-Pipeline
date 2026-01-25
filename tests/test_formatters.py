from src.formatters import format_faq_text
from src.models import FAQItem


def test_format_faq_text():
    items = [
        FAQItem(question="What is this?", answer="It is a test."),
        FAQItem(question="How do I make it?", answer="Follow the steps."),
    ]
    text = format_faq_text(items)
    expected = "Q: What is this?\nA: It is a test.\n\nQ: How do I make it?\nA: Follow the steps."
    assert text == expected
