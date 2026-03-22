"""
conectores/canal_base.py — Interface base para conectores de canal.

Todo conector (dry-run ou real) deve implementar esta interface.
A troca entre dry-run e canal real exige apenas criar um novo conector
que implemente processar_execucao() e registrá-lo no integrador_canais.

Contrato de saída de processar_execucao():
  - Retorna dict com o resultado quando houver resposta disponível.
  - Retorna None quando a execução ainda não tem resultado (sem invenção).

Campos mínimos do dict de retorno:
  tipo_resultado         — sem_resposta | respondeu_interesse | respondeu_sem_interesse
                           | pediu_proposta | pediu_retorno_futuro | contato_invalido | erro_execucao
  resumo_resultado       — frase curta descrevendo o resultado
  detalhes               — contexto adicional (opcional)
  proxima_acao_sugerida  — o que fazer a seguir (opcional)
  data_resultado         — ISO 8601 (opcional, usa now() se ausente)
  canal                  — telefone | whatsapp | email | ...
  origem                 — identificador do conector (ex: 'dry_run', 'twilio_voice')
"""

from abc import ABC, abstractmethod


class CanalBase(ABC):
    """Interface mínima para um conector de canal externo."""

    @property
    @abstractmethod
    def nome(self) -> str:
        """Identificador do canal (ex: 'dry_run', 'twilio_voice', 'whatsapp_cloud')."""
        ...

    @property
    @abstractmethod
    def modo(self) -> str:
        """Modo de operação: 'dry_run', 'sandbox', 'producao'."""
        ...

    @abstractmethod
    def processar_execucao(self, execucao: dict) -> dict | None:
        """
        Recebe uma execução pronta da fila_execucao_contato.json.
        Retorna resultado padronizado ou None (sem invenção).

        O resultado é um dict com os campos descritos no módulo.
        None indica que o resultado ainda não está disponível —
        a execução deve permanecer aguardando_integracao_canal.
        """
        ...
