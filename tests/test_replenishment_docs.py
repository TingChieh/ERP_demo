from pathlib import Path


README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def test_readme_documents_replenishment_rules_and_safety_boundaries():
    required_phrases = (
        "target_stock",
        "recommended_purchase_qty",
        "pending_receipt",
        "7-day average",
        "14 days",
        "simple rule",
        "not machine learning",
        "user confirmation",
        "draft creation",
    )

    for phrase in required_phrases:
        assert phrase in README
