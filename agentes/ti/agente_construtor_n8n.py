"""
agentes/ti/agente_construtor_n8n.py — Construtor autônomo de fluxos n8n.

Cria, configura, testa e registra workflows de bot WhatsApp no n8n
sem nenhuma intervenção manual na interface.

Fluxo para um cliente novo:
  1. construir_bot_atendimento(conta_id, dados_formulario)
     → Carrega template → substitui variáveis → cria workflow → ativa → testa → registra
  2. construir_bot_agendamento(conta_id, dados_formulario)
     → Idem, para o bot de agendamento
  3. construir_lembrete(conta_id, calendar_id, numero)
     → Workflow de lembrete 2h antes do horário

Integração com agente de entrega:
  Quando o checklist de entrega chegar na etapa "Configurar bot",
  o agente_operacao_entrega chama:
      from agentes.ti.agente_construtor_n8n import AgenteConstrutorN8N
      construtor = AgenteConstrutorN8N()
      resultado  = construtor.construir_bot_atendimento(conta_id, dados_formulario)

Registro por conta:
  dados/workflows_por_conta.json — workflow_id + tipo + status por conta_id
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from conectores.n8n_api import N8NConnector, obter_conector
from core.persistencia import carregar_json_fixo, salvar_json_fixo

logger = logging.getLogger(__name__)

# ─── Caminhos ─────────────────────────────────────────────────────────────────

_DIR_TEMPLATES   = Path(__file__).parent.parent.parent / "dados" / "templates_n8n"
_ARQ_WORKFLOWS   = config.PASTA_DADOS / "workflows_por_conta.json"
_ARQ_FEED        = config.PASTA_DADOS / "feed_eventos_empresa.json"

_TEMPLATES = {
    "atendimento": _DIR_TEMPLATES / "template_atendimento_whatsapp.json",
    "agendamento": _DIR_TEMPLATES / "template_agendamento_whatsapp.json",
    "lembrete":    _DIR_TEMPLATES / "template_lembrete_agendamento.json",
}

# URL padrão da Vetor API (conselho_app FastAPI)
_CALENDARIO_VETOR_URL_PADRAO = os.environ.get("VETOR_API_URL", "http://localhost:8000")
_EVOLUTION_API_URL_PADRAO    = os.environ.get("EVOLUTION_API_URL", "http://localhost:8080")


# ─── Helpers de I/O ───────────────────────────────────────────────────────────

def _carregar_workflows() -> dict:
    try:
        return carregar_json_fixo(_ARQ_WORKFLOWS.name, _ARQ_WORKFLOWS.parent) or {}
    except Exception:
        return {}


def _salvar_workflows(dados: dict) -> None:
    salvar_json_fixo(dados, _ARQ_WORKFLOWS.name, _ARQ_WORKFLOWS.parent)


def _registrar_feed(evento: str, detalhes: dict) -> None:
    try:
        feed = carregar_json_fixo(_ARQ_FEED.name, _ARQ_FEED.parent) or []
        feed.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "agente":    "construtor_n8n",
            "evento":    evento,
            **detalhes,
        })
        salvar_json_fixo(feed[-500:], _ARQ_FEED.name, _ARQ_FEED.parent)
    except Exception as _err:
        logger.warning("erro ignorado: %s", _err)


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── Substituição de variáveis ────────────────────────────────────────────────

def _substituir_variaveis(template_str: str, variaveis: dict) -> str:
    """
    Substitui {{KEY}} no texto do template.

    Dois casos:
    1. Valor dict/list → "{{KEY}}" (com aspas) é trocado pelo JSON raw, sem aspas.
    2. Valor string    → {{KEY}} dentro de uma string é trocado pelo valor JSON-safe.
    """
    # Passagem 1: dict/list → substitui `"{{KEY}}"` (com aspas externas) por JSON cru
    for chave, valor in variaveis.items():
        if isinstance(valor, (dict, list)):
            quoted_ph = '"{{' + chave + '}}"'
            template_str = template_str.replace(quoted_ph, json.dumps(valor, ensure_ascii=False))

    # Passagem 2: strings → substitui {{KEY}} no contexto de string JSON
    for chave, valor in variaveis.items():
        placeholder = "{{" + chave + "}}"
        if placeholder in template_str:
            # json.dumps do valor e remove as aspas externas → dá string JSON-safe
            safe = json.dumps(str(valor), ensure_ascii=False)[1:-1]
            template_str = template_str.replace(placeholder, safe)

    return template_str


def _carregar_template(tipo: str) -> dict:
    """Carrega e parseia um template JSON."""
    arq = _TEMPLATES.get(tipo)
    if not arq or not arq.exists():
        raise FileNotFoundError(f"Template '{tipo}' não encontrado em {_DIR_TEMPLATES}")
    return json.loads(arq.read_text(encoding="utf-8"))


def _aplicar_template(tipo: str, variaveis: dict) -> dict:
    """Carrega template, substitui variáveis e retorna workflow JSON."""
    template_str = _TEMPLATES[tipo].read_text(encoding="utf-8")
    preenchido   = _substituir_variaveis(template_str, variaveis)
    try:
        wf = json.loads(preenchido)
        # Remove metadados internos antes de enviar ao n8n
        wf.pop("_meta", None)
        return wf
    except json.JSONDecodeError as e:
        raise ValueError(f"Template '{tipo}' inválido após substituição: {e}") from e


# ─── Helpers de formatação ────────────────────────────────────────────────────

def _horarios_para_texto(horarios) -> str:
    """Converte dict de horários ou texto para string legível."""
    if isinstance(horarios, str):
        return horarios
    if isinstance(horarios, dict):
        dias = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
        nomes = {"seg": "Seg", "ter": "Ter", "qua": "Qua", "qui": "Qui",
                 "sex": "Sex", "sab": "Sáb", "dom": "Dom"}
        partes = []
        for dia in dias:
            cfg_dia = horarios.get(dia)
            if cfg_dia and not cfg_dia.get("fechado"):
                ini = cfg_dia.get("inicio", "")
                fim = cfg_dia.get("fim", "")
                if ini and fim:
                    partes.append(f"{nomes[dia]}: {ini}–{fim}")
        return " | ".join(partes) if partes else str(horarios)
    return str(horarios)


def _instance_para_conta(conta_id: str) -> str:
    """Gera nome de instância Evolution API a partir do conta_id."""
    slug = "".join(c for c in conta_id.lower() if c.isalnum() or c == "-")[:16]
    return f"vetor-{slug}"


# ─── Registro por conta ───────────────────────────────────────────────────────

def _registrar_workflow(conta_id: str, tipo: str, workflow_id: str, extra: dict = None) -> None:
    dados = _carregar_workflows()
    conta = dados.setdefault(conta_id, {"workflows": []})
    conta["workflows"].append({
        "tipo":        tipo,
        "workflow_id": workflow_id,
        "ativo":       True,
        "criado_em":   _agora(),
        **(extra or {}),
    })
    _salvar_workflows(dados)


def _workflows_da_conta(conta_id: str) -> list:
    dados = _carregar_workflows()
    return dados.get(conta_id, {}).get("workflows", [])


# ─── Classe principal ─────────────────────────────────────────────────────────

class AgenteConstrutorN8N:
    """
    Constrói workflows n8n para clientes da Vetor de forma autônoma.

    Usa dry-run por padrão — os JSONs são montados e validados,
    mas nenhum workflow é criado no n8n real até modo='real'.
    """

    def __init__(self, modo: str = None):
        self.n8n  = obter_conector(modo=modo)
        self.modo = self.n8n.modo
        logger.info(f"[ConstrutorN8N] inicializado modo={self.modo}")

    # ─── Bot de atendimento ────────────────────────────────────────────────────

    def construir_bot_atendimento(self, conta_id: str, dados_formulario: dict) -> dict:
        """
        Cria bot de atendimento WhatsApp para a conta.

        dados_formulario esperado (saída de core/formularios_entrega.py):
          nome_negocio       str
          faqs               list[{pergunta, resposta}]
          horarios           dict | str
          numero_encaminhamento  str (WhatsApp do dono para transferência)

        Retorna:
          status, workflow_id, testes_ok, workflow_json (em dry-run)
        """
        logger.info(f"[ConstrutorN8N] construir_bot_atendimento conta={conta_id}")

        faqs     = dados_formulario.get("faqs", [])
        horarios = _horarios_para_texto(dados_formulario.get("horarios", ""))
        instance = _instance_para_conta(conta_id)

        variaveis = {
            "NOME_NEGOCIO":         dados_formulario.get("nome_negocio", "Negócio"),
            "EVOLUTION_API_URL":    _EVOLUTION_API_URL_PADRAO,
            "EVOLUTION_INSTANCE":   instance,
            "FAQS_JSON":            json.dumps(faqs, ensure_ascii=False),
            "HORARIOS_TEXTO":       horarios,
            "NUMERO_ENCAMINHAMENTO": dados_formulario.get("numero_encaminhamento",
                                      dados_formulario.get("whatsapp", "")),
        }

        return self._construir_e_registrar(
            conta_id=conta_id,
            tipo="atendimento",
            variaveis=variaveis,
            cenarios_teste=self._cenarios_atendimento(faqs),
        )

    # ─── Bot de agendamento ────────────────────────────────────────────────────

    def construir_bot_agendamento(self, conta_id: str, dados_formulario: dict) -> dict:
        """
        Cria bot de agendamento WhatsApp para a conta.

        dados_formulario esperado:
          nome_negocio  str
          servicos      list[{nome, duracao}]
          calendar_id   str (do Google Calendar connector)
        """
        logger.info(f"[ConstrutorN8N] construir_bot_agendamento conta={conta_id}")

        servicos    = dados_formulario.get("servicos", [])
        calendar_id = dados_formulario.get("calendar_id", "")
        instance    = _instance_para_conta(conta_id)

        variaveis = {
            "NOME_NEGOCIO":          dados_formulario.get("nome_negocio", "Negócio"),
            "EVOLUTION_API_URL":     _EVOLUTION_API_URL_PADRAO,
            "EVOLUTION_INSTANCE":    instance,
            "SERVICOS_JSON":         json.dumps(servicos, ensure_ascii=False),
            "CALENDARIO_VETOR_URL":  _CALENDARIO_VETOR_URL_PADRAO,
            "CALENDAR_ID":           calendar_id,
        }

        return self._construir_e_registrar(
            conta_id=conta_id,
            tipo="agendamento",
            variaveis=variaveis,
            cenarios_teste=self._cenarios_agendamento(servicos),
            extra={"calendar_id": calendar_id},
        )

    # ─── Workflow de lembrete ──────────────────────────────────────────────────

    def construir_lembrete(self, conta_id: str, calendar_id: str, numero: str) -> dict:
        """
        Cria workflow de lembrete automático 2h antes do agendamento.

        Parâmetros:
          conta_id:    ID da conta
          calendar_id: ID do Google Calendar da conta
          numero:      número WhatsApp do negócio (Evolution instance)
        """
        logger.info(f"[ConstrutorN8N] construir_lembrete conta={conta_id}")

        instance = _instance_para_conta(conta_id)

        variaveis = {
            "EVOLUTION_API_URL":    _EVOLUTION_API_URL_PADRAO,
            "EVOLUTION_INSTANCE":   instance,
            "CALENDARIO_VETOR_URL": _CALENDARIO_VETOR_URL_PADRAO,
            "CALENDAR_ID":          calendar_id,
        }

        return self._construir_e_registrar(
            conta_id=conta_id,
            tipo="lembrete",
            variaveis=variaveis,
            cenarios_teste=[],  # lembrete não tem webhook, skip teste
            extra={"calendar_id": calendar_id},
        )

    # ─── Desativar todos os workflows da conta ─────────────────────────────────

    def desativar_workflows_conta(self, conta_id: str) -> int:
        """
        Desativa todos os workflows ativos de uma conta (ex: cliente cancelou).

        Retorna número de workflows desativados.
        """
        logger.info(f"[ConstrutorN8N] desativar_workflows_conta conta={conta_id}")

        dados   = _carregar_workflows()
        conta   = dados.get(conta_id, {})
        wfs     = conta.get("workflows", [])
        total   = 0

        for wf in wfs:
            if wf.get("ativo"):
                ok = self.n8n.desativar_workflow(wf["workflow_id"])
                if ok:
                    wf["ativo"] = False
                    wf["desativado_em"] = _agora()
                    total += 1

        _salvar_workflows(dados)
        _registrar_feed("workflows_desativados", {"conta_id": conta_id, "total": total})
        logger.info(f"[ConstrutorN8N] {total} workflows desativados para {conta_id}")
        return total

    # ─── Atualizar FAQs sem recriar ────────────────────────────────────────────

    def atualizar_faqs(self, conta_id: str, novas_faqs: list) -> dict:
        """
        Atualiza as FAQs do bot de atendimento sem recriar o workflow.

        Localiza o nó 'Configuração' no workflow de atendimento da conta,
        atualiza o campo 'faqs' e salva via API.
        """
        logger.info(f"[ConstrutorN8N] atualizar_faqs conta={conta_id} n={len(novas_faqs)}")

        wfs = _workflows_da_conta(conta_id)
        wf_atend = next((w for w in wfs if w["tipo"] == "atendimento" and w.get("ativo")), None)

        if not wf_atend:
            return {"status": "erro", "motivo": "Workflow de atendimento não encontrado para esta conta."}

        wf_id = wf_atend["workflow_id"]
        faqs_json = json.dumps(novas_faqs, ensure_ascii=False)

        if self.modo == "dry-run":
            logger.info(f"[ConstrutorN8N] dry-run: FAQs atualizadas (não enviado ao n8n)")
            return {
                "status":      "ok",
                "workflow_id": wf_id,
                "faqs_novas":  len(novas_faqs),
                "modo":        "dry-run",
            }

        try:
            wf = self.n8n.obter_workflow(wf_id)
            nodes = wf.get("nodes", [])

            # Localiza nó Configuração e atualiza stringValue das FAQs
            atualizado = False
            for node in nodes:
                if node.get("name") == "Configuração":
                    valores = node.get("parameters", {}).get("fields", {}).get("values", [])
                    for campo in valores:
                        if campo.get("name") == "faqs":
                            campo["stringValue"] = faqs_json
                            atualizado = True
                    break

            if not atualizado:
                return {"status": "erro", "motivo": "Nó 'Configuração' não encontrado no workflow."}

            wf["nodes"] = nodes
            self.n8n.atualizar_workflow(wf_id, wf)
            _registrar_feed("faqs_atualizadas", {"conta_id": conta_id, "total_faqs": len(novas_faqs)})

            return {"status": "ok", "workflow_id": wf_id, "faqs_novas": len(novas_faqs)}

        except Exception as exc:
            logger.error(f"[ConstrutorN8N] Erro ao atualizar FAQs {conta_id}: {exc}")
            return {"status": "erro", "motivo": str(exc)}

    # ─── Pipeline interna ──────────────────────────────────────────────────────

    def _construir_e_registrar(
        self,
        conta_id:       str,
        tipo:           str,
        variaveis:      dict,
        cenarios_teste: list,
        extra:          dict = None,
    ) -> dict:
        """
        Pipeline completa: montar → criar → ativar → testar → registrar.
        """
        # 1. Montar workflow JSON a partir do template
        try:
            wf_json = _aplicar_template(tipo, variaveis)
        except Exception as exc:
            return {"status": "erro", "etapa": "template", "motivo": str(exc)}

        # 2. Criar no n8n
        try:
            criado = self.n8n.criar_workflow(wf_json)
        except Exception as exc:
            return {"status": "erro", "etapa": "criar", "motivo": str(exc)}

        wf_id = criado.get("id", "")

        # 3. Ativar
        try:
            self.n8n.ativar_workflow(wf_id)
        except Exception as exc:
            logger.warning(f"[ConstrutorN8N] Falha ao ativar {wf_id}: {exc}")

        # 4. Testar (3 cenários)
        resultados_teste = []
        testes_ok = True
        for cenario in cenarios_teste[:3]:
            try:
                r = self.n8n.executar_workflow(wf_id, cenario)
                passou = r.get("status") == "success"
                resultados_teste.append({"cenario": cenario.get("_descricao", "?"), "ok": passou})
                if not passou:
                    testes_ok = False
            except Exception as exc:
                resultados_teste.append({"cenario": cenario.get("_descricao", "?"), "ok": False, "erro": str(exc)})
                testes_ok = False

        # 5. Registrar
        _registrar_workflow(conta_id, tipo, wf_id, extra)
        _registrar_feed(
            f"workflow_{tipo}_criado",
            {"conta_id": conta_id, "workflow_id": wf_id, "testes_ok": testes_ok},
        )

        if not testes_ok:
            logger.warning(
                f"[ConstrutorN8N] Workflow {wf_id} criado mas testes falharam — escalar."
            )

        resultado = {
            "status":          "ok" if testes_ok else "criado_com_falhas",
            "workflow_id":     wf_id,
            "tipo":            tipo,
            "conta_id":        conta_id,
            "testes_ok":       testes_ok,
            "resultados_teste": resultados_teste,
            "modo":            self.modo,
            "criado_em":       criado.get("createdAt", ""),
        }

        if self.modo == "dry-run":
            resultado["workflow_json"] = wf_json

        return resultado

    # ─── Cenários de teste ─────────────────────────────────────────────────────

    @staticmethod
    def _cenarios_atendimento(faqs: list) -> list:
        """Gera 3 cenários de teste para o bot de atendimento."""
        # Tenta usar uma FAQ real, senão usa genérico
        pergunta_faq = faqs[0]["pergunta"].split(",")[0].strip() if faqs else "informações"

        return [
            {
                "_descricao": "pergunta_faq",
                "data": {
                    "key":     {"remoteJid": "5517999000001@s.whatsapp.net"},
                    "message": {"conversation": pergunta_faq},
                },
            },
            {
                "_descricao": "pedido_horario",
                "data": {
                    "key":     {"remoteJid": "5517999000002@s.whatsapp.net"},
                    "message": {"conversation": "qual o horário de funcionamento"},
                },
            },
            {
                "_descricao": "pedido_atendente",
                "data": {
                    "key":     {"remoteJid": "5517999000003@s.whatsapp.net"},
                    "message": {"conversation": "quero falar com atendente"},
                },
            },
        ]

    @staticmethod
    def _cenarios_agendamento(servicos: list) -> list:
        """Gera cenários de teste para o bot de agendamento."""
        return [
            {
                "_descricao": "inicio_conversa",
                "data": {
                    "key":     {"remoteJid": "5517999000004@s.whatsapp.net"},
                    "message": {"conversation": "oi"},
                },
            },
            {
                "_descricao": "escolha_servico",
                "data": {
                    "key":     {"remoteJid": "5517999000004@s.whatsapp.net"},
                    "message": {"conversation": "1"},
                },
            },
            {
                "_descricao": "escolha_data",
                "data": {
                    "key":     {"remoteJid": "5517999000004@s.whatsapp.net"},
                    "message": {"conversation": "15/05"},
                },
            },
        ]


# ─── Factory ──────────────────────────────────────────────────────────────────

def obter_agente(modo: str = None) -> AgenteConstrutorN8N:
    """Retorna instância configurada do agente construtor."""
    return AgenteConstrutorN8N(modo=modo)


# ─── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    agente = obter_agente()
    print(f"\nModo: {agente.modo}\n")

    # ── Bot de atendimento
    dados_atend = {
        "nome_negocio": "Barbearia do Carlos",
        "faqs": [
            {"pergunta": "preço,valor,quanto custa", "resposta": "Corte a partir de R$ 35. Corte + barba R$ 55."},
            {"pergunta": "aceita cartão,cartão",      "resposta": "Sim! Aceitamos débito, crédito e Pix."},
            {"pergunta": "estacionamento,estacionar", "resposta": "Temos estacionamento gratuito na lateral."},
        ],
        "horarios": {
            "seg": {"inicio": "09:00", "fim": "18:00"},
            "ter": {"inicio": "09:00", "fim": "18:00"},
            "qua": {"inicio": "09:00", "fim": "18:00"},
            "qui": {"inicio": "09:00", "fim": "18:00"},
            "sex": {"inicio": "09:00", "fim": "18:00"},
            "sab": {"inicio": "08:00", "fim": "14:00"},
        },
        "numero_encaminhamento": "5517999887766",
    }

    r_atend = agente.construir_bot_atendimento("emp_barbearia_carlos", dados_atend)
    print(f"construir_bot_atendimento: status={r_atend['status']} | wf_id={r_atend['workflow_id']}")
    print(f"  testes_ok={r_atend['testes_ok']}")
    for t in r_atend.get("resultados_teste", []):
        print(f"  [{'+' if t['ok'] else 'X'}] {t['cenario']}")

    # ── Bot de agendamento
    dados_ag = {
        "nome_negocio": "Barbearia do Carlos",
        "servicos": [
            {"nome": "Corte", "duracao": 30},
            {"nome": "Corte + Barba", "duracao": 60},
            {"nome": "Barba", "duracao": 30},
        ],
        "calendar_id": "dry-run-agenda-abc123@group.calendar.google.com",
    }

    r_ag = agente.construir_bot_agendamento("emp_barbearia_carlos", dados_ag)
    print(f"\nconstruir_bot_agendamento: status={r_ag['status']} | wf_id={r_ag['workflow_id']}")

    # ── Lembrete
    r_lem = agente.construir_lembrete(
        "emp_barbearia_carlos",
        "dry-run-agenda-abc123@group.calendar.google.com",
        "5517999887766",
    )
    print(f"\nconstruir_lembrete: status={r_lem['status']} | wf_id={r_lem['workflow_id']}")

    # ── Atualizar FAQs
    novas = [{"pergunta": "preço", "resposta": "Corte a partir de R$ 40."}]
    r_faq = agente.atualizar_faqs("emp_barbearia_carlos", novas)
    print(f"\natualizar_faqs: {r_faq}")

    # ── Desativar (não desativa em dry-run, mas conta o total)
    total_desativ = agente.desativar_workflows_conta("emp_barbearia_carlos")
    print(f"\ndesativar_workflows_conta: {total_desativ} workflows desativados")

    # ── Verificar registro
    from agentes.ti.agente_construtor_n8n import _workflows_da_conta
    wfs = _workflows_da_conta("emp_barbearia_carlos")
    print(f"\nWorkflows registrados para emp_barbearia_carlos: {len(wfs)}")
    for w in wfs:
        print(f"  {w['tipo']:12} | {w['workflow_id']} | ativo={w.get('ativo')}")
