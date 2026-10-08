"""Audio-device descriptions and identity hints."""

DeviceDict = dict[str, float | int | str]


def device_key(info: DeviceDict) -> str:
    """Prefer a supplied persistent ID; the display-name fallback is not unique."""
    for field in STABLE_DEVICE_ID_FIELDS:
        if value := str(info.get(field, '')).strip():
            return f'{field}:{value}'
    return str(info['name'])


STABLE_DEVICE_ID_FIELDS = ('uid', 'unique_id', 'persistent_id', 'guid', 'identifier')
