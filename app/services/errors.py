class BusinessError(Exception):
    """Erro de regra de negócio, com mensagem pronta para o operador."""


class CommandNotFound(BusinessError):
    pass


class CommandClosed(BusinessError):
    pass


class InvalidWeight(BusinessError):
    pass


class PriceNotFound(BusinessError):
    pass


class NotAuthorized(BusinessError):
    pass


class InvalidCpf(BusinessError):
    pass


class DuplicateOpenCommand(BusinessError):
    """Já existe comanda em aberto para o CPF; `existing` guarda o código dela."""

    def __init__(self, existing_code: str):
        super().__init__(f"Já existe a comanda {existing_code} em aberto para este CPF.")
        self.existing_code = existing_code


class PaymentError(BusinessError):
    pass
