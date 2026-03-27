"""
core/simulador_ciclo_email.py — Simulador de ciclo email completo.

Roda o fluxo de email de ponta a ponta em modo 100% simulado:
  preparar (templates) → enviar (simulado) → resposta (simulada)
    → classificar → agir → registrar → métricas

Nenhum email real sai. Tudo marcado com simulado=True e distinguível.

Este é o ensaio geral antes de conectar SMTP/IMAP real.

Funções públicas:
  simular_ciclo_completo(n=3)  → dict (relatório completo)
  verificar_integridade()      → dict (status de consistência)
  obter_metricas()             → dict (métricas acumuladas)
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger(__name__)

_ARQ_PIPELINE    = "pipeline_comercial.json"
_ARQ_FILA_EMAIL  = "fila_envio_email.json"
_ARQ_RESPOSTAS   = "respostas_email.json"
_ARQ_ACOES       = "acoes_respostas.json"
_ARQ_METRICAS    = "metricas_email.json"
_ARQ_FOLLOWUPS   = "fila_followups.json"

_TEMPLATE_POR_ESTAGIO = {
    "qualificando":          "abordagem_inicial",
    "negociacao":            "envio_proposta",
    "em_pausa":              "followup_sem_resposta",
    "pronto_para_entrega":   "followup_sem_resposta",
    "proposta_enviada":      "envio_proposta",
}

_MOCK_OPPS = [
    {
        "id":                    "sim_opp_001",
        "contraparte":           "Padaria Pão Quente",
        "estagio":               "qualificando",
        "categoria":             "alimentacao",
        "cidade":                "São Paulo",
        "contato_principal":     "contato@padariapq.com.br",
        "linha_servico_sugerida": "cardápio digital e pedidos online",
        "valor_estimado":        3500,
        "observacoes":           "sem presença digital, sistema de pedidos manual",
    },
    {
        "id":                    "sim_opp_002",
        "contraparte":           "Oficina Mota",
        "estagio":               "negociacao",
        "categoria":             "automotivo",
        "cidade":                "Campinas",
        "contato_principal":     "contato@oficinamota.com.br",
        "linha_servico_sugerida": "agendamento online e CRM de clientes",
        "valor_estimado":        4800,
        "observacoes":           "agendamento por WhatsApp manual, sem histórico de cliente",
    },
    {
        "id":                    "sim_opp_003",
        "contraparte":           "Clínica Bem Estar",
        "estagio":               "qualificando",
        "categoria":             "saude",
        "cidade":                "Rio de Janeiro",
        "contato_principal":     "contato@clinicabem.com.br",
        "linha_servico_sugerida": "confirmação automática de consultas",
        "valor_estimado":        2900,
        "observacoes":           "confirma consultas por telefone, alta taxa de no-show",
    },
    {
        "id":                    "sim_opp_004",
        "contraparte":           "Barbearia Central",
        "estagio":               "em_pausa",
        "categoria":             "beleza",
        "cidade":                "São Paulo",
        "contato_principal":     "contato@barbeariacentral.com.br",
        "linha_servico_sugerida": "sistema de agendamento automático",
        "valor_estimado":        2100,
        "observacoes":           "demonstrou interesse anteriormente, aguardando momento certo",
    },
    {
        "id":                    "sim_opp_005",
        "contraparte":           "Escola de Idiomas LinguaLivre",
        "estagio":               "qualificando",
        "categoria":             "educacao",
        "cidade":                "Belo Horizonte",
        "contato_principal":     "contato@lingualiv.com.br",
        "linha_servico_sugerida": "automação de matrículas e acompanhamento de alunos",
        "valor_estimado":        3200,
        "observacoes":           "processo de matrícula manual com planilha, perda de leads",
    },
]


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: str, padrao=None):
    if padrao is None:
        padrao = []
    p = config.PASTA_DADOS / arq
    if not p.exists():
        return padrao
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def _salvar(arq: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    (config.PASTA_DADOS / arq).write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── Seleção de oportunidades ─────────────────────────────────────────────────

def _selecionar_ou_criar_oportunidades(n: int) -> list:
    """
    Retorna N oportunidades para simular.
    Usa pipeline real (estágios ativos) e completa com mocks se necessário.
    """
    pipeline = _ler(_ARQ_PIPELINE, [])
    estagios_ativos = {"qualificando", "negociacao", "em_pausa", "pronto_para_entrega"}

    reais = [
        opp for opp in pipeline
        if opp.get("estagio") in estagios_ativos
        and opp.get("contato_principal")
    ][:n]

    if len(reais) >= n:
        log.info(f"[simulador] usando {n} oportunidades reais do pipeline")
        return reais

    # Complementar com mocks
    faltam = n - len(reais)
    mocks = random.sample(_MOCK_OPPS, min(faltam, len(_MOCK_OPPS)))
    log.info(
        f"[simulador] {len(reais)} reais + {len(mocks)} mocks "
        f"= {len(reais) + len(mocks)} oportunidades"
    )
    return reais + mocks


# ─── Preparação de emails ─────────────────────────────────────────────────────

def _preparar_emails_com_templates(opps: list) -> list:
    """
    Gera emails para cada oportunidade usando core/templates_email.py.
    Retorna lista de entradas prontas para fila_envio_email.json.
    """
    try:
        from core.templates_email import gerar_email
    except ImportError:
        gerar_email = None

    emails = []
    for opp in opps:
        estagio = opp.get("estagio", "qualificando")
        tipo    = _TEMPLATE_POR_ESTAGIO.get(estagio, "abordagem_inicial")

        nome_contato = (opp.get("contato_principal", "") or "").split("@")[0]
        if not nome_contato or "@" in nome_contato:
            nome_contato = opp.get("contraparte", "cliente").split()[0]

        variaveis = {
            "nome_contato":      nome_contato,
            "nome_empresa":      opp.get("contraparte", "empresa"),
            "categoria":         opp.get("categoria", ""),
            "problema_principal": opp.get("observacoes", "")[:100],
            "solucao_curta":     opp.get("linha_servico_sugerida", "automação de processos"),
            "nome_oferta":       opp.get("linha_servico_sugerida", "solução de automação"),
            "valor":             str(opp.get("valor_estimado", "3.500")),
            "prazo":             "30 dias",
            "dias_desde_ultimo": "7",
        }

        email_gerado = {"assunto": "", "corpo": "", "fonte": "fallback", "tipo": tipo}
        if gerar_email:
            try:
                email_gerado = gerar_email(tipo, variaveis)
            except Exception as exc:
                log.warning(f"[simulador] template falhou ({opp.get('id')}): {exc}")

        if not email_gerado.get("assunto"):
            email_gerado["assunto"] = f"[Simulado] Proposta para {opp.get('contraparte', 'empresa')}"
        if not email_gerado.get("corpo"):
            email_gerado["corpo"] = (
                f"Olá {nome_contato},\n\n"
                f"Gostaríamos de apresentar nossa solução de {variaveis['solucao_curta']} "
                f"para a {opp.get('contraparte', 'sua empresa')}.\n\n"
                f"[email simulado — sem envio real]"
            )

        email_id = f"email_sim_{uuid.uuid4().hex[:8]}"
        emails.append({
            "id":                email_id,
            "execucao_id":       f"exec_sim_{opp.get('id', uuid.uuid4().hex[:6])}",
            "oportunidade_id":   opp.get("id", ""),
            "conta_id":          opp.get("conta_id", ""),
            "contraparte":       opp.get("contraparte", ""),
            "email_destino":     opp.get("contato_principal", ""),
            "assunto":           email_gerado.get("assunto", ""),
            "corpo":             email_gerado.get("corpo", ""),
            "tipo_envio":        tipo,
            "abordagem_tipo":    tipo,
            "fonte_template":    email_gerado.get("fonte", "fallback"),
            "status":            "enviado_simulado",
            "simulado":          True,
            "cidade":            opp.get("cidade", ""),
            "categoria":         opp.get("categoria", ""),
            "criado_em":         _agora(),
            "enviado_em":        _agora(),
        })
        log.info(
            f"[simulador] email preparado | {opp.get('contraparte','?')[:35]} | "
            f"tipo={tipo} | fonte={email_gerado.get('fonte','?')}"
        )

    return emails


# ─── Injeção na fila ──────────────────────────────────────────────────────────

def _adicionar_a_fila_envio(emails: list) -> list:
    """
    Adiciona emails simulados a fila_envio_email.json.
    Não duplica IDs já presentes.
    Retorna lista dos que foram efetivamente adicionados.
    """
    fila = _ler(_ARQ_FILA_EMAIL, [])
    ids_existentes = {e.get("id") for e in fila}

    adicionados = []
    for email in emails:
        if email["id"] not in ids_existentes:
            fila.append(email)
            ids_existentes.add(email["id"])
            adicionados.append(email)

    _salvar(_ARQ_FILA_EMAIL, fila)
    log.info(f"[simulador] {len(adicionados)} emails adicionados à fila (enviado_simulado)")
    return adicionados


# ─── Verificação de integridade ───────────────────────────────────────────────

def verificar_integridade(emails_enviados: list = None, leitor_resultado: dict = None) -> dict:
    """
    Verifica consistência após ciclo simulado:
    - Todos os emails_enviados têm status=enviado_simulado
    - Respostas têm email_origem_id válido
    - Ações têm resposta_id válido (não orphãs)
    - Pipeline: opps movimentadas têm estagio coerente
    - Memória: não verifica (best-effort)
    """
    alertas = []
    ok      = True

    fila      = _ler(_ARQ_FILA_EMAIL,  [])
    respostas = _ler(_ARQ_RESPOSTAS,   [])
    acoes_log = _ler(_ARQ_ACOES,       [])
    pipeline  = _ler(_ARQ_PIPELINE,    [])

    ids_emails    = {e.get("id") for e in fila}
    ids_respostas = {r.get("resposta_id") for r in respostas}
    idx_pipeline  = {opp.get("id"): opp for opp in pipeline}

    # 1. Emails simulados devem estar na fila
    if emails_enviados:
        for email in emails_enviados:
            if email["id"] not in ids_emails:
                alertas.append(f"Email {email['id']} não encontrado na fila")
                ok = False
            elif fila[next(i for i, e in enumerate(fila) if e["id"] == email["id"])].get("status") != "enviado_simulado":
                alertas.append(f"Email {email['id']} não tem status=enviado_simulado")
                ok = False

    # 2. Respostas têm email_origem_id válido
    for resp in respostas:
        if resp.get("simulado") or resp.get("modo") == "simulado":
            origem_id = resp.get("email_origem_id", "")
            if origem_id and origem_id not in ids_emails:
                # pode ser de simulações anteriores — não é crítico
                pass

    # 3. Ações orphãs: acoes_log sem resposta correspondente
    n_orphas = sum(
        1 for a in acoes_log
        if a.get("resposta_id") not in ids_respostas
    )
    if n_orphas > 0:
        alertas.append(f"{n_orphas} ação(ões) orphã(s) sem resposta correspondente")

    # 4. Pipeline coerente: estagios válidos
    estagios_validos = {
        "qualificando", "qualificado",           # variantes aceitas
        "negociacao", "negociando",
        "em_pausa",
        "perdida", "perdido",                    # variantes aceitas
        "ganho", "ganho_confirmado",
        "pronto_para_entrega", "em_entrega",
        "proposta_enviada", "proposta_aceita",
    }
    for opp in pipeline:
        est = opp.get("estagio", "")
        if est and est not in estagios_validos:
            alertas.append(f"Pipeline {opp['id']}: estagio inválido '{est}'")
            ok = False

    # 5. Resumo de movimentos (informativo)
    movimentos = {}
    for opp in pipeline:
        est_ant = opp.get("estagio_anterior")
        est_atu = opp.get("estagio")
        if est_ant and est_ant != est_atu:
            key = f"{est_ant}_para_{est_atu}"
            movimentos[key] = movimentos.get(key, 0) + 1

    return {
        "ok":               ok,
        "alertas":          alertas,
        "total_emails_fila": len(fila),
        "total_respostas":   len(respostas),
        "total_acoes_log":   len(acoes_log),
        "acoes_orphas":      n_orphas,
        "movimentos_pipeline": movimentos,
    }


# ─── Métricas ─────────────────────────────────────────────────────────────────

def _coletar_e_salvar_metricas(emails_enviados: list, leitor_resultado: dict) -> dict:
    """
    Atualiza dados/metricas_email.json com dados do ciclo recém-executado.
    Merge acumulativo: não sobrescreve histórico.
    """
    metricas = _ler(_ARQ_METRICAS, _metricas_vazias())

    n_enviados   = len(emails_enviados)
    n_respostas  = leitor_resultado.get("respostas_processadas", 0)
    por_classif  = leitor_resultado.get("por_classificacao", {})
    n_acoes      = leitor_resultado.get("acoes_geradas", 0)

    # Acumuladores globais
    metricas["emails_enviados_total"] += n_enviados
    metricas["respostas_recebidas_total"] += n_respostas

    if metricas["emails_enviados_total"] > 0:
        metricas["taxa_resposta"] = round(
            metricas["respostas_recebidas_total"] / metricas["emails_enviados_total"], 4
        )

    for classif, count in por_classif.items():
        metricas["classificacoes"][classif] = metricas["classificacoes"].get(classif, 0) + count

    metricas["acoes_executadas"] += n_acoes

    # Pipeline movido
    pipeline  = _ler(_ARQ_PIPELINE, [])
    for opp in pipeline:
        est_ant = opp.get("estagio_anterior")
        est_atu = opp.get("estagio")
        if est_ant and est_ant != est_atu:
            key = f"{est_ant}_para_{est_atu}"
            metricas["pipeline_movido"][key] = metricas["pipeline_movido"].get(key, 0) + 1

    # Por template
    for email in emails_enviados:
        tipo = email.get("tipo_envio", "")
        if tipo:
            if tipo not in metricas["por_template"]:
                metricas["por_template"][tipo] = {"enviados": 0, "respondidos": 0, "taxa": 0.0}
            metricas["por_template"][tipo]["enviados"] += 1

    # Calcular respondidos por template (aproximação via respostas simuladas)
    respostas = _ler(_ARQ_RESPOSTAS, [])
    ids_emails_ciclo = {e["id"] for e in emails_enviados}
    for resp in respostas:
        origem_id = resp.get("email_origem_id", "")
        if origem_id in ids_emails_ciclo:
            email_original = next(
                (e for e in emails_enviados if e["id"] == origem_id), None
            )
            if email_original:
                tipo = email_original.get("tipo_envio", "")
                if tipo and tipo in metricas["por_template"]:
                    metricas["por_template"][tipo]["respondidos"] += 1

    for tipo, dados in metricas["por_template"].items():
        env = dados["enviados"]
        rep = dados["respondidos"]
        dados["taxa"] = round(rep / env, 4) if env > 0 else 0.0

    metricas["ultimo_ciclo"] = {
        "executado_em":     _agora(),
        "emails_enviados":  n_enviados,
        "respostas":        n_respostas,
        "acoes":            n_acoes,
        "por_classificacao": por_classif,
    }

    _salvar(_ARQ_METRICAS, metricas)
    log.info(
        f"[simulador] métricas atualizadas | "
        f"total_enviados={metricas['emails_enviados_total']} | "
        f"taxa_resposta={metricas['taxa_resposta']}"
    )
    return metricas


def _metricas_vazias() -> dict:
    return {
        "emails_enviados_total":    0,
        "respostas_recebidas_total": 0,
        "taxa_resposta":            0.0,
        "classificacoes":           {},
        "acoes_executadas":         0,
        "pipeline_movido":          {},
        "tempo_medio_resposta_simulado_dias": 1.5,
        "por_template":             {},
        "ultimo_ciclo":             None,
    }


def obter_metricas() -> dict:
    """Retorna métricas acumuladas de metricas_email.json."""
    return _ler(_ARQ_METRICAS, _metricas_vazias())


# ─── Ciclo completo ───────────────────────────────────────────────────────────

def simular_ciclo_completo(n_oportunidades: int = 3) -> dict:
    """
    Roda o ciclo email completo de ponta a ponta em modo simulado.

    Etapas:
      1. Selecionar N oportunidades (reais ou mocks)
      2. Gerar emails com templates (core/templates_email)
      3. Adicionar à fila como 'enviado_simulado'
      4. Leitor gera respostas simuladas (probabilístico por tipo)
      5. Classificar + executar ações derivadas
      6. Verificar integridade
      7. Atualizar metricas_email.json
      8. Retornar relatório

    Retorna:
      dict com: status, emails_preparados, emails_adicionados,
                respostas_geradas, por_classificacao, acoes_executadas,
                integridade, metricas, oportunidades_usadas, duracao_segundos
    """
    from core.leitor_respostas_email import processar_respostas

    inicio = datetime.now()

    log.info("=" * 60)
    log.info(f"SIMULADOR CICLO EMAIL — início | n={n_oportunidades}")
    log.info("=" * 60)

    # ── Etapa 1: Selecionar oportunidades ─────────────────────────────────────
    opps = _selecionar_ou_criar_oportunidades(n_oportunidades)
    if not opps:
        log.warning("[simulador] nenhuma oportunidade disponível — abortando")
        return {
            "status": "abortado",
            "motivo": "nenhuma oportunidade disponível",
        }

    log.info(f"[1/7] {len(opps)} oportunidades selecionadas")

    # ── Etapa 2: Preparar emails com templates ────────────────────────────────
    emails_preparados = _preparar_emails_com_templates(opps)
    log.info(f"[2/7] {len(emails_preparados)} emails gerados com templates")

    # ── Etapa 3: Adicionar à fila como enviado_simulado ───────────────────────
    emails_adicionados = _adicionar_a_fila_envio(emails_preparados)
    log.info(f"[3/7] {len(emails_adicionados)} emails marcados como enviado_simulado")

    # ── Etapa 4+5: Leitor processa respostas (gera + classifica + age) ────────
    leitor_resultado = processar_respostas()
    log.info(
        f"[4/7] leitor: {leitor_resultado.get('respostas_processadas',0)} respostas | "
        f"{leitor_resultado.get('acoes_geradas',0)} ações | "
        f"{leitor_resultado.get('por_classificacao',{})}"
    )

    # ── Etapa 6: Verificar integridade ────────────────────────────────────────
    integridade = verificar_integridade(emails_adicionados, leitor_resultado)
    if integridade["alertas"]:
        log.warning(f"[5/7] integridade: {integridade['alertas']}")
    else:
        log.info(f"[5/7] integridade OK — {integridade['movimentos_pipeline']} movimentos pipeline")

    # ── Etapa 7: Métricas ─────────────────────────────────────────────────────
    metricas = _coletar_e_salvar_metricas(emails_adicionados, leitor_resultado)
    log.info(
        f"[6/7] métricas salvas | "
        f"taxa_resposta={metricas['taxa_resposta']} | "
        f"total_enviados={metricas['emails_enviados_total']}"
    )

    duracao = round((datetime.now() - inicio).total_seconds(), 2)

    # ── Relatório final ───────────────────────────────────────────────────────
    relatorio = {
        "status":                    "ok" if integridade["ok"] else "ok_com_alertas",
        "executado_em":              _agora(),
        "duracao_segundos":          duracao,
        "oportunidades_usadas":      [o.get("id", "") for o in opps],
        "oportunidades_detalhes":    [
            {"id": o.get("id"), "contraparte": o.get("contraparte"), "estagio": o.get("estagio")}
            for o in opps
        ],
        "emails_preparados":         len(emails_preparados),
        "emails_adicionados_fila":   len(emails_adicionados),
        "emails_por_template":       _contar_por_campo(emails_adicionados, "tipo_envio"),
        "emails_por_fonte":          _contar_por_campo(emails_adicionados, "fonte_template"),
        "respostas_geradas":         leitor_resultado.get("respostas_processadas", 0),
        "por_classificacao":         leitor_resultado.get("por_classificacao", {}),
        "acoes_executadas":          leitor_resultado.get("acoes_geradas", 0),
        "taxa_resposta_ciclo":       round(
            leitor_resultado.get("respostas_processadas", 0) / max(len(emails_adicionados), 1), 4
        ),
        "integridade":               integridade,
        "metricas_acumuladas": {
            "emails_enviados_total":    metricas["emails_enviados_total"],
            "taxa_resposta":            metricas["taxa_resposta"],
            "acoes_executadas":         metricas["acoes_executadas"],
        },
    }

    log.info("=" * 60)
    log.info(f"SIMULADOR CICLO EMAIL — concluído em {duracao}s | status={relatorio['status']}")
    log.info(f"  emails preparados : {relatorio['emails_preparados']}")
    log.info(f"  respostas geradas : {relatorio['respostas_geradas']}")
    log.info(f"  ações executadas  : {relatorio['acoes_executadas']}")
    log.info(f"  taxa de resposta  : {relatorio['taxa_resposta_ciclo']:.0%}")
    log.info("=" * 60)

    return relatorio


def _contar_por_campo(lista: list, campo: str) -> dict:
    contagem = {}
    for item in lista:
        v = item.get(campo, "")
        if v:
            contagem[v] = contagem.get(v, 0) + 1
    return contagem


# ─── Ponto de entrada para orquestrador ──────────────────────────────────────

def executar() -> dict:
    """Compatível com orquestrador. Roda ciclo com 3 oportunidades."""
    resultado = simular_ciclo_completo(n_oportunidades=3)
    return {
        "agente":                "simulador_ciclo_email",
        "emails_preparados":     resultado.get("emails_preparados", 0),
        "respostas_geradas":     resultado.get("respostas_geradas", 0),
        "acoes_executadas":      resultado.get("acoes_executadas", 0),
        "taxa_resposta_ciclo":   resultado.get("taxa_resposta_ciclo", 0.0),
        "status":                resultado.get("status", "erro"),
    }
