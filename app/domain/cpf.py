import re


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def is_valid_cpf(value: str) -> bool:
    """Valida os dois dígitos verificadores; rejeita sequências repetidas (111.111.111-11)."""
    cpf = only_digits(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(cpf[i]) * (size + 1 - i) for i in range(size))
        digit = (total * 10) % 11 % 10
        if digit != int(cpf[size]):
            return False
    return True


def format_cpf(value: str) -> str:
    cpf = only_digits(value)
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else value


def mask_cpf(value: str) -> str:
    """Para tickets e telas compartilhadas (LGPD): ***.456.789-**"""
    cpf = only_digits(value)
    return f"***.{cpf[3:6]}.{cpf[6:9]}-**" if len(cpf) == 11 else ""
