"""Ponto de integração com o TEF real.

NÃO IMPLEMENTADO: depende do fornecedor contratado (SDK/DLL, credenciais, homologação com a
adquirente). Para integrar, implemente `charge()` chamando o SDK e devolva `PaymentResult`:
aprovado com o NSU/autorização em `reference`, ou recusado com a mensagem do fornecedor.
Em Windows os TEFs costumam expor uma DLL (ctypes) ou um serviço HTTP local."""
from decimal import Decimal

from .gateway import PaymentGateway, PaymentResult


class TefGateway(PaymentGateway):
    name = "tef"

    def charge(self, method: str, amount: Decimal, description: str = "") -> PaymentResult:
        raise NotImplementedError(
            "Integração TEF ainda não implementada. Use o gateway 'simulated' ou o modo de caixa manual.")
