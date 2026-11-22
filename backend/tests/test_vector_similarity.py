from services.vector_similarity import cosine_similarity


def test_identical_vectors_have_unit_similarity():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_orthogonal_vectors_have_zero_similarity():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_opposite_vectors_have_negative_similarity():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_invalid_or_zero_vectors_fail_closed():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == -1.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == -1.0
    assert cosine_similarity(None, [1.0]) == -1.0
    assert cosine_similarity(["not-a-number"], [1.0]) == -1.0
