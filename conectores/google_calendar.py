"""
conectores/google_calendar.py — Google Calendar API.

Cria e gerencia agendas para clientes automaticamente.
API gratuita — zero custo por chamada.

Modos:
  dry-run (padrão): zero chamadas externas, respostas simuladas realistas
  real: OAuth2 service account → Google Calendar API v3

Autenticação (modo real):
  1. Criar service account no Google Cloud Console
  2. Habilitar API: Google Calendar API
  3. Baixar JSON de credenciais → salvar em credenciais/google_service_account.json
  4. Alterar "modo" para "real" em dados/config_google_calendar.json

Dependência para modo real:
  pip install google-auth google-auth-httplib2 requests

Referência:
  https://developers.google.com/calendar/api/v3/reference
"""

import json
import logging
import os
import random
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

# ─── Configuração ─────────────────────────────────────────────────────────────

_ARQ_CONFIG = config.PASTA_DADOS / "config_google_calendar.json"

_CONFIG_PADRAO = {
    "modo":             "dry-run",
    "credentials_path": None,
}

_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

_BASE_URL = "https://www.googleapis.com/calendar/v3"


# ─── I/O de configuração ──────────────────────────────────────────────────────

def _carregar_config() -> dict:
    cfg = dict(_CONFIG_PADRAO)
    if _ARQ_CONFIG.exists():
        try:
            cfg.update(json.loads(_ARQ_CONFIG.read_text(encoding="utf-8")))
        except Exception as _err:
            logger.warning("erro ignorado: %s", _err)
    if os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_PATH"):
        cfg["credentials_path"] = os.environ["GOOGLE_CALENDAR_CREDENTIALS_PATH"]
    return cfg


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id_fake(prefixo: str = "cal") -> str:
    return f"dry-run-{prefixo}-{uuid.uuid4().hex[:12]}@group.calendar.google.com"


def _evento_id_fake() -> str:
    return f"evt{uuid.uuid4().hex[:16]}"


# ─── Autenticação OAuth2 ──────────────────────────────────────────────────────

def _obter_access_token(credentials_path: str) -> str:
    """
    Obtém access token via OAuth2 service account.
    Requer google-auth: pip install google-auth google-auth-httplib2
    """
    try:
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import Request as GoogleRequest

        creds = Credentials.from_service_account_file(credentials_path, scopes=_GOOGLE_SCOPES)
        creds.refresh(GoogleRequest())
        return creds.token

    except ImportError:
        raise RuntimeError(
            "Dependência ausente para modo real. "
            "Execute: pip install google-auth google-auth-httplib2"
        )
    except Exception as e:
        raise RuntimeError(f"Falha ao obter access token: {e}")


def _headers(credentials_path: str) -> dict:
    token = _obter_access_token(credentials_path)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _get(url: str, hdrs: dict, params: dict = None) -> dict:
    import requests
    r = requests.get(url, headers=hdrs, params=params, timeout=config.TIMEOUT_REQUISICAO)
    r.raise_for_status()
    return r.json()


def _post(url: str, hdrs: dict, body: dict) -> dict:
    import requests
    r = requests.post(url, headers=hdrs, json=body, timeout=config.TIMEOUT_REQUISICAO)
    r.raise_for_status()
    return r.json()


def _patch(url: str, hdrs: dict, body: dict) -> dict:
    import requests
    r = requests.patch(url, headers=hdrs, json=body, timeout=config.TIMEOUT_REQUISICAO)
    r.raise_for_status()
    return r.json()


def _delete(url: str, hdrs: dict) -> bool:
    import requests
    r = requests.delete(url, headers=hdrs, timeout=config.TIMEOUT_REQUISICAO)
    return r.status_code in (200, 204)


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _parse_hora(s: str) -> tuple[int, int]:
    """'HH:MM' → (hora, minuto)."""
    h, m = s.split(":")
    return int(h), int(m)


def _gerar_slots_do_dia(
    dia: date,
    horario_inicio: str,
    horario_fim: str,
    duracao: int,
    intervalo: int,
) -> list[datetime]:
    """Gera lista de datetimes de início de slot para um dia."""
    h_ini, m_ini = _parse_hora(horario_inicio)
    h_fim, m_fim = _parse_hora(horario_fim)
    inicio = datetime(dia.year, dia.month, dia.day, h_ini, m_ini)
    fim_limite = datetime(dia.year, dia.month, dia.day, h_fim, m_fim)
    slots = []
    atual = inicio
    passo = timedelta(minutes=duracao + intervalo)
    while atual + timedelta(minutes=duracao) <= fim_limite:
        slots.append(atual)
        atual += passo
    return slots


_DIAS_PT = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6}


# ─── Classe principal ─────────────────────────────────────────────────────────

class GoogleCalendarConnector:
    """
    Gerencia agendas Google Calendar para clientes da Vetor.

    Em modo dry-run, todos os métodos retornam dados simulados realistas
    sem fazer nenhuma chamada à API.

    Uso:
        gc = GoogleCalendarConnector()
        cal = gc.criar_agenda("Barbearia do João")
        slots = gc.criar_slots_horario(cal["calendar_id"], config_slots)
        disp  = gc.verificar_disponibilidade(cal["calendar_id"], "2026-04-01")
        evt   = gc.criar_agendamento(cal["calendar_id"], dados_agendamento)
    """

    def __init__(self, modo: str = None):
        cfg = _carregar_config()
        self.modo = modo or cfg.get("modo", "dry-run")
        self.credentials_path = cfg.get("credentials_path")

        if self.modo == "real" and not self.credentials_path:
            logger.warning(
                "Modo 'real' configurado mas credentials_path ausente — "
                "usando dry-run como fallback."
            )
            self.modo = "dry-run"

    # ─── Criar agenda ──────────────────────────────────────────────────────────

    def criar_agenda(self, nome: str, timezone: str = "America/Sao_Paulo") -> dict:
        """
        Cria uma nova agenda compartilhada para o cliente.

        Retorna:
            calendar_id: ID único da agenda
            link:        Link de acesso ao Google Calendar
            nome:        Nome da agenda criada
            modo:        dry-run | real
        """
        logger.info(f"[Calendar] criar_agenda: '{nome}' tz={timezone} modo={self.modo}")

        if self.modo == "dry-run":
            cal_id = _id_fake("agenda")
            return {
                "calendar_id": cal_id,
                "nome":        nome,
                "timezone":    timezone,
                "link":        f"https://calendar.google.com/calendar/r?cid={cal_id}",
                "modo":        "dry-run",
                "criado_em":   _agora(),
            }

        hdrs = _headers(self.credentials_path)
        body = {
            "summary":  nome,
            "timeZone": timezone,
        }
        resp = _post(f"{_BASE_URL}/calendars", hdrs, body)
        cal_id = resp["id"]
        link = f"https://calendar.google.com/calendar/r?cid={cal_id}"
        logger.info(f"[Calendar] Agenda criada: {cal_id}")
        return {
            "calendar_id": cal_id,
            "nome":        nome,
            "timezone":    timezone,
            "link":        link,
            "modo":        "real",
            "criado_em":   _agora(),
        }

    # ─── Criar slots de horário ────────────────────────────────────────────────

    def criar_slots_horario(self, calendar_id: str, cfg_slots: dict) -> int:
        """
        Cria eventos recorrentes representando slots disponíveis de atendimento.

        cfg_slots esperado:
          profissionais      list[str]  — nomes dos profissionais
          horarios           dict       — {dia_semana: {inicio: "HH:MM", fim: "HH:MM"}}
                                          Dias: seg, ter, qua, qui, sex, sab, dom
          duracao_minutos    int        — duração de cada atendimento
          intervalo_minutos  int        — pausa entre atendimentos (padrão 0)
          folgas             list[str]  — datas bloqueadas "YYYY-MM-DD"
          semanas_antecipadas int       — janela de geração (padrão 4)

        Retorna:
            Número de slots criados (ou simulados em dry-run).
        """
        profissionais = cfg_slots.get("profissionais", ["Profissional"])
        horarios      = cfg_slots.get("horarios", {})
        duracao       = cfg_slots.get("duracao_minutos", 60)
        intervalo     = cfg_slots.get("intervalo_minutos", 0)
        folgas_str    = set(cfg_slots.get("folgas", []))
        semanas       = cfg_slots.get("semanas_antecipadas", 4)

        folgas = {date.fromisoformat(d) for d in folgas_str if d}

        hoje    = date.today()
        fim     = hoje + timedelta(weeks=semanas)
        total   = 0
        erros   = 0

        logger.info(
            f"[Calendar] criar_slots_horario: {len(profissionais)} profissional(is), "
            f"janela {hoje}→{fim}, duracao={duracao}min"
        )

        if self.modo == "dry-run":
            # Simula contagem sem criar eventos reais
            dia_atual = hoje
            while dia_atual <= fim:
                if dia_atual not in folgas:
                    nome_dia = dia_atual.strftime("%A").lower()[:3]
                    for nome_pt, num in _DIAS_PT.items():
                        if num == dia_atual.weekday() and nome_pt in horarios:
                            cfg_dia = horarios[nome_pt]
                            slots = _gerar_slots_do_dia(
                                dia_atual,
                                cfg_dia["inicio"],
                                cfg_dia["fim"],
                                duracao,
                                intervalo,
                            )
                            total += len(slots) * len(profissionais)
                            break
                dia_atual += timedelta(days=1)
            logger.info(f"[Calendar] dry-run: {total} slots simulados.")
            return total

        hdrs = _headers(self.credentials_path)
        dia_atual = hoje
        while dia_atual <= fim:
            if dia_atual in folgas:
                dia_atual += timedelta(days=1)
                continue

            for nome_pt, num in _DIAS_PT.items():
                if num == dia_atual.weekday() and nome_pt in horarios:
                    cfg_dia = horarios[nome_pt]
                    slots = _gerar_slots_do_dia(
                        dia_atual,
                        cfg_dia["inicio"],
                        cfg_dia["fim"],
                        duracao,
                        intervalo,
                    )
                    for slot_inicio in slots:
                        slot_fim = slot_inicio + timedelta(minutes=duracao)
                        for prof in profissionais:
                            body = {
                                "summary":     f"[DISPONÍVEL] {prof}",
                                "description": f"Slot disponível — {prof}",
                                "start": {
                                    "dateTime": slot_inicio.isoformat(),
                                    "timeZone": "America/Sao_Paulo",
                                },
                                "end": {
                                    "dateTime": slot_fim.isoformat(),
                                    "timeZone": "America/Sao_Paulo",
                                },
                                "colorId":     "2",  # verde = disponível
                                "extendedProperties": {
                                    "private": {
                                        "tipo":         "slot_disponivel",
                                        "profissional": prof,
                                    }
                                },
                            }
                            try:
                                _post(f"{_BASE_URL}/calendars/{calendar_id}/events", hdrs, body)
                                total += 1
                            except Exception as exc:
                                erros += 1
                                logger.warning(f"    Erro ao criar slot {slot_inicio} / {prof}: {exc}")
                    break

            dia_atual += timedelta(days=1)

        logger.info(f"[Calendar] {total} slots criados, {erros} erros.")
        return total

    # ─── Verificar disponibilidade ─────────────────────────────────────────────

    def verificar_disponibilidade(self, calendar_id: str, data: str) -> list:
        """
        Retorna lista de horários disponíveis para uma data.

        data: "YYYY-MM-DD"

        Retorna lista de dicts:
          horario_inicio, horario_fim, profissional, evento_id
        """
        logger.info(f"[Calendar] verificar_disponibilidade: {calendar_id} data={data} modo={self.modo}")

        if self.modo == "dry-run":
            d = date.fromisoformat(data)
            # Gera horários fixos simulados (09:00 às 17:00, 1h cada)
            disponiveis = []
            hora = 9
            for _ in range(8):
                if hora >= 17:
                    break
                inicio = datetime(d.year, d.month, d.day, hora, 0)
                fim    = inicio + timedelta(hours=1)
                disponiveis.append({
                    "horario_inicio": inicio.strftime("%H:%M"),
                    "horario_fim":    fim.strftime("%H:%M"),
                    "profissional":   "Profissional",
                    "evento_id":      _evento_id_fake(),
                })
                hora += 1
            return disponiveis

        hdrs = _headers(self.credentials_path)
        d  = date.fromisoformat(data)
        d1 = datetime(d.year, d.month, d.day, 0,  0,  0).isoformat() + "Z"
        d2 = datetime(d.year, d.month, d.day, 23, 59, 59).isoformat() + "Z"

        params = {
            "timeMin":      d1,
            "timeMax":      d2,
            "singleEvents": "true",
            "orderBy":      "startTime",
            "q":            "[DISPONÍVEL]",
        }
        resp   = _get(f"{_BASE_URL}/calendars/{calendar_id}/events", hdrs, params)
        itens  = resp.get("items", [])

        disponiveis = []
        for ev in itens:
            props = ev.get("extendedProperties", {}).get("private", {})
            if props.get("tipo") == "slot_disponivel":
                ini_str = ev["start"].get("dateTime", "")
                fim_str = ev["end"].get("dateTime", "")
                try:
                    ini_dt = datetime.fromisoformat(ini_str)
                    fim_dt = datetime.fromisoformat(fim_str)
                    disponiveis.append({
                        "horario_inicio": ini_dt.strftime("%H:%M"),
                        "horario_fim":    fim_dt.strftime("%H:%M"),
                        "profissional":   props.get("profissional", "—"),
                        "evento_id":      ev["id"],
                    })
                except Exception as _err:
                    logger.warning("erro ignorado: %s", _err)

        return disponiveis

    # ─── Criar agendamento ─────────────────────────────────────────────────────

    def criar_agendamento(self, calendar_id: str, dados: dict) -> dict:
        """
        Cria evento de agendamento confirmado na agenda.

        dados esperado:
          nome_cliente      str — nome do cliente
          telefone_cliente  str — telefone/WhatsApp do cliente (opcional)
          servico           str — serviço a ser realizado
          horario           str — "YYYY-MM-DDTHH:MM:SS" ou "YYYY-MM-DDTHH:MM"
          duracao_minutos   int — duração do serviço (padrão 60)
          profissional      str — profissional responsável
          slot_evento_id    str — ID do slot a substituir/deletar (opcional)

        Retorna:
          evento_id, link_confirmacao, horario_inicio, horario_fim, status
        """
        nome     = dados.get("nome_cliente", "Cliente")
        telefone = dados.get("telefone_cliente", "")
        servico  = dados.get("servico", "Atendimento")
        horario  = dados.get("horario", datetime.now().isoformat())
        duracao  = dados.get("duracao_minutos", 60)
        prof     = dados.get("profissional", "Profissional")
        slot_id  = dados.get("slot_evento_id")

        logger.info(
            f"[Calendar] criar_agendamento: {nome} / {servico} / {horario} "
            f"/ {prof} modo={self.modo}"
        )

        try:
            ini_dt = datetime.fromisoformat(horario)
        except Exception:
            ini_dt = datetime.now()

        fim_dt = ini_dt + timedelta(minutes=duracao)

        if self.modo == "dry-run":
            evt_id = _evento_id_fake()
            return {
                "evento_id":        evt_id,
                "link_confirmacao": (
                    f"https://calendar.google.com/calendar/r/eventedit?"
                    f"eid={evt_id}"
                ),
                "horario_inicio":   ini_dt.strftime("%H:%M"),
                "horario_fim":      fim_dt.strftime("%H:%M"),
                "data":             ini_dt.strftime("%d/%m/%Y"),
                "profissional":     prof,
                "servico":          servico,
                "status":           "confirmado",
                "modo":             "dry-run",
            }

        hdrs = _headers(self.credentials_path)

        # Remove slot disponível se informado
        if slot_id:
            try:
                _delete(f"{_BASE_URL}/calendars/{calendar_id}/events/{slot_id}", hdrs)
            except Exception as exc:
                logger.warning(f"[Calendar] Não foi possível remover slot {slot_id}: {exc}")

        desc_partes = [f"Serviço: {servico}", f"Profissional: {prof}"]
        if telefone:
            desc_partes.append(f"WhatsApp: {telefone}")

        body = {
            "summary":     f"{servico} — {nome}",
            "description": "\n".join(desc_partes),
            "start": {
                "dateTime": ini_dt.isoformat(),
                "timeZone": "America/Sao_Paulo",
            },
            "end": {
                "dateTime": fim_dt.isoformat(),
                "timeZone": "America/Sao_Paulo",
            },
            "colorId": "11",  # vermelho = agendado
            "extendedProperties": {
                "private": {
                    "tipo":             "agendamento",
                    "profissional":     prof,
                    "servico":          servico,
                    "nome_cliente":     nome,
                    "telefone_cliente": telefone,
                }
            },
        }

        resp   = _post(f"{_BASE_URL}/calendars/{calendar_id}/events", hdrs, body)
        evt_id = resp["id"]
        link   = resp.get("htmlLink", f"https://calendar.google.com/calendar/r")
        logger.info(f"[Calendar] Agendamento criado: {evt_id}")

        return {
            "evento_id":        evt_id,
            "link_confirmacao": link,
            "horario_inicio":   ini_dt.strftime("%H:%M"),
            "horario_fim":      fim_dt.strftime("%H:%M"),
            "data":             ini_dt.strftime("%d/%m/%Y"),
            "profissional":     prof,
            "servico":          servico,
            "status":           "confirmado",
            "modo":             "real",
        }

    # ─── Cancelar agendamento ──────────────────────────────────────────────────

    def cancelar_agendamento(self, calendar_id: str, evento_id: str) -> bool:
        """
        Cancela um agendamento existente.

        Retorna True se cancelado com sucesso, False se houve erro.
        """
        logger.info(
            f"[Calendar] cancelar_agendamento: {evento_id} modo={self.modo}"
        )

        if self.modo == "dry-run":
            return True

        try:
            hdrs = _headers(self.credentials_path)
            return _delete(f"{_BASE_URL}/calendars/{calendar_id}/events/{evento_id}", hdrs)
        except Exception as exc:
            logger.error(f"[Calendar] Erro ao cancelar {evento_id}: {exc}")
            return False

    # ─── Remarcar agendamento ──────────────────────────────────────────────────

    def remarcar_agendamento(
        self, calendar_id: str, evento_id: str, novo_horario: str, duracao_minutos: int = 60
    ) -> dict:
        """
        Remarca um agendamento existente para um novo horário.

        novo_horario: "YYYY-MM-DDTHH:MM:SS"

        Retorna o mesmo formato de criar_agendamento.
        """
        logger.info(
            f"[Calendar] remarcar_agendamento: {evento_id} → {novo_horario} modo={self.modo}"
        )

        try:
            ini_dt = datetime.fromisoformat(novo_horario)
        except Exception:
            ini_dt = datetime.now()

        fim_dt = ini_dt + timedelta(minutes=duracao_minutos)

        if self.modo == "dry-run":
            return {
                "evento_id":      evento_id,
                "horario_inicio": ini_dt.strftime("%H:%M"),
                "horario_fim":    fim_dt.strftime("%H:%M"),
                "data":           ini_dt.strftime("%d/%m/%Y"),
                "status":         "remarcado",
                "modo":           "dry-run",
            }

        hdrs = _headers(self.credentials_path)
        body = {
            "start": {
                "dateTime": ini_dt.isoformat(),
                "timeZone": "America/Sao_Paulo",
            },
            "end": {
                "dateTime": fim_dt.isoformat(),
                "timeZone": "America/Sao_Paulo",
            },
        }
        resp = _patch(f"{_BASE_URL}/calendars/{calendar_id}/events/{evento_id}", hdrs, body)
        logger.info(f"[Calendar] Agendamento remarcado: {evento_id}")

        return {
            "evento_id":      resp.get("id", evento_id),
            "horario_inicio": ini_dt.strftime("%H:%M"),
            "horario_fim":    fim_dt.strftime("%H:%M"),
            "data":           ini_dt.strftime("%d/%m/%Y"),
            "status":         "remarcado",
            "modo":           "real",
        }

    # ─── Compartilhar agenda ───────────────────────────────────────────────────

    def compartilhar_agenda(self, calendar_id: str, email_dono: str) -> bool:
        """
        Compartilha a agenda com o email do dono do negócio (papel: owner).

        Retorna True se compartilhado com sucesso.
        """
        logger.info(
            f"[Calendar] compartilhar_agenda: {calendar_id} → {email_dono} modo={self.modo}"
        )

        if self.modo == "dry-run":
            return True

        try:
            hdrs = _headers(self.credentials_path)
            body = {
                "role":      "owner",
                "scope": {
                    "type":  "user",
                    "value": email_dono,
                },
            }
            _post(f"{_BASE_URL}/calendars/{calendar_id}/acl", hdrs, body)
            logger.info(f"[Calendar] Agenda compartilhada com {email_dono}")
            return True
        except Exception as exc:
            logger.error(f"[Calendar] Erro ao compartilhar com {email_dono}: {exc}")
            return False

    # ─── Métricas ──────────────────────────────────────────────────────────────

    def obter_metricas(self, calendar_id: str, periodo_dias: int = 30) -> dict:
        """
        Retorna métricas de uso da agenda no período.

        Métricas retornadas:
          agendamentos_total     — total de agendamentos confirmados
          cancelamentos          — total de eventos cancelados
          taxa_ocupacao_pct      — % dos slots que foram ocupados
          horario_mais_popular   — HH:MM com maior demanda
          dia_mais_movimentado   — dia da semana com mais agendamentos
          slots_disponiveis      — slots ainda não agendados
        """
        logger.info(
            f"[Calendar] obter_metricas: {calendar_id} periodo={periodo_dias}d modo={self.modo}"
        )

        if self.modo == "dry-run":
            seed = sum(ord(c) for c in calendar_id) % 9999
            rng  = random.Random(seed)
            total = rng.randint(15, 80)
            slots = rng.randint(total, total + 40)
            return {
                "agendamentos_total":    total,
                "cancelamentos":         rng.randint(0, max(1, total // 10)),
                "taxa_ocupacao_pct":     round(total / slots * 100, 1) if slots else 0,
                "horario_mais_popular":  f"{rng.choice([9, 10, 11, 14, 15, 16])}:00",
                "dia_mais_movimentado":  rng.choice(["Sexta", "Sábado", "Quinta"]),
                "slots_disponiveis":     slots - total,
                "periodo_dias":          periodo_dias,
                "modo":                  "dry-run",
            }

        hdrs = _headers(self.credentials_path)
        fim  = datetime.now()
        ini  = fim - timedelta(days=periodo_dias)

        params = {
            "timeMin":      ini.isoformat() + "Z",
            "timeMax":      fim.isoformat() + "Z",
            "singleEvents": "true",
            "maxResults":   2500,
        }
        resp  = _get(f"{_BASE_URL}/calendars/{calendar_id}/events", hdrs, params)
        itens = resp.get("items", [])

        agendamentos  = 0
        cancelamentos = 0
        horas: dict[str, int] = {}
        dias:  dict[str, int] = {}
        slots_disp = 0

        for ev in itens:
            props = ev.get("extendedProperties", {}).get("private", {})
            tipo  = props.get("tipo", "")
            ini_str = ev.get("start", {}).get("dateTime", "")

            try:
                ini_ev = datetime.fromisoformat(ini_str)
            except Exception:
                continue

            hora_str = ini_ev.strftime("%H:00")
            dia_str  = ini_ev.strftime("%A")

            if tipo == "agendamento":
                agendamentos += 1
                horas[hora_str] = horas.get(hora_str, 0) + 1
                dias[dia_str]   = dias.get(dia_str, 0)   + 1
            elif tipo == "slot_disponivel":
                slots_disp += 1
            elif ev.get("status") == "cancelled":
                cancelamentos += 1

        total_slots = agendamentos + slots_disp
        taxa = round(agendamentos / total_slots * 100, 1) if total_slots else 0
        hora_pop = max(horas, key=horas.get) if horas else "—"
        dia_pop  = max(dias,  key=dias.get)  if dias  else "—"

        return {
            "agendamentos_total":    agendamentos,
            "cancelamentos":         cancelamentos,
            "taxa_ocupacao_pct":     taxa,
            "horario_mais_popular":  hora_pop,
            "dia_mais_movimentado":  dia_pop,
            "slots_disponiveis":     slots_disp,
            "periodo_dias":          periodo_dias,
            "modo":                  "real",
        }


# ─── Factory ──────────────────────────────────────────────────────────────────

def obter_conector(modo: str = None) -> GoogleCalendarConnector:
    """Retorna instância configurada do conector."""
    return GoogleCalendarConnector(modo=modo)


# ─── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    gc = obter_conector()
    print(f"\nModo: {gc.modo}\n")

    # 1. Criar agenda
    cal = gc.criar_agenda("Barbearia do João Teste")
    print("criar_agenda:", cal)

    # 2. Criar slots
    cfg_slots = {
        "profissionais":     ["Carlos", "Marcos"],
        "horarios": {
            "seg": {"inicio": "09:00", "fim": "18:00"},
            "ter": {"inicio": "09:00", "fim": "18:00"},
            "qua": {"inicio": "09:00", "fim": "18:00"},
            "qui": {"inicio": "09:00", "fim": "18:00"},
            "sex": {"inicio": "09:00", "fim": "18:00"},
            "sab": {"inicio": "09:00", "fim": "13:00"},
        },
        "duracao_minutos":    60,
        "intervalo_minutos":  0,
        "folgas":             [],
        "semanas_antecipadas": 2,
    }
    total_slots = gc.criar_slots_horario(cal["calendar_id"], cfg_slots)
    print(f"\ncriar_slots_horario: {total_slots} slots")

    # 3. Verificar disponibilidade
    amanha = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    disponiveis = gc.verificar_disponibilidade(cal["calendar_id"], amanha)
    print(f"\nverificar_disponibilidade ({amanha}): {len(disponiveis)} slots disponíveis")
    for h in disponiveis[:3]:
        print(f"  {h['horario_inicio']} – {h['horario_fim']} | {h['profissional']}")

    # 4. Criar agendamento
    horario_ag = f"{amanha}T10:00:00"
    evt = gc.criar_agendamento(cal["calendar_id"], {
        "nome_cliente":     "Maria Silva",
        "telefone_cliente": "(17) 99988-7766",
        "servico":          "Corte + Barba",
        "horario":          horario_ag,
        "duracao_minutos":  60,
        "profissional":     "Carlos",
    })
    print(f"\ncriar_agendamento: {evt}")

    # 5. Remarcar
    novo_horario = f"{amanha}T14:00:00"
    remarc = gc.remarcar_agendamento(cal["calendar_id"], evt["evento_id"], novo_horario)
    print(f"\nremarcar_agendamento: {remarc}")

    # 6. Compartilhar
    ok = gc.compartilhar_agenda(cal["calendar_id"], "dono@email.com")
    print(f"\ncompartilhar_agenda: {ok}")

    # 7. Métricas
    metricas = gc.obter_metricas(cal["calendar_id"])
    print(f"\nobter_metricas: {metricas}")

    # 8. Cancelar
    cancelado = gc.cancelar_agendamento(cal["calendar_id"], evt["evento_id"])
    print(f"\ncancelar_agendamento: {cancelado}")
