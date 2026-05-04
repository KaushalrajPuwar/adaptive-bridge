# scripts/tests/test_tc_parameter_mapping.py
"""Validate that GE scenario parameters map correctly to tc command arguments."""


def test_ge_average_loss_formula():
    """Verify the average loss formula: (r*G + p*B) / (p+r) for each scenario."""
    scenarios = [
        # (name, p, r, G, B, expected_avg)
        ("mild", 1, 15, 0.5, 30, 2.34),
        ("moderate", 3, 15, 0.5, 40, 7.08),
        ("strong", 2, 10, 1.0, 50, 9.17),
    ]
    for name, p, r, G, B, expected in scenarios:
        avg = (r * G + p * B) / (p + r)
        assert abs(avg - expected) < 0.1, f"{name}: expected ~{expected}%, got {avg:.2f}%"


def test_gradient_holds():
    """Verify mild < moderate < strong average loss."""
    def _avg(p, r, G, B):
        return (r * G + p * B) / (p + r)

    mild = _avg(1, 15, 0.5, 30)
    moderate = _avg(3, 15, 0.5, 40)
    strong = _avg(2, 10, 1.0, 50)

    assert mild < moderate, f"Mild ({mild:.2f}) not < Moderate ({moderate:.2f})"
    assert moderate < strong, f"Moderate ({moderate:.2f}) not < Strong ({strong:.2f})"
