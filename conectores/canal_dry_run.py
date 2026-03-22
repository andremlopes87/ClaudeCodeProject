"""
conectores/canal_dry_run.py — Conector dry-run com motor de cenários.

Ordem de decisão:
  1. Resposta explícita em respostas_simuladas_contato.json  (prioridade máxima)
  2. Motor de cenários determinístico (config_cenarios_contato.json + seed)
  3. None — execução permanece aguardando

Regra de verdade:
  Nunca inventa resultado fora das políticas configuradas.
  Nunca infere interesse sem base.
  Resultados do motor são deterministicos: mesma execucao_id + seed → mesmo resultado.

Para trocar por canal real:
  Criar nova classe herdando CanalBase, implementar processar_execucao().
  Nenhum outro arquivo muda.
"""

from datetime import datetime

from conectores.canal_base import CanalBase


class CanalDryRun(CanalBase):
    """
    Conector dry-run com fallback para motor de cenários.

    Construtor:
      respostas_simuladas — lista in-memory de respostas explícitas (mutada in-place)
      config_motor        — dict de config_cenarios_contato.json (opcional)
      pipeline_idx        — {opp_id: opp} para enrichment de contexto (opcional)
      hist_cenarios       — lista de histórico de decisões (mutada in-place, opcional)
    """

    def __init__(
        self,
        respostas_simuladas: list,
        config_motor: dict | None = None,
        pipeline_idx: dict | None = None,
        hist_cenarios: list | None = None,
    ) -> None:
        self._respostas    = respostas_simuladas
        self._config       = config_motor
        self._pipeline     = pipeline_idx or {}
        self._hist         = hist_cenarios if hist_cenarios is not None else []

    @property
    def nome(self) -> str:
        return "dry_run"

    @property
    def modo(self) -> str:
        return "dry_run"

    def processar_execucao(self, execucao: dict) -> dict | None:
        """
        Tenta encontrar resultado na ordem:
          1. resposta_explicita (respostas_simuladas_contato.json)
          2. motor_cenarios    (config + seed determinística)
          3. None
        """
        # ── Tentativa 1: resposta explícita ──────────────────────────────────
        resposta = self._encontrar_resposta(execucao.get("id", ""))
        if resposta is not None:
            return {
                "tipo_resultado":        resposta["tipo_resultado"],
                "resumo_resultado":      resposta["resumo_resultado"],
                "detalhes":              resposta.get("detalhes", ""),
                "proxima_acao_sugerida": resposta.get("proxima_acao_sugerida", ""),
                "data_resultado":        resposta.get("data_resultado"),
                "canal":                 execucao.get("canal", "telefone"),
                "origem":                "dry_run",
                "_origem":               "resposta_explicita",
                "_regra":                None,
                "_resposta_id":          resposta["id"],
            }

        # ── Tentativa 2: motor de cenários ────────────────────────────────────
        if self._config:
            from core.motor_cenarios_contato import decidir_resultado_para_execucao
            return decidir_resultado_para_execucao(
                execucao, self._config, self._pipeline, self._hist
            )

        return None

    def _encontrar_resposta(self, exec_id: str) -> dict | None:
        return next(
            (r for r in self._respostas
             if r.get("execucao_id") == exec_id and not r.get("consumido", False)),
            None,
        )
