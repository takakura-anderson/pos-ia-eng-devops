"""
Definição de exceções customizadas do sistema.
Centraliza o tratamento de erros para melhor monitoramento e padronização.
"""


class CnpjAppError(Exception):
    """Classe base para todas as exceções customizadas da aplicação."""

    pass


class DataDiscoveryError(CnpjAppError):
    """Levantada quando ocorre um problema na fase de discovery (ex: bloqueios de firewall, mudança de layout, site fora do ar)."""

    pass
