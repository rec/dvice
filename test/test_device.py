from dvice.device import device_key


def test_device_key_prefers_stable_identity() -> None:
    assert device_key({'name': 'USB Audio', 'uid': 'first'}) == 'uid:first'
    assert device_key({'name': 'USB Audio'}) == 'USB Audio'
