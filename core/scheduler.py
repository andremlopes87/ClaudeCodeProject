"""
core/scheduler.py

Loop contínuo que executa os agentes da Vetor conforme agenda configurável.

Funciona sem LLM, sem serviço externo, sem Celery — apenas time.sleep.

Arquivos gerenciados:
  dados/scheduler_estado.json  — controle de execuções do dia
  dados/scheduler_log.json     — histórico append-only de execuções

Governança respeitada:
  dados/estado_governanca_conselho.json — agentes_pausados e modo_empresa
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_ESTADO = config.PASTA_DADOS / "scheduler_estado.json"
_ARQ_LOG    = config.PASTA_DADOS / "scheduler_log.json"
_ARQ_GOV    = config.PASTA_DADOS / "estado_governanca_conselho.json"

# Mapeamento abreviatura PT-BR → weekday() do Python (0=seg)
_DIA_IDX = {
    "seg": 0, "ter": 1, "qua": 2, "qui": 3,
    "sex": 4, "sab": 5, "dom": 6,
}
_DIA_NOME = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


# ─── Classe principal ─────────────────────────────────────────────────────────

class Scheduler:
    """
    Scheduler de agentes da Vetor.

    Uso:
      scheduler = Scheduler()
      scheduler.run()                       # loop contínuo
      scheduler.run(once=True)              # roda devidos agora e sai
      scheduler.run(dry_run=True)           # mostra agenda, não executa
      scheduler.executar_agente("comercial")# força execução imediata
    """

    def __init__(self):
        self._agenda    = getattr(config, "AGENDA_AGENTES", {})
        self._intervalo = getattr(config, "SCHEDULER_INTERVALO_CHECK", 60)
        self._tolerancia = getattr(config, "SCHEDULER_TOLERANCIA_MINUTOS", 5)
        self._ativo     = getattr(config, "SCHEDULER_ATIVO", True)

    # ─── Ponto de entrada ─────────────────────────────────────────────────────

    def run(self, dry_run: bool = False, once: bool = False) -> None:
        """
        Loop principal.

        dry_run: imprime agenda sem executar nada.
        once:    executa agentes devidos agora e retorna.
        """
        if not self._ativo and not dry_run:
            print("[Scheduler] SCHEDULER_ATIVO=False — nenhum agente será executado.")
            return

        if dry_run:
            self._imprimir_agenda_dia()
            return

        if once:
            self._verificar_e_executar()
            return

        print("[Scheduler] Iniciando loop contínuo. Ctrl+C para encerrar.")
        self._imprimir_agenda_dia()

        try:
            while True:
                self._verificar_e_executar()
                time.sleep(self._intervalo)
        except KeyboardInterrupt:
            print("\n[Scheduler] Encerrado pelo usuário.")

    def executar_agente(self, nome_agente: str) -> dict:
        """Força execução imediata de um agente, ignorando agenda e governança."""
        print(f"[Scheduler] Execução forçada: {nome_agente}")
        return self._executar(nome_agente, forcado=True)

    # ─── Loop interno ─────────────────────────────────────────────────────────

    def _verificar_e_executar(self) -> None:
        """Verifica a agenda e executa os agentes devidos neste momento."""
        agora = datetime.now()
        self._atualizar_ultima_verificacao(agora)

        devidos = self._agentes_devidos(agora)
        if not devidos:
            return

        for agente, horario_str in devidos:
            motivo_skip = self._motivo_bloqueio(agente)
            if motivo_skip:
                print(f"[Scheduler] {agente} — pulado: {motivo_skip}")
                self._registrar_log(agente, agora.isoformat(), agora.isoformat(),
                                    "pulado", 0, motivo_skip)
                # Marcar como executado nessa janela para não repetir na próxima checagem
                self._marcar_executado(agente, horario_str, agora)
                continue

            resultado = self._executar(agente)
            self._marcar_executado(agente, horario_str, agora)
            status = "ok" if resultado["sucesso"] else "erro"
            print(
                f"[Scheduler] {agente} — {status} "
                f"({resultado['duracao_ms']}ms)"
                + (f" | {resultado['erro']}" if resultado.get('erro') else "")
            )

    # ─── Verificação de agenda ────────────────────────────────────────────────

    def _agentes_devidos(self, agora: datetime) -> list:
        """
        Retorna lista de (agente, horario_str) que devem ser executados agora.
        Considera dia da semana, janela de tolerância e deduplicação.
        """
        devidos = []
        dia_semana = agora.weekday()   # 0=seg

        for agente, cfg in self._agenda.items():
            dias_cfg = cfg.get("dias", [])
            dias_idx = [_DIA_IDX[d] for d in dias_cfg if d in _DIA_IDX]
            if dia_semana not in dias_idx:
                continue

            for horario_str in cfg.get("horarios", []):
                if self._dentro_da_janela(agora, horario_str):
                    if not self._ja_executou(agente, horario_str, agora):
                        devidos.append((agente, horario_str))

        return devidos

    def _dentro_da_janela(self, agora: datetime, horario_str: str) -> bool:
        """True se agora está na janela [horario, horario + tolerância]."""
        try:
            h, m = map(int, horario_str.split(":"))
        except Exception:
            return False
        agendado  = agora.replace(hour=h, minute=m, second=0, microsecond=0)
        limite    = agendado + timedelta(minutes=self._tolerancia)
        return agendado <= agora <= limite

    def _ja_executou(self, agente: str, horario_str: str, agora: datetime) -> bool:
        """True se já foi executado nesta janela de horário hoje."""
        estado  = self._ler_estado()
        hoje    = agora.strftime("%Y-%m-%d")
        try:
            h, m = map(int, horario_str.split(":"))
        except Exception:
            return False

        janela_ini = datetime(agora.year, agora.month, agora.day, h, m)
        janela_fim = janela_ini + timedelta(minutes=self._tolerancia)

        execucoes = estado.get("execucoes_hoje", {}).get(agente, [])
        for ts in execucoes:
            if not ts.startswith(hoje):
                continue
            try:
                dt = datetime.fromisoformat(ts)
                if janela_ini <= dt <= janela_fim:
                    return True
            except Exception:
                continue
        return False

    # ─── Governança ───────────────────────────────────────────────────────────

    def _motivo_bloqueio(self, agente: str) -> "str | None":
        """
        Retorna string com motivo de bloqueio ou None se pode executar.

        Verifica:
          1. agentes_pausados no estado de governança
          2. modo_empresa: "manutencao" bloqueia tudo exceto secretario
        """
        gov = self._ler_governanca()

        pausados = gov.get("agentes_pausados", [])
        if agente in pausados:
            return f"agente pausado via governança"

        modo = gov.get("modo_empresa", "normal")
        if modo == "manutencao" and agente != "secretario":
            return f"empresa em modo manutencao"

        return None

    # ─── Execução ─────────────────────────────────────────────────────────────

    def _executar(self, agente: str, forcado: bool = False) -> dict:
        """
        Executa o agente e retorna resultado com status e duração.
        Nunca lança exceção — agente que falha não derruba o scheduler.
        """
        inicio    = datetime.now()
        inicio_ts = inicio.isoformat(timespec="seconds")

        print(f"[Scheduler] → {agente} iniciando ({inicio_ts})")

        try:
            fn = self._obter_executor(agente)
            fn()
            fim    = datetime.now()
            fim_ts = fim.isoformat(timespec="seconds")
            duracao = int((fim - inicio).total_seconds() * 1000)
            self._registrar_log(agente, inicio_ts, fim_ts, "ok", duracao, None)
            return {"sucesso": True, "duracao_ms": duracao, "erro": None}

        except Exception as exc:
            fim    = datetime.now()
            fim_ts = fim.isoformat(timespec="seconds")
            duracao = int((fim - inicio).total_seconds() * 1000)
            msg_erro = str(exc)
            log.warning(f"[scheduler] {agente} falhou: {msg_erro}")
            self._registrar_log(agente, inicio_ts, fim_ts, "erro", duracao, msg_erro)
            return {"sucesso": False, "duracao_ms": duracao, "erro": msg_erro}

    def _obter_executor(self, agente: str):
        """Retorna a função main() correspondente ao agente. Importação lazy."""
        import sys
        from pathlib import Path as _Path

        # Garante que o diretório raiz está no sys.path
        raiz = str(_Path(__file__).parent.parent)
        if raiz not in sys.path:
            sys.path.insert(0, raiz)

        if agente == "prospeccao":
            import main_agente_prospeccao
            return main_agente_prospeccao.main

        if agente == "marketing":
            from agentes.marketing.agente_marketing import executar
            return executar

        if agente == "comercial":
            import main_agente_comercial
            return main_agente_comercial.main

        if agente == "executor_contato":
            import main_agente_executor_contato
            return main_agente_executor_contato.main

        if agente == "financeiro":
            import main_agente_financeiro
            return main_agente_financeiro.main

        if agente == "secretario":
            import main_agente_secretario
            return main_agente_secretario.main

        if agente == "customer_success":
            import main_agente_customer_success
            return main_agente_customer_success.main

        if agente == "ciclo_completo":
            import main_empresa
            return main_empresa.main

        if agente == "auditor_seguranca":
            import main_agente_auditor_seguranca
            return main_agente_auditor_seguranca.main

        if agente == "qualidade":
            import main_agente_qualidade
            return main_agente_qualidade.main

        raise ValueError(f"Agente desconhecido no scheduler: '{agente}'")

    # ─── Estado e log ─────────────────────────────────────────────────────────

    def _marcar_executado(self, agente: str, horario_str: str, agora: datetime) -> None:
        estado = self._ler_estado()
        hoje   = agora.strftime("%Y-%m-%d")

        # Resetar execucoes_hoje se mudou o dia
        estado = self._resetar_se_novo_dia(estado, hoje)

        ts = agora.isoformat(timespec="seconds")
        estado["execucoes_hoje"].setdefault(agente, []).append(ts)

        # Calcular próximo agendado
        estado["proximo_agendado"] = self._calcular_proximo(agora)
        self._salvar_estado(estado)

    def _atualizar_ultima_verificacao(self, agora: datetime) -> None:
        estado = self._ler_estado()
        hoje   = agora.strftime("%Y-%m-%d")
        estado = self._resetar_se_novo_dia(estado, hoje)
        estado["ultima_verificacao"] = agora.isoformat(timespec="seconds")
        self._salvar_estado(estado)

    def _resetar_se_novo_dia(self, estado: dict, hoje: str) -> dict:
        """Limpa execucoes_hoje se a data mudou."""
        ultima = estado.get("ultima_verificacao", "")
        if ultima[:10] != hoje:
            estado["execucoes_hoje"] = {}
        return estado

    def _calcular_proximo(self, agora: datetime) -> "dict | None":
        """Calcula o próximo agendamento após agora."""
        candidatos = []
        for agente, cfg in self._agenda.items():
            dias_idx = [_DIA_IDX[d] for d in cfg.get("dias", []) if d in _DIA_IDX]
            for horario_str in cfg.get("horarios", []):
                try:
                    h, m = map(int, horario_str.split(":"))
                except Exception:
                    continue
                # Verificar próximos 7 dias
                for delta in range(8):
                    alvo = agora + timedelta(days=delta)
                    alvo = alvo.replace(hour=h, minute=m, second=0, microsecond=0)
                    if alvo <= agora:
                        continue
                    if alvo.weekday() not in dias_idx:
                        continue
                    candidatos.append((alvo, agente, horario_str))
                    break

        if not candidatos:
            return None
        candidatos.sort(key=lambda x: x[0])
        prox = candidatos[0]
        return {"agente": prox[1], "horario": prox[2], "em": prox[0].isoformat(timespec="seconds")}

    # ─── Exibição ─────────────────────────────────────────────────────────────

    def _imprimir_agenda_dia(self) -> None:
        agora      = datetime.now()
        dia_semana = agora.weekday()
        nome_dia   = _DIA_NOME[dia_semana]
        data_str   = agora.strftime("%d/%m/%Y")

        slots = []
        for agente, cfg in self._agenda.items():
            dias_idx = [_DIA_IDX[d] for d in cfg.get("dias", []) if d in _DIA_IDX]
            if dia_semana not in dias_idx:
                continue
            for horario_str in cfg.get("horarios", []):
                slots.append((horario_str, agente))

        slots.sort()

        print(f"\n[Scheduler] Agenda — {nome_dia}, {data_str}")
        if not slots:
            print("  (nenhum agente agendado para hoje)")
        for horario_str, agente in slots:
            gov = self._ler_governanca()
            bloqueio = ""
            if agente in gov.get("agentes_pausados", []):
                bloqueio = "  [PAUSADO]"
            elif gov.get("modo_empresa") == "manutencao" and agente != "secretario":
                bloqueio = "  [MANUTENCAO]"
            print(f"  {horario_str}  {agente}{bloqueio}")

        proximo = self._calcular_proximo(agora)
        if proximo:
            print(f"\n[Scheduler] Próximo: {proximo['agente']} às {proximo['horario']} ({proximo['em'][:16]})")
        print()

    # ─── I/O ──────────────────────────────────────────────────────────────────

    def _ler_estado(self) -> dict:
        if not _ARQ_ESTADO.exists():
            return {"ultima_verificacao": "", "execucoes_hoje": {}, "proximo_agendado": None}
        try:
            with open(_ARQ_ESTADO, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"ultima_verificacao": "", "execucoes_hoje": {}, "proximo_agendado": None}

    def _salvar_estado(self, estado: dict) -> None:
        try:
            _ARQ_ESTADO.parent.mkdir(parents=True, exist_ok=True)
            with open(_ARQ_ESTADO, "w", encoding="utf-8") as f:
                json.dump(estado, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log.warning(f"[scheduler] falha ao salvar estado: {exc}")

    def _ler_governanca(self) -> dict:
        if not _ARQ_GOV.exists():
            return {"modo_empresa": "normal", "agentes_pausados": []}
        try:
            with open(_ARQ_GOV, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"modo_empresa": "normal", "agentes_pausados": []}

    def _registrar_log(
        self,
        agente: str,
        inicio: str,
        fim: str,
        status: str,
        duracao_ms: int,
        erro: "str | None",
    ) -> None:
        historico: list = []
        if _ARQ_LOG.exists():
            try:
                with open(_ARQ_LOG, encoding="utf-8") as f:
                    historico = json.load(f)
                if not isinstance(historico, list):
                    historico = []
            except Exception:
                historico = []

        historico.append({
            "agente":     agente,
            "inicio":     inicio,
            "fim":        fim,
            "status":     status,
            "duracao_ms": duracao_ms,
            "erro":       erro,
        })

        try:
            _ARQ_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_ARQ_LOG, "w", encoding="utf-8") as f:
                json.dump(historico, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log.warning(f"[scheduler] falha ao salvar log: {exc}")
