"""Count product titles consistently across editing and prechecks."""


def title_units(value: str) -> int:
    """Han ideographs count two units; letters, digits and symbols count one."""
    def is_han(code: int) -> bool:
        return (0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF
                or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x2FA1F
                or 0x30000 <= code <= 0x323AF)

    return sum(2 if is_han(ord(character)) else 1 for character in value)
