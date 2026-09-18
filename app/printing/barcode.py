from barcode import Code128


def code128_modules(text: str) -> str:
    """Devolve a sequência de módulos do Code 128 ('1' = barra, '0' = espaço)."""
    return Code128(text).build()[0]
