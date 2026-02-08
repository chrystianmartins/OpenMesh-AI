from app.services.api_keys import API_KEY_PREFIX, generate_api_key_material


def test_generate_api_key_material_has_expected_shape() -> None:
    key_material = generate_api_key_material()

    assert key_material.raw_key.startswith(f"{API_KEY_PREFIX}_")
    assert len(key_material.key_hash) == 64
    assert key_material.prefix == key_material.raw_key[:12]


def test_generate_api_key_material_is_random() -> None:
    first = generate_api_key_material()
    second = generate_api_key_material()

    assert first.raw_key != second.raw_key
    assert first.key_hash != second.key_hash
