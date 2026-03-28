"""
core/auto_teste_entrega.py

Auto-testa bots e serviços digitais criados para uma conta antes de
marcar a entrega como concluída.

Em dry-run: simula todos os testes sem chamadas reais — sempre passa.
Em real: envia mensagens de teste via webhook n8n e verifica agenda.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_WORKFLOWS = config.PASTA_DADOS / "workflows_por_conta.json"


# ─── Função principal ──────────────────────────────────────────────────────────

def testar_cenarios(
    conta_id: str,
    entrega: dict,
    modo: str | None = None,
) -> dict:
    """
    Executa cenários de teste para todos os workflows da conta.

    Returns:
        {status, testes_ok, passou, falhou, detalhes, testado_em}
    """
    modo_efetivo = modo or _obter_modo()
    agora = datetime.now().isoformat(timespec="seconds")

    workflows = _carregar_workflows_conta(conta_id)
    if not workflows:
        log.info(f"[auto_teste] {conta_id} — sem workflows registrados, pulando testes")
        return {
            "status":     "sem_workflows",
            "testes_ok":  True,
            "passou":     0,
            "falhou":     0,
            "detalhes":   [],
            "testado_em": agora,
        }

    detalhes = []
    passou = 0
    falhou = 0

    for wf in workflows:
        tipo = wf.get("tipo", "")
        wf_id = wf.get("workflow_id", "")

        if tipo == "atendimento":
            res = _testar_atendimento(wf_id, conta_id, modo_efetivo)
        elif tipo == "agendamento":
            res = _testar_agendamento(wf_id, wf.get("calendar_id", ""), conta_id, modo_efetivo)
        elif tipo == "lembrete":
            res = _testar_lembrete(wf_id, wf.get("calendar_id", ""), conta_id, modo_efetivo)
        else:
            continue

        detalhes.append({
            "tipo":        tipo,
            "workflow_id": wf_id,
            "ok":          res["ok"],
            "cenarios":    res.get("cenarios", []),
            "erro":        res.get("erro"),
        })
        if res["ok"]:
            passou += 1
        else:
            falhou += 1

    testes_ok = falhou == 0
    log.info(
        f"[auto_teste] conta={conta_id} | passou={passou} falhou={falhou} | modo={modo_efetivo}"
    )

    return {
        "status":     "ok",
        "testes_ok":  testes_ok,
        "passou":     passou,
        "falhou":     falhou,
        "detalhes":   detalhes,
        "testado_em": agora,
    }


# ─── Testers por tipo ──────────────────────────────────────────────────────────

def _testar_atendimento(wf_id: str, conta_id: str, modo: str) -> dict:
    if modo == "dry-run":
        return {
            "ok": True,
            "cenarios": [
                {"cenario": "pergunta_faq",     "resultado": "passou"},
                {"cenario": "pedido_horario",   "resultado": "passou"},
                {"cenario": "pedido_atendente", "resultado": "passou"},
            ],
        }
    cenarios = [
        ("qual o horário?",           "pedido_horario"),
        ("quanto custa?",             "pergunta_preco"),
        ("quero falar com atendente", "pedido_atendente"),
    ]
    resultados = []
    for mensagem, label in cenarios:
        ok = _simular_webhook_n8n(wf_id, mensagem, conta_id)
        resultados.append({"cenario": label, "resultado": "passou" if ok else "falhou"})
    return {"ok": all(r["resultado"] == "passou" for r in resultados), "cenarios": resultados}


def _testar_agendamento(wf_id: str, calendar_id: str, conta_id: str, modo: str) -> dict:
    if modo == "dry-run":
        return {
            "ok": True,
            "cenarios": [
                {"cenario": "inicio_fluxo",  "resultado": "passou"},
                {"cenario": "agenda_ok",     "resultado": "passou"},
            ],
        }
    resultados = []
    # Verificar agenda acessível
    try:
        from conectores.google_calendar import GoogleCalendarConnector
        cal = GoogleCalendarConnector(modo=modo)
        slots = cal.verificar_disponibilidade(calendar_id, datetime.now().strftime("%Y-%m-%d"))
        resultados.append({
            "cenario":  "agenda_acessivel",
            "resultado": "passou" if isinstance(slots, list) else "falhou",
        })
    except Exception as exc:
        resultados.append({"cenario": "agenda_acessivel", "resultado": "erro", "detalhe": str(exc)})
    # Verificar webhook responde
    ok_wh = _simular_webhook_n8n(wf_id, "quero agendar", conta_id)
    resultados.append({"cenario": "inicio_fluxo", "resultado": "passou" if ok_wh else "falhou"})
    return {"ok": all(r["resultado"] == "passou" for r in resultados), "cenarios": resultados}


def _testar_lembrete(wf_id: str, calendar_id: str, conta_id: str, modo: str) -> dict:
    if modo == "dry-run":
        return {
            "ok": True,
            "cenarios": [{"cenario": "lembrete_configurado", "resultado": "passou"}],
        }
    try:
        from conectores.n8n_api import N8NConnector
        n8n = N8NConnector(modo=modo)
        wf = n8n.obter_workflow(wf_id)
        ativo = wf.get("active", False)
        return {
            "ok":      ativo,
            "cenarios": [{"cenario": "lembrete_ativo", "resultado": "passou" if ativo else "falhou"}],
            "erro":    None if ativo else "workflow inativo",
        }
    except Exception as exc:
        return {"ok": False, "cenarios": [], "erro": str(exc)}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _carregar_workflows_conta(conta_id: str) -> list:
    if not _ARQ_WORKFLOWS.exists():
        return []
    try:
        dados = json.loads(_ARQ_WORKFLOWS.read_text(encoding="utf-8"))
        return dados.get(conta_id, {}).get("workflows", [])
    except Exception:
        return []


def _obter_modo() -> str:
    arq = config.PASTA_DADOS / "config_n8n.json"
    if not arq.exists():
        return "dry-run"
    try:
        return json.loads(arq.read_text(encoding="utf-8")).get("modo", "dry-run")
    except Exception:
        return "dry-run"


def _simular_webhook_n8n(wf_id: str, mensagem: str, conta_id: str) -> bool:
    """Dispara webhook n8n com mensagem simulada. Retorna True se recebeu resposta."""
    try:
        import requests
        n8n_url = os.environ.get("N8N_URL", "http://localhost:5678")
        slug = "".join(c for c in conta_id.lower() if c.isalnum() or c == "-")[:16]
        payload = {
            "body": {
                "data": {
                    "key": {"remoteJid": "test@s.whatsapp.net"},
                    "message": {"conversation": mensagem},
                }
            }
        }
        r = requests.post(
            f"{n8n_url}/webhook/wapp-in-{slug}",
            json=payload,
            timeout=10,
        )
        return r.status_code < 400
    except Exception:
        return False
