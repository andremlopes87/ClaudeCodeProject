"""
conectores/canal_dry_run.py — Conector dry-run (simulação controlada por arquivo).

Não envia mensagem real. Não liga. Não usa API externa.
Busca resultado pré-definido em respostas_simuladas_contato.json.
Se não encontrar resposta compatível para a execução, retorna None.

Regra de verdade:
  Nunca inventa resultado. Nunca infere interesse sem entrada explícita.
  Se não houver resposta simulada disponível → None → execução aguarda.

Para trocar por canal real:
  Criar nova classe que herde CanalBase, implementar processar_execucao(),
  registrar no integrador_canais. Nenhum outro arquivo muda.
"""

from conectores.canal_base import CanalBase


class CanalDryRun(CanalBase):
    """
    Conector dry-run que lê respostas de uma lista in-memory.
    A lista é carregada pelo integrador e passada no construtor.
    Mutações (consumido=True) são feitas in-place para o integrador persistir.
    """

    def __init__(self, respostas_simuladas: list) -> None:
        self._respostas = respostas_simuladas

    @property
    def nome(self) -> str:
        return "dry_run"

    @property
    def modo(self) -> str:
        return "dry_run"

    def processar_execucao(self, execucao: dict) -> dict | None:
        """
        Busca resposta simulada compatível por execucao_id.
        Marca como consumida in-place se encontrada.
        Retorna resultado padronizado ou None.
        """
        exec_id  = execucao.get("id", "")
        resposta = self._encontrar_resposta(exec_id)

        if resposta is None:
            return None

        return {
            "tipo_resultado":        resposta["tipo_resultado"],
            "resumo_resultado":      resposta["resumo_resultado"],
            "detalhes":              resposta.get("detalhes", ""),
            "proxima_acao_sugerida": resposta.get("proxima_acao_sugerida", ""),
            "data_resultado":        resposta.get("data_resultado"),
            "canal":                 execucao.get("canal", "telefone"),
            "origem":                "dry_run",
            "_resposta_id":          resposta["id"],   # usado pelo integrador para marcar consumida
        }

    def _encontrar_resposta(self, exec_id: str) -> dict | None:
        return next(
            (r for r in self._respostas
             if r.get("execucao_id") == exec_id and not r.get("consumido", False)),
            None,
        )
