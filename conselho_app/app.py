"""
conselho_app/app.py — Painel do Conselho (web interno).

Serve as paginas HTML do painel lendo os arquivos de observabilidade
gerados pelo ciclo da empresa.

Rodar com:
  python main_conselho.py
  ou:
  uvicorn conselho_app.app:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import sys
from pathlib import Path

# Garantir que o raiz do projeto esteja no path
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config

app = FastAPI(title="Painel do Conselho", docs_url=None, redoc_url=None)

_STATIC_DIR    = Path(__file__).parent / "static"
_TEMPLATE_DIR  = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

# Jinja2 global: badge de alerta de TI (lido a cada render, sem custo relevante)
def _ti_tem_alerta() -> bool:
    try:
        rel = json.loads((config.PASTA_DADOS / "relatorio_seguranca.json").read_text(encoding="utf-8"))
        if rel.get("resumo", {}).get("criticas", 0) > 0:
            return True
    except Exception:
        pass
    try:
        inc = json.loads((config.PASTA_DADOS / "incidentes_executor.json").read_text(encoding="utf-8"))
        from datetime import datetime, timedelta
        limite = datetime.now() - timedelta(hours=48)
        for i in inc:
            if i.get("tipo") == "rollback":
                ts = datetime.fromisoformat(i.get("timestamp", "2000-01-01"))
                if ts >= limite:
                    return True
    except Exception:
        pass
    return False

templates.env.globals["ti_tem_alerta"] = _ti_tem_alerta


# ─── Helpers de leitura ───────────────────────────────────────────────────────

def _ler(nome: str, padrao=None):
    if padrao is None:
        padrao = {}
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def _painel():
    return _ler("painel_conselho.json", {})


def _metricas():
    return _ler("metricas_empresa.json", {})


def _areas():
    return _ler("metricas_areas.json", {})


def _agentes():
    return _ler("metricas_agentes.json", [])


def _feed():
    return _ler("feed_eventos_empresa.json", {"eventos": [], "total": 0, "gerado_em": "—"})


# ─── Páginas HTML ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def pagina_index(request: Request):
    painel   = _painel()
    metricas = _metricas()
    from core.governanca_conselho import resumir_governanca_ativa
    saude = painel.get("saude", _ler("saude_empresa.json", {}))
    # Resumo mínimo de provisionamento para card da homepage
    try:
        from core.provisionamento_canais import resumir_para_painel as _resumir_prov
        _prov = _resumir_prov()
        prov_resumo = {
            "status_geral": _prov["status_geral"],
            "dominio":      _prov["provisionamento"].get("dominio_planejado", "—"),
            "pendencias":   len(_prov["bloqueios"]),
            "apto":         _prov["apto"],
        }
    except Exception:
        prov_resumo = {}
    # Resumo de ofertas para card da homepage
    try:
        from core.ofertas_empresa import resumir_para_painel as _resumir_ofertas
        ofertas_resumo = _resumir_ofertas()
    except Exception:
        ofertas_resumo = {}
    # Resumo de propostas para card da homepage
    try:
        from core.propostas_empresa import resumir_para_painel as _resumir_propostas
        from core.expediente_propostas import resumir_para_painel as _resumir_exp
        propostas_resumo = _resumir_propostas()
        propostas_resumo["_exp"] = _resumir_exp()
    except Exception:
        propostas_resumo = {}
    # Resumo de contas/clientes para card da homepage
    try:
        from core.contas_empresa import resumir_para_painel as _resumir_contas
        contas_resumo = _resumir_contas()
    except Exception:
        contas_resumo = {}
    # Resumo de acompanhamento pós-entrega
    try:
        from core.acompanhamento_contas import resumir_para_painel as _resumir_acomp
        acomp_resumo = _resumir_acomp()
    except Exception:
        acomp_resumo = {}
    # Resumo de contratos/faturamento
    try:
        from core.contratos_empresa import resumir_para_painel as _resumir_ct
        contratos_resumo = _resumir_ct()
    except Exception:
        contratos_resumo = {}
    # Resumo LLM para card da homepage
    try:
        from core.llm_log import resumo_custos_dia as _rcdia
        llm_resumo = _rcdia()
        llm_resumo["modo"] = getattr(config, "LLM_MODO", "dry-run")
    except Exception:
        llm_resumo = {}
    # Resumo NPS para card da homepage
    try:
        from core.nps_feedback import calcular_nps_empresa as _calc_nps
        nps_resumo = _calc_nps()
    except Exception:
        nps_resumo = {}
    # Resumo TI para cards da homepage
    try:
        _rel_seg  = _ler("relatorio_seguranca.json", None)
        _rel_qual = _ler("relatorio_qualidade.json", None)
        _rel_mel  = _ler("relatorio_melhorias.json", None)
        _hist_mel = _ler("historico_melhorias.json", [])
        ti_resumo = {
            "score_seguranca":  _rel_seg["resumo"]["score_seguranca"]  if _rel_seg  else None,
            "total_vulns":      _rel_seg["resumo"]["total_vulnerabilidades"] if _rel_seg else None,
            "score_qualidade":  _rel_qual["score_qualidade"] if _rel_qual else None,
            "taxa_testes":      _rel_qual["testes"]["taxa_sucesso"] if _rel_qual else None,
            "melhorias_aplic":  sum(h.get("aplicadas", 0) for h in _hist_mel),
            "pendentes_llm":    _rel_mel["pendentes_llm_real"] if _rel_mel else 0,
            "modo_executor":    _ler("politicas_ti.json", {}).get("executor", {}).get("modo", "dry-run"),
        }
    except Exception:
        ti_resumo = {}
    # Resumo canais para card da homepage
    try:
        from core.canais import CanalEmail as _CE2, CanalWhatsApp as _CW2, CanalTelefone as _CT2
        _modos = []
        _fila_total = 0
        for _cls in (_CE2, _CW2, _CT2):
            try:
                _st = _cls().status()
                _modos.append(_st.get("modo", "dry-run"))
                _fila_total += _st.get("fila_pendente", 0)
            except Exception:
                _modos.append("dry-run")
        canais_resumo = {
            "ativos":    sum(1 for m in _modos if m != "dry-run"),
            "em_fila":   _fila_total,
            "dry_run":   sum(1 for m in _modos if m == "dry-run"),
        }
    except Exception:
        canais_resumo = {}
    # Resumo multi-cidade para card da homepage
    try:
        import json as _json_mc
        from collections import defaultdict as _ddc
        _pipe = _json_mc.loads((config.PASTA_DADOS / "pipeline_comercial.json").read_text(encoding="utf-8"))
        _cids: dict = _ddc(lambda: {"leads": 0, "oport": 0})
        for _it in _pipe:
            _c = (_it.get("cidade") or "").strip()
            if _c:
                _cids[_c]["leads"] += 1
                if _it.get("status", "") not in ("descartada", "perdida"):
                    _cids[_c]["oport"] += 1
        cidades_resumo = {
            "total_cidades":     len(_cids),
            "total_leads":       sum(v["leads"] for v in _cids.values()),
            "total_oportunidades": sum(v["oport"] for v in _cids.values()),
        }
    except Exception:
        cidades_resumo = {}
    # Métricas de email para card da homepage
    try:
        _em  = _ler("metricas_email.json", {})
        _cfg = _ler("config_canal_email.json", {})
        email_card = {
            "modo":      _cfg.get("modo", "desativado"),
            "enviados":  _em.get("emails_enviados_total", 0),
            "taxa":      round(_em.get("taxa_resposta", 0) * 100, 1),
            "respostas": _em.get("respostas_recebidas_total", 0),
        }
    except Exception:
        email_card = {}
    # Resumo scheduler para card da homepage
    try:
        from datetime import datetime as _dt
        _estado_sched = _ler("scheduler_estado.json", {})
        _log_sched    = _ler("scheduler_log.json", [])
        _hoje_str     = _dt.now().strftime("%Y-%m-%d")
        _exec_hoje    = _estado_sched.get("execucoes_hoje", {})
        _ciclos_hoje  = sum(len(v) for v in _exec_hoje.values()) if isinstance(_exec_hoje, dict) else 0
        _erros_hoje   = sum(1 for e in _log_sched
                            if e.get("status") == "erro"
                            and e.get("inicio", "")[:10] == _hoje_str)
        scheduler_resumo = {
            "ativo":          getattr(config, "SCHEDULER_ATIVO", True),
            "ultima_verif":   _estado_sched.get("ultima_verificacao", "—"),
            "proximo":        _estado_sched.get("proximo_agendado"),
            "ciclos_hoje":    _ciclos_hoje,
            "erros_hoje":     _erros_hoje,
        }
    except Exception:
        scheduler_resumo = {}
    return templates.TemplateResponse("index.html", {
        "request":        request,
        "page":           "index",
        "status":         painel.get("status_empresa", "desconhecido"),
        "atualizado_em":  painel.get("atualizado_em", "—"),
        "ultimo_ciclo":   painel.get("ultimo_ciclo", {}),
        "gargalos":       painel.get("gargalos", []),
        "deliberacoes":   painel.get("deliberacoes", {}),
        "proximas_acoes": painel.get("proximas_acoes_relevantes", []),
        "metricas":       metricas,
        "gov":            resumir_governanca_ativa(),
        "saude":          saude,
        "prov_email":       prov_resumo,
        "ofertas_resumo":   ofertas_resumo,
        "propostas_resumo": propostas_resumo,
        "contas_resumo":    contas_resumo,
        "acomp_resumo":     acomp_resumo,
        "contratos_resumo": contratos_resumo,
        "llm_resumo":       llm_resumo,
        "scheduler_resumo": scheduler_resumo,
        "nps_resumo":       nps_resumo,
        "ti_resumo":        ti_resumo,
        "canais_resumo":    canais_resumo,
        "cidades_resumo":   cidades_resumo,
        "email_card":       email_card,
    })


@app.get("/agentes", response_class=HTMLResponse)
async def pagina_agentes(request: Request):
    from core.governanca_conselho import resumir_governanca_ativa
    from datetime import datetime
    log_sched = _ler("scheduler_log.json", [])
    log_llm   = _ler("log_llm.json", [])
    hoje      = datetime.now().strftime("%Y-%m-%d")
    # Última execução por agente via scheduler
    sched_por_agente: dict = {}
    for entrada in log_sched:
        ag = entrada.get("agente", "")
        if not ag:
            continue
        ex = sched_por_agente.get(ag)
        if not ex or entrada.get("inicio", "") > ex.get("inicio", ""):
            sched_por_agente[ag] = entrada
    # Chamadas LLM hoje por agente
    llm_por_agente: dict = {}
    for entrada in log_llm:
        if not entrada.get("timestamp", "").startswith(hoje):
            continue
        ag = entrada.get("agente", "")
        if ag not in llm_por_agente:
            llm_por_agente[ag] = {"chamadas": 0, "custo_simulado": 0.0}
        llm_por_agente[ag]["chamadas"] += 1
        llm_por_agente[ag]["custo_simulado"] += entrada.get("custo_estimado_real", 0.0)
    return templates.TemplateResponse("agentes.html", {
        "request":          request,
        "page":             "agentes",
        "agentes":          _agentes(),
        "gov":              resumir_governanca_ativa(),
        "sched_por_agente": sched_por_agente,
        "llm_por_agente":   llm_por_agente,
    })


@app.get("/areas", response_class=HTMLResponse)
async def pagina_areas(request: Request):
    return templates.TemplateResponse("areas.html", {
        "request": request,
        "page":    "areas",
        "areas":   _areas(),
    })


@app.get("/feed", response_class=HTMLResponse)
async def pagina_feed(request: Request):
    return templates.TemplateResponse("feed.html", {
        "request": request,
        "page":    "feed",
        "feed":    _feed(),
    })


@app.get("/deliberacoes", response_class=HTMLResponse)
async def pagina_deliberacoes(request: Request):
    delibs = _ler("deliberacoes_conselho.json", [])
    pendentes = [d for d in delibs if d.get("status") in ("pendente", "em_analise")]
    painel    = _painel()
    return templates.TemplateResponse("deliberacoes.html", {
        "request":               request,
        "page":                  "deliberacoes",
        "delibs_resumo":         painel.get("deliberacoes", {"total":0,"pendentes":0,"resolvidas":0,"aplicadas":0}),
        "deliberacoes_pendentes": pendentes,
        "todas_deliberacoes":    delibs,
    })


@app.get("/comercial", response_class=HTMLResponse)
async def pagina_comercial(request: Request):
    areas    = _areas()
    metricas = _metricas()
    pipeline = _ler("pipeline_comercial.json", [])
    return templates.TemplateResponse("comercial.html", {
        "request":           request,
        "page":              "comercial",
        "com":               areas.get("comercial", {}),
        "metricas":          metricas,
        "pipeline_comercial": pipeline,
    })


@app.get("/entrega", response_class=HTMLResponse)
async def pagina_entrega(request: Request):
    areas    = _areas()
    metricas = _metricas()
    pipeline = _ler("pipeline_entrega.json", [])
    return templates.TemplateResponse("entrega.html", {
        "request":           request,
        "page":              "entrega",
        "ent":               areas.get("entrega", {}),
        "metricas":          metricas,
        "pipeline_entrega":  pipeline,
    })


@app.get("/financeiro", response_class=HTMLResponse)
async def pagina_financeiro(request: Request):
    areas    = _areas()
    caixa    = _ler("posicao_caixa.json", {})
    previsao = _ler("previsao_caixa.json", {})
    riscos   = _ler("fila_riscos_financeiros.json", [])
    # Dados de contratos para o painel financeiro
    try:
        from core.contratos_empresa import resumir_para_painel as _rct
        from modulos.financeiro.reconciliador_contratos_faturamento import (
            resumir_para_painel as _rrecon
        )
        ct_resumo    = _rct()
        recon_resumo = _rrecon()
    except Exception:
        ct_resumo    = {}
        recon_resumo = {}
    # Recebíveis de contratos (abertos + risco)
    try:
        rcv_contratos = [r for r in _ler("contas_a_receber.json", [])
                         if r.get("origem_recebivel") == "contrato_vetor"
                         and r.get("status") in ("aberta", "parcial", "vencida")]
    except Exception:
        rcv_contratos = []
    return templates.TemplateResponse("financeiro.html", {
        "request":       request,
        "page":          "financeiro",
        "fin":           areas.get("financeiro", {}),
        "caixa":         caixa,
        "previsao":      previsao,
        "riscos":        riscos,
        "ct_resumo":     ct_resumo,
        "recon_resumo":  recon_resumo,
        "rcv_contratos": rcv_contratos,
    })


# ─── Drill-down ───────────────────────────────────────────────────────────────

@app.get("/drill/{tipo}/{ref_id:path}", response_class=HTMLResponse)
async def pagina_drill(request: Request, tipo: str, ref_id: str):
    item      = None
    historico = []
    extras    = {}

    if tipo in ("oportunidade", "auto"):
        pipeline = _ler("pipeline_comercial.json", [])
        item = next((o for o in pipeline if o.get("id") == ref_id), None)
        if item:
            resultados = _ler("resultados_contato.json", [])
            historico  = [r for r in resultados if r.get("oportunidade_id") == ref_id]
            insumos    = _ler("insumos_entrega.json", [])
            ins_opp    = [i for i in insumos if i.get("oportunidade_id") == ref_id]
            if ins_opp:
                extras["insumos"] = ins_opp
            hist_fech = _ler("historico_fechamento_comercial.json", [])
            hist_opp  = [h for h in hist_fech if h.get("oportunidade_id") == ref_id]
            if hist_opp:
                extras["avaliacao_fechamento"] = hist_opp

    elif tipo == "entrega":
        pipeline  = _ler("pipeline_entrega.json", [])
        item = next((e for e in pipeline if e.get("id") == ref_id), None)
        if item:
            checklists = _ler("checklists_entrega.json", [])
            ck = next((c for c in checklists if c.get("entrega_id") == ref_id), None)
            if ck:
                extras["checklist"] = ck.get("itens", [])
            hist_ent = _ler("historico_entrega.json", [])
            historico = [h for h in hist_ent if h.get("entrega_id") == ref_id]

    elif tipo == "deliberacao":
        delibs = _ler("deliberacoes_conselho.json", [])
        item = next((d for d in delibs if d.get("id") == ref_id), None)
        if item and item.get("referencia_ids"):
            pipeline = _ler("pipeline_comercial.json", [])
            refs = [o for o in pipeline if o.get("id") in item["referencia_ids"]]
            if refs:
                extras["oportunidades_relacionadas"] = refs

    return templates.TemplateResponse("drill.html", {
        "request":  request,
        "page":     "",
        "tipo":     tipo,
        "ref_id":   ref_id,
        "item":     item,
        "historico": historico,
        "extras":   extras,
    })


# ─── API endpoints (polling) ─────────────────────────────────────────────────

@app.get("/api/overview")
async def api_overview():
    return JSONResponse({
        "painel":   _painel(),
        "metricas": _metricas(),
    })


@app.get("/api/feed")
async def api_feed():
    return JSONResponse(_feed())


@app.get("/api/agentes")
async def api_agentes():
    return JSONResponse(_agentes())


@app.get("/api/areas")
async def api_areas():
    return JSONResponse(_areas())


@app.get("/api/metricas")
async def api_metricas():
    return JSONResponse(_metricas())


@app.post("/api/refresh")
async def api_refresh():
    """Reconsolida os arquivos de observabilidade sem rodar o ciclo completo."""
    try:
        from core.observabilidade_empresa import executar_observabilidade
        resultado = executar_observabilidade()
        return JSONResponse({"status": "ok", "resultado": resultado})
    except Exception as exc:
        return JSONResponse({"status": "erro", "mensagem": str(exc)}, status_code=500)


@app.get("/api/status")
async def api_status():
    painel = _painel()
    return JSONResponse({
        "status":        painel.get("status_empresa", "desconhecido"),
        "atualizado_em": painel.get("atualizado_em", "—"),
        "ok":            True,
    })


# ─── Página de governança ─────────────────────────────────────────────────────

@app.get("/identidade", response_class=HTMLResponse)
async def pagina_identidade(request: Request, aba: str = "institucional"):
    from core.identidade_empresa import resumir_identidade_para_painel, obter_assinatura
    dados = resumir_identidade_para_painel()
    prontidao = _ler("prontidao_canais_reais.json", {})
    return templates.TemplateResponse("identidade.html", {
        "request":        request,
        "page":           "identidade",
        "aba_ativa":      aba,
        "identidade":     dados["identidade"],
        "guia":           dados["guia"],
        "assinaturas":    dados["assinaturas"],
        "canais":         dados["canais"],
        "historico":      dados["historico"],
        "status_completo": dados["status_completo"],
        "prontidao":      prontidao,
        "resultado":      None,
        "assinatura_previa": {
            "comercial":     obter_assinatura("comercial"),
            "financeiro":    obter_assinatura("financeiro"),
            "institucional": obter_assinatura("institucional"),
        },
    })


@app.post("/identidade", response_class=HTMLResponse)
async def salvar_identidade(
    request: Request,
    aba:     str = "institucional",
    secao:   str = Form(...),
    # Identidade
    nome_oficial:           str = Form(""),
    nome_exibicao:          str = Form(""),
    descricao_curta:        str = Form(""),
    descricao_media:        str = Form(""),
    proposta_valor_resumida: str = Form(""),
    publico_alvo:           str = Form(""),
    linhas_servico:         str = Form(""),
    cidade_base:            str = Form(""),
    pais_base:              str = Form("Brasil"),
    idioma_padrao:          str = Form("pt-BR"),
    # Guia
    tom_voz:                str = Form(""),
    nivel_formalidade:      str = Form("medio"),
    postura_comercial:      str = Form(""),
    postura_consultiva:     str = Form(""),
    postura_cobranca:       str = Form(""),
    estilo_abertura:        str = Form(""),
    estilo_fechamento:      str = Form(""),
    palavras_que_usa:       str = Form(""),
    palavras_que_evita:     str = Form(""),
    observacoes:            str = Form(""),
    # Assinaturas
    nome_remetente_padrao:  str = Form(""),
    cargo_remetente_padrao: str = Form(""),
    assinatura_comercial_texto:     str = Form(""),
    assinatura_financeiro_texto:    str = Form(""),
    assinatura_institucional_texto: str = Form(""),
    # Canais
    dominio_oficial_planejado:  str = Form(""),
    site_oficial:               str = Form(""),
    email_principal_planejado:  str = Form(""),
    email_comercial_planejado:  str = Form(""),
    email_financeiro_planejado: str = Form(""),
    instagram_oficial:          str = Form(""),
    whatsapp_oficial:           str = Form(""),
    status_configuracao_email:  str = Form("nao_definido"),
    status_configuracao_site:   str = Form("nao_definido"),
):
    from core.identidade_empresa import (
        carregar_identidade, carregar_guia_comunicacao,
        carregar_assinaturas, carregar_canais,
        salvar_identidade as _salvar_id,
        salvar_guia_comunicacao, salvar_assinaturas, salvar_canais,
        resumir_identidade_para_painel, obter_assinatura,
    )

    mensagem = ""
    if secao == "identidade":
        dados = carregar_identidade()
        dados.update({
            "nome_oficial": nome_oficial, "nome_exibicao": nome_exibicao,
            "descricao_curta": descricao_curta, "descricao_media": descricao_media,
            "proposta_valor_resumida": proposta_valor_resumida,
            "publico_alvo": publico_alvo,
            "linhas_servico": [s.strip() for s in linhas_servico.split(",") if s.strip()],
            "cidade_base": cidade_base, "pais_base": pais_base, "idioma_padrao": idioma_padrao,
        })
        _salvar_id(dados, origem="painel")
        mensagem = "Identidade institucional salva."

    elif secao == "guia":
        dados = carregar_guia_comunicacao()
        dados.update({
            "tom_voz": tom_voz, "nivel_formalidade": nivel_formalidade,
            "postura_comercial": postura_comercial, "postura_consultiva": postura_consultiva,
            "postura_cobranca": postura_cobranca, "estilo_abertura": estilo_abertura,
            "estilo_fechamento": estilo_fechamento, "observacoes": observacoes,
            "palavras_que_usa":   [s.strip() for s in palavras_que_usa.split(",") if s.strip()],
            "palavras_que_evita": [s.strip() for s in palavras_que_evita.split(",") if s.strip()],
        })
        salvar_guia_comunicacao(dados, origem="painel")
        mensagem = "Guia de comunicação salvo."

    elif secao == "assinaturas":
        dados = carregar_assinaturas()
        dados.update({
            "nome_remetente_padrao": nome_remetente_padrao,
            "cargo_remetente_padrao": cargo_remetente_padrao,
            "assinatura_comercial_texto": assinatura_comercial_texto,
            "assinatura_financeiro_texto": assinatura_financeiro_texto,
            "assinatura_institucional_texto": assinatura_institucional_texto,
        })
        salvar_assinaturas(dados, origem="painel")
        mensagem = "Assinaturas salvas."

    elif secao == "canais":
        dados = carregar_canais()
        dados.update({
            "dominio_oficial_planejado": dominio_oficial_planejado,
            "site_oficial": site_oficial,
            "email_principal_planejado": email_principal_planejado,
            "email_comercial_planejado": email_comercial_planejado,
            "email_financeiro_planejado": email_financeiro_planejado,
            "instagram_oficial": instagram_oficial,
            "whatsapp_oficial": whatsapp_oficial,
            "status_configuracao_email": status_configuracao_email,
            "status_configuracao_site": status_configuracao_site,
            "observacoes": observacoes,
        })
        salvar_canais(dados, origem="painel")
        mensagem = "Canais oficiais salvos."

    dados_painel = resumir_identidade_para_painel()
    prontidao = _ler("prontidao_canais_reais.json", {})
    return templates.TemplateResponse("identidade.html", {
        "request":        request,
        "page":           "identidade",
        "aba_ativa":      aba,
        "identidade":     dados_painel["identidade"],
        "guia":           dados_painel["guia"],
        "assinaturas":    dados_painel["assinaturas"],
        "canais":         dados_painel["canais"],
        "historico":      dados_painel["historico"],
        "status_completo": dados_painel["status_completo"],
        "prontidao":      prontidao,
        "resultado":      {"mensagem": mensagem} if mensagem else None,
        "assinatura_previa": {
            "comercial":     obter_assinatura("comercial"),
            "financeiro":    obter_assinatura("financeiro"),
            "institucional": obter_assinatura("institucional"),
        },
    })


@app.get("/propostas", response_class=HTMLResponse)
async def pagina_propostas(request: Request):
    from core.propostas_empresa import resumir_para_painel
    from core.expediente_propostas import resumir_para_painel as resumir_expediente
    try:
        from core.respostas_documentos import carregar_respostas as _cr
        _rdocs = _cr()
        respostas_por_proposta = {
            r["proposta_id"]: r for r in _rdocs
            if r.get("proposta_id") and r.get("status_aplicacao") == "aplicado"
        }
    except Exception:
        respostas_por_proposta = {}
    return templates.TemplateResponse("propostas.html", {
        "request":               request,
        "page":                  "propostas",
        "resumo":                resumir_para_painel(),
        "expediente":            resumir_expediente(),
        "respostas_por_proposta": respostas_por_proposta,
    })


@app.post("/propostas/{proposta_id}/aprovar", response_class=RedirectResponse)
async def aprovar_proposta_action(proposta_id: str):
    from core.propostas_empresa import aprovar_proposta
    aprovar_proposta(proposta_id, origem="conselho_painel")
    return RedirectResponse("/propostas", status_code=303)


@app.post("/propostas/{proposta_id}/rejeitar", response_class=RedirectResponse)
async def rejeitar_proposta_action(proposta_id: str):
    from core.propostas_empresa import rejeitar_proposta
    rejeitar_proposta(proposta_id, motivo="Rejeitada pelo conselho via painel", origem="conselho_painel")
    return RedirectResponse("/propostas", status_code=303)


@app.post("/propostas/{proposta_id}/arquivar", response_class=RedirectResponse)
async def arquivar_proposta_action(proposta_id: str):
    from core.propostas_empresa import arquivar_proposta
    arquivar_proposta(proposta_id, origem="conselho_painel")
    return RedirectResponse("/propostas", status_code=303)


@app.post("/propostas/{proposta_id}/aceite", response_class=RedirectResponse)
async def aceite_proposta_action(proposta_id: str):
    from core.propostas_empresa import registrar_aceite_proposta
    registrar_aceite_proposta(
        proposta_id,
        tipo_aceite="aceite_manual_conselho",
        descricao="Aceite registrado manualmente pelo conselho via painel",
        origem="conselho_painel",
    )
    return RedirectResponse("/propostas", status_code=303)


@app.post("/propostas/{proposta_id}/preparar-envio", response_class=RedirectResponse)
async def preparar_envio_action(proposta_id: str):
    from core.propostas_empresa import carregar_propostas
    from core.expediente_propostas import criar_envio_proposta
    propostas = carregar_propostas()
    prop = next((p for p in propostas if p["id"] == proposta_id), None)
    if prop:
        criar_envio_proposta(prop, origem="conselho_painel")
    return RedirectResponse("/propostas", status_code=303)


@app.post("/propostas/{proposta_id}/enfileirar-email", response_class=RedirectResponse)
async def enfileirar_email_action(proposta_id: str):
    from core.expediente_propostas import carregar_envios, enfileirar_proposta_no_email_assistido
    envios = carregar_envios()
    envio = next(
        (e for e in envios if e.get("proposta_id") == proposta_id
         and e.get("status") not in {"cancelado", "em_fila_assistida",
                                      "enviado_manual_registrado", "resposta_recebida"}),
        None,
    )
    if envio:
        enfileirar_proposta_no_email_assistido(envio, origem="conselho_painel")
    return RedirectResponse("/propostas", status_code=303)


@app.post("/propostas/{proposta_id}/marcar-enviada", response_class=RedirectResponse)
async def marcar_enviada_action(proposta_id: str):
    from core.expediente_propostas import marcar_envio_como_enviado
    marcar_envio_como_enviado(proposta_id, origem="conselho_painel")
    return RedirectResponse("/propostas", status_code=303)


@app.post("/propostas/{proposta_id}/resposta", response_class=RedirectResponse)
async def registrar_resposta_action(
    proposta_id: str,
    tipo_resposta: str = Form("sem_resposta"),
    descricao: str = Form(""),
    observacoes: str = Form(""),
):
    from core.expediente_propostas import registrar_resposta_proposta, aplicar_resposta_proposta
    resposta = registrar_resposta_proposta(
        proposta_id,
        tipo_resposta=tipo_resposta,
        descricao=descricao,
        observacoes=observacoes,
        origem="conselho_painel",
    )
    if resposta:
        aplicar_resposta_proposta(resposta)
    return RedirectResponse("/propostas", status_code=303)


@app.get("/contas", response_class=HTMLResponse)
async def pagina_contas(request: Request, status: str = "", busca: str = ""):
    from core.contas_empresa import carregar_contas, resumir_para_painel
    contas  = carregar_contas()
    resumo  = resumir_para_painel()
    # Filtros
    filtradas = contas
    if status:
        filtradas = [c for c in filtradas if c.get("status_relacionamento") == status]
    if busca:
        _b = busca.lower()
        filtradas = [c for c in filtradas
                     if _b in (c.get("nome_empresa") or "").lower()
                     or _b in (c.get("cidade") or "").lower()
                     or _b in (c.get("categoria") or "").lower()]
    filtradas = sorted(filtradas, key=lambda c: c.get("atualizado_em", ""), reverse=True)
    return templates.TemplateResponse("contas.html", {
        "request":      request,
        "page":         "contas",
        "contas":       filtradas,
        "resumo":       resumo,
        "filtro_status": status,
        "busca":        busca,
        "total_sem_filtro": len(contas),
    })


@app.get("/contas/{conta_id}", response_class=HTMLResponse)
async def pagina_conta_detalhe(request: Request, conta_id: str):
    from core.contas_empresa import obter_detalhe_conta
    from core.acompanhamento_contas import (
        obter_acompanhamentos_conta, obter_expansoes_conta, obter_saude_conta
    )
    detalhe = obter_detalhe_conta(conta_id)
    if not detalhe:
        return RedirectResponse("/contas")
    return templates.TemplateResponse("contas.html", {
        "request":  request,
        "page":     "contas",
        "detalhe":  detalhe,
        "conta_selecionada":   detalhe.get("conta"),
        "saude_conta":         obter_saude_conta(conta_id),
        "acompanhamentos":     obter_acompanhamentos_conta(conta_id),
        "expansoes":           obter_expansoes_conta(conta_id),
        "contas":   [],
        "resumo":   {},
        "filtro_status": "",
        "busca":    "",
        "total_sem_filtro": 0,
    })


@app.get("/acompanhamento", response_class=HTMLResponse)
async def pagina_acompanhamento(request: Request, filtro: str = "", busca: str = ""):
    from core.acompanhamento_contas import (
        carregar_acompanhamentos, carregar_saude_contas,
        carregar_expansoes, resumir_para_painel,
    )
    from core.contas_empresa import carregar_contas
    acomps   = carregar_acompanhamentos()
    saudes   = carregar_saude_contas()
    expansoes = carregar_expansoes()
    resumo   = resumir_para_painel()
    contas   = {c["id"]: c for c in carregar_contas()}

    # Enriquecer saúdes com nome da conta
    for s in saudes:
        s["_nome"] = contas.get(s.get("conta_id", ""), {}).get("nome_empresa", "—")

    # Filtros
    saudes_filtradas = saudes
    if filtro == "risco":
        saudes_filtradas = [s for s in saudes if s.get("status_saude") in ("atencao", "critica")]
    elif filtro == "expansao":
        saudes_filtradas = [s for s in saudes if s.get("potencial_expansao")]
    elif filtro in ("excelente", "boa", "atencao", "critica"):
        saudes_filtradas = [s for s in saudes if s.get("status_saude") == filtro]
    if busca:
        _b = busca.lower()
        saudes_filtradas = [s for s in saudes_filtradas if _b in (s.get("_nome") or "").lower()]

    saudes_filtradas = sorted(saudes_filtradas,
                               key=lambda s: s.get("score_saude", 0),
                               reverse=True)

    # Seções especiais
    em_risco  = [s for s in saudes if s.get("status_saude") in ("atencao", "critica")]
    pot_exp   = [s for s in saudes if s.get("potencial_expansao")]
    exp_sug   = [x for x in expansoes if x.get("status") == "sugerida"]
    exp_hand  = [x for x in expansoes if x.get("status") == "pronta_para_handoff"]
    acomps_ab = [a for a in acomps if a.get("status") in ("novo", "em_andamento")]

    # Enriquecer expansões com nome da conta
    for x in exp_sug + exp_hand:
        x["_nome"] = contas.get(x.get("conta_id", ""), {}).get("nome_empresa", "—")

    return templates.TemplateResponse("acompanhamento.html", {
        "request":         request,
        "page":            "acompanhamento",
        "saudes":          saudes_filtradas,
        "resumo":          resumo,
        "filtro":          filtro,
        "busca":           busca,
        "em_risco":        em_risco[:10],
        "pot_exp":         pot_exp[:10],
        "exp_sugeridas":   exp_sug[:20],
        "exp_handoff":     exp_hand[:10],
        "acomps_abertos":  acomps_ab[:20],
        "total_saudes":    len(saudes),
    })


@app.post("/acompanhamento/{acomp_id}/satisfacao", response_class=RedirectResponse)
async def registrar_satisfacao_action(
    acomp_id: str,
    satisfacao: str = Form(""),
    nps: str       = Form(""),
    resumo: str    = Form(""),
):
    from core.acompanhamento_contas import registrar_satisfacao
    nps_int = None
    try:
        nps_int = int(nps) if nps.strip() else None
    except ValueError:
        pass
    registrar_satisfacao(acomp_id, satisfacao, nps_int, resumo, "conselho")
    return RedirectResponse("/acompanhamento", status_code=303)


@app.post("/acompanhamento/expansao/{exp_id}/promover", response_class=RedirectResponse)
async def promover_expansao_action(exp_id: str):
    from core.acompanhamento_contas import carregar_expansoes, _salvar, _ARQ_EXPANSAO, _agora
    expansoes = carregar_expansoes()
    exp = next((x for x in expansoes if x["id"] == exp_id), None)
    if exp:
        exp["status"]       = "pronta_para_handoff"
        exp["atualizado_em"] = _agora()
        _salvar(_ARQ_EXPANSAO, expansoes)
    return RedirectResponse("/acompanhamento", status_code=303)


@app.get("/ofertas", response_class=HTMLResponse)
async def pagina_ofertas(request: Request):
    from core.ofertas_empresa import carregar_catalogo, carregar_regras, resumir_para_painel
    return templates.TemplateResponse("ofertas.html", {
        "request": request,
        "page":    "ofertas",
        "catalogo": carregar_catalogo(),
        "regras":   carregar_regras(),
        "resumo":   resumir_para_painel(),
    })


@app.get("/ativacao-email", response_class=HTMLResponse)
async def pagina_ativacao_email(request: Request):
    from core.provisionamento_canais import resumir_para_painel
    dados = resumir_para_painel()
    return templates.TemplateResponse("ativacao_email.html", {
        "request":          request,
        "page":             "ativacao_email",
        "provisionamento":  dados["provisionamento"],
        "checklist":        dados["checklist"],
        "historico_recente": dados["historico_recente"],
        "status_geral":     dados["status_geral"],
        "apto":             dados["apto"],
        "bloqueios":        dados["bloqueios"],
        "progresso":        dados["progresso"],
    })


@app.get("/email", response_class=HTMLResponse)
async def pagina_email(request: Request):
    from core.integrador_email import carregar_config_canal_email
    config_canal  = carregar_config_canal_email()
    estado        = _ler("estado_canal_email.json", {})
    historico     = _ler("historico_email.json", [])
    metricas      = _ler("metricas_email.json", {})
    respostas     = _ler("respostas_email.json", [])
    fila          = _ler("fila_envio_email.json", [])

    historico_recente = sorted(historico, key=lambda x: x.get("registrado_em",""), reverse=True)[:30]
    ultimos_emails    = sorted(fila, key=lambda x: x.get("criado_em",""), reverse=True)[:20]
    respostas_por_email = {r.get("email_origem_id",""): r for r in respostas}

    preparados   = [e for e in fila if e.get("status") == "preparado"]
    bloqueados   = [e for e in fila if e.get("status") == "bloqueado"]
    enviados_sim = [e for e in fila if e.get("status") == "enviado_simulado"]

    n_enviados     = len([e for e in fila if e.get("status") in ("preparado","enviado","enviado_simulado")])
    n_respondidos  = len(respostas)
    n_interessados = sum(1 for r in respostas if r.get("classificacao") in ("interessado","aceite","negocia_valor","pedido_info"))
    n_convertidos  = sum(1 for r in respostas if r.get("classificacao") == "aceite")

    docs_map: dict = {}
    try:
        docs_list = _ler("documentos_oficiais.json", [])
        docs_map = {d["id"]: d for d in docs_list}
    except Exception:
        pass

    return templates.TemplateResponse("email.html", {
        "request":            request,
        "page":               "email",
        "config_canal":       config_canal,
        "estado":             estado,
        "fila_email":         fila,
        "preparados":         preparados,
        "bloqueados":         bloqueados,
        "enviados_sim":       enviados_sim,
        "historico_recente":  historico_recente,
        "docs_map":           docs_map,
        "metricas":           metricas,
        "respostas":          respostas,
        "respostas_por_email": respostas_por_email,
        "ultimos_emails":     ultimos_emails,
        "funil": {
            "enviados":    n_enviados,
            "respondidos": n_respondidos,
            "interessados": n_interessados,
            "convertidos": n_convertidos,
        },
    })


@app.get("/email/simulacao", response_class=HTMLResponse)
async def pagina_email_simulacao(request: Request):
    metricas     = _ler("metricas_email.json", {})
    ultimo_ciclo = metricas.get("ultimo_ciclo") or {}
    return templates.TemplateResponse("email_simulacao.html", {
        "request":      request,
        "page":         "email",
        "metricas":     metricas,
        "ultimo_ciclo": ultimo_ciclo,
    })


@app.post("/api/email/simular", response_class=JSONResponse)
async def api_simular_email(n: int = Form(default=3)):
    try:
        from core.simulador_ciclo_email import simular_ciclo_completo
        resultado = simular_ciclo_completo(n_oportunidades=min(max(n, 1), 10))
        return JSONResponse(resultado)
    except Exception as exc:
        return JSONResponse({"status": "erro", "erro": str(exc)}, status_code=500)


@app.post("/api/verificar-smtp", response_class=JSONResponse)
async def api_verificar_smtp():
    try:
        import socket
        from core.provisionamento_canais import resumir_para_painel as _rpp
        prov = _rpp()["provisionamento"]
        host = prov.get("smtp_host_planejado", "")
        porta = int(prov.get("smtp_porta_planejada") or 587)
        if not host:
            return JSONResponse({"ok": False, "msg": "SMTP host não configurado em provisionamento_email_real.json"})
        s = socket.create_connection((host, porta), timeout=5)
        s.close()
        return JSONResponse({"ok": True, "msg": f"SMTP {host}:{porta} acessível"})
    except Exception as exc:
        return JSONResponse({"ok": False, "msg": str(exc)})


@app.post("/api/verificar-imap", response_class=JSONResponse)
async def api_verificar_imap():
    try:
        import socket
        from core.provisionamento_canais import resumir_para_painel as _rpp
        prov = _rpp()["provisionamento"]
        host  = prov.get("imap_host_planejado") or prov.get("smtp_host_planejado", "")
        porta = int(prov.get("imap_porta_planejada") or 993)
        if not host:
            return JSONResponse({"ok": False, "msg": "IMAP host não configurado"})
        s = socket.create_connection((host, porta), timeout=5)
        s.close()
        return JSONResponse({"ok": True, "msg": f"IMAP {host}:{porta} acessível"})
    except Exception as exc:
        return JSONResponse({"ok": False, "msg": str(exc)})



@app.get("/canais", response_class=HTMLResponse)
async def pagina_canais(request: Request):
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    from pathlib import Path as _Path

    _dd = _Path(__file__).parent.parent / "dados"

    def _ler_c(nome, padrao):
        try:
            return _json.loads((_dd / nome).read_text(encoding="utf-8"))
        except Exception:
            return padrao

    from core.canais import CanalEmail as _CE, CanalWhatsApp as _CW, CanalTelefone as _CT
    estado = _ler_c("estado_canais.json", {})

    hoje = _dt.now()
    dias = [(hoje - _td(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    def _hist(items, campo="registrado_em"):
        por_dia: dict = {}
        for it in items:
            d = (it.get(campo) or "")[:10]
            if d:
                por_dia[d] = por_dia.get(d, 0) + 1
        return [por_dia.get(d, 0) for d in dias]

    hist_email = _ler_c("historico_email.json", [])
    fila_wapp  = _ler_c("fila_envio_whatsapp.json", [])
    fila_tel   = _ler_c("fila_chamadas_telefone.json", [])

    def _safe_status(cls):
        try:
            return cls().status()
        except Exception:
            return {"modo": "dry-run", "configurado": False}

    canais = [
        {
            "id":             "email",
            "nome":           "Email",
            "icone":          "✉",
            "status":         _safe_status(_CE),
            "pre_requisitos": estado.get("email", {}).get("pre_requisitos", []),
            "hist_7d":        _hist(hist_email, "registrado_em"),
        },
        {
            "id":             "whatsapp",
            "nome":           "WhatsApp",
            "icone":          "◎",
            "status":         _safe_status(_CW),
            "pre_requisitos": estado.get("whatsapp", {}).get("pre_requisitos", []),
            "hist_7d":        _hist(fila_wapp, "registrado_em"),
        },
        {
            "id":             "telefone",
            "nome":           "Telefone",
            "icone":          "☎",
            "status":         _safe_status(_CT),
            "pre_requisitos": estado.get("telefone", {}).get("pre_requisitos", []),
            "hist_7d":        _hist(fila_tel, "registrado_em"),
        },
    ]

    ativos  = sum(1 for c in canais if c["status"].get("modo", "dry-run") != "dry-run")
    em_fila = sum(c["status"].get("fila_pendente", 0) for c in canais)
    dry_run = sum(1 for c in canais if c["status"].get("modo", "dry-run") == "dry-run")

    return templates.TemplateResponse("canais.html", {
        "request":    request,
        "page":       "canais",
        "canais":     canais,
        "ativos":     ativos,
        "em_fila":    em_fila,
        "dry_run":    dry_run,
        "dias_labels": dias,
    })


@app.get("/multi-cidade", response_class=HTMLResponse)
async def pagina_multi_cidade(request: Request):
    import json as _json
    from collections import defaultdict as _dd
    from pathlib import Path as _Path

    _dados = _Path(__file__).parent.parent / "dados"

    def _ler_mc(nome, padrao):
        try:
            return _json.loads((_dados / nome).read_text(encoding="utf-8"))
        except Exception:
            return padrao

    pipeline  = _ler_mc("pipeline_comercial.json", [])
    scheduler = _ler_mc("scheduler_estado.json", {})

    cidades: dict = _dd(lambda: {"leads": 0, "oportunidades": 0, "ganhos": 0, "nichos": set()})
    nicho_map: dict = _dd(lambda: {"cidades": set(), "total": 0})
    empresas_multi: dict = _dd(set)

    for item in pipeline:
        cidade = (item.get("cidade") or "").strip()
        if not cidade:
            continue
        status = item.get("status", "")
        nicho  = (item.get("categoria") or item.get("segmento") or item.get("tipo_negocio") or "").strip()
        nome   = (item.get("empresa") or item.get("nome") or "").strip()

        cidades[cidade]["leads"] += 1
        if status not in ("descartada", "perdida"):
            cidades[cidade]["oportunidades"] += 1
        if status in ("ganho", "fechada", "contrato_assinado"):
            cidades[cidade]["ganhos"] += 1
        if nicho:
            cidades[cidade]["nichos"].add(nicho)
            nicho_map[nicho]["cidades"].add(cidade)
            nicho_map[nicho]["total"] += 1
        if nome:
            empresas_multi[nome].add(cidade)

    cidades_lista = sorted(
        [
            {
                "cidade":        c,
                "leads":         v["leads"],
                "oportunidades": v["oportunidades"],
                "ganhos":        v["ganhos"],
                "nichos":        sorted(v["nichos"])[:5],
            }
            for c, v in cidades.items()
        ],
        key=lambda x: x["oportunidades"],
        reverse=True,
    )

    nichos_lista = sorted(
        [
            {"nicho": n, "cidades": sorted(v["cidades"]), "total": v["total"]}
            for n, v in nicho_map.items()
        ],
        key=lambda x: (len(x["cidades"]), x["total"]),
        reverse=True,
    )[:10]

    redes = [
        {"nome": nome, "cidades": sorted(cs)}
        for nome, cs in empresas_multi.items()
        if len(cs) > 1
    ][:10]

    return templates.TemplateResponse("multi_cidade.html", {
        "request":           request,
        "page":              "multi_cidade",
        "cidades":           cidades_lista,
        "nichos_cross":      nichos_lista,
        "redes":             redes,
        "total_cidades":     len(cidades_lista),
        "total_leads":       sum(c["leads"] for c in cidades_lista),
        "total_oportunidades": sum(c["oportunidades"] for c in cidades_lista),
        "ultima_execucao":   scheduler.get("ultima_verificacao", "—"),
        "proxima_execucao":  scheduler.get("proximo_agendado"),
    })


@app.get("/telefone", response_class=HTMLResponse)
async def pagina_telefone(request: Request):
    from conectores.telefone import CanalTelefone as _CanalTelefone
    import json, os
    _dados_dir = os.path.join(os.path.dirname(__file__), "..", "dados")
    def _ler_tel(nome, padrao):
        try:
            with open(os.path.join(_dados_dir, nome), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return padrao
    canal = _CanalTelefone()
    config_canal  = _ler_tel("config_canal_telefone.json", {})
    fila          = _ler_tel("fila_chamadas_telefone.json", [])
    pendentes     = [c for c in fila if c.get("status") in ("pendente", "agendado")]
    concluidas    = sorted(
        [c for c in fila if c.get("status") == "concluida"],
        key=lambda x: x.get("atualizado_em", ""), reverse=True
    )[:20]
    return templates.TemplateResponse("telefone.html", {
        "request":           request,
        "page":              "telefone",
        "status_canal":      canal.status(),
        "config_canal":      config_canal,
        "pendentes":         pendentes,
        "concluidas_recentes": concluidas,
        "flash":             None,
    })


@app.post("/telefone/{chamada_id}/resultado", response_class=RedirectResponse)
async def registrar_resultado_chamada(
    chamada_id: str,
    resultado:   str = Form(...),
    observacoes: str = Form(""),
):
    from conectores.telefone import CanalTelefone as _CanalTelefone
    _CanalTelefone().registrar_resultado_chamada(chamada_id, resultado, observacoes or None)
    return RedirectResponse("/telefone", status_code=303)


@app.get("/entrada-manual", response_class=HTMLResponse)
async def pagina_entrada_manual(request: Request):
    from modulos.entrada_manual.processador_entrada_manual import (
        carregar_todas_entradas_manuais, carregar_avaliacao_por_entrada,
    )
    entradas   = carregar_todas_entradas_manuais()
    avals      = {e["id"]: carregar_avaliacao_por_entrada(e["id"]) for e in entradas if carregar_avaliacao_por_entrada(e["id"])}
    return templates.TemplateResponse("entrada_manual.html", {
        "request":              request,
        "page":                 "entrada_manual",
        "entradas":             entradas,
        "avaliacoes_por_entrada": avals,
        "resultado":            None,
        "form_data":            None,
    })


@app.post("/entrada-manual", response_class=HTMLResponse)
async def processar_entrada_manual(
    request: Request,
    nome:             str = Form(...),
    categoria:        str = Form(""),
    cidade:           str = Form(""),
    estado:           str = Form(""),
    telefone:         str = Form(""),
    email:            str = Form(""),
    site:             str = Form(""),
    instagram:        str = Form(""),
    whatsapp:         str = Form(""),
    facebook:         str = Form(""),
    modo:             str = Form("avaliacao_manual"),
    observacoes:      str = Form(""),
    valor_venda:      str = Form(""),
    servico_vendido:  str = Form(""),
    forcar_insercao:  str = Form(""),
):
    from modulos.entrada_manual.processador_entrada_manual import (
        processar_entrada_manual as _processar,
        carregar_todas_entradas_manuais,
        carregar_avaliacao_por_entrada,
    )
    dados = {
        "nome": nome, "categoria": categoria, "cidade": cidade,
        "estado": estado, "telefone": telefone, "email": email,
        "site": site, "instagram": instagram, "whatsapp": whatsapp,
        "facebook": facebook, "modo": modo, "observacoes": observacoes,
        "valor_venda": valor_venda, "servico_vendido": servico_vendido,
        "forcar_insercao": forcar_insercao == "1",
    }
    resultado = _processar(dados)
    _atualizar_observabilidade()

    entradas = carregar_todas_entradas_manuais()
    avals    = {e["id"]: carregar_avaliacao_por_entrada(e["id"]) for e in entradas if carregar_avaliacao_por_entrada(e["id"])}
    return templates.TemplateResponse("entrada_manual.html", {
        "request":              request,
        "page":                 "entrada_manual",
        "entradas":             entradas,
        "avaliacoes_por_entrada": avals,
        "resultado":            resultado,
        "form_data":            dados,
    })


@app.get("/saude", response_class=HTMLResponse)
async def pagina_saude(request: Request):
    from core.confiabilidade_empresa import resumir_confiabilidade_para_painel
    dados = resumir_confiabilidade_para_painel()
    return templates.TemplateResponse("saude.html", {
        "request":    request,
        "page":       "saude",
        "saude":      dados["saude"],
        "lock":       {"ativo": dados["lock_ativo"], "ciclo_id": dados["lock_ciclo_id"],
                       "etapa": dados["lock_etapa"], "iniciado_em": dados["lock_iniciado_em"]},
        "recovery":   dados["recovery"],
        "checkpoints": dados["checkpoints_ultimo_ciclo"],
        "incidentes_abertos":  dados["incidentes_abertos"],
        "todos_incidentes":    dados["todos_incidentes"],
    })


@app.get("/governanca", response_class=HTMLResponse)
async def pagina_governanca(request: Request):
    from core.governanca_conselho import resumir_governanca_ativa
    from core.politicas_empresa import resumir_politicas_ativas
    from core.politicas_ti import carregar_politicas_ti
    gov     = resumir_governanca_ativa()
    politicas_resumo = resumir_politicas_ativas()
    politicas_ti = carregar_politicas_ti()
    historico = _ler("historico_comandos_conselho.json", [])
    historico_recente = sorted(historico, key=lambda x: x.get("registrado_em",""), reverse=True)[:20]
    return templates.TemplateResponse("governanca.html", {
        "request":    request,
        "page":       "governanca",
        "gov":        gov,
        "politicas":  politicas_resumo,
        "politicas_ti": politicas_ti,
        "historico":  historico_recente,
        "agentes_conhecidos": [
            "agente_financeiro", "agente_prospeccao", "agente_marketing",
            "agente_comercial", "agente_secretario", "agente_executor_contato",
            "integrador_email", "integrador_canais", "agente_operacao_entrega",
            "gerador_insumos_desde_contato", "avaliador_fechamento_comercial",
        ],
        "areas_conhecidas": ["financeiro", "prospeccao", "marketing", "comercial", "entrega", "operacao"],
        "modos_validos":    ["normal", "conservador", "foco_caixa", "foco_crescimento", "manutencao"],
        "linhas_servico":   ["marketing_presenca_digital", "automacao_atendimento", "outras"],
        "riscos_ti":        ["baixo", "medio"],
    })


# ─── Ações de deliberação (form POST → redirect) ──────────────────────────────

@app.post("/acao/deliberar/{delib_id}")
async def acao_deliberar(
    delib_id:     str,
    acao:         str  = Form(...),
    justificativa: str = Form(""),
):
    from core.governanca_conselho import registrar_comando_conselho
    valor_map = {"aprovar": "aprovado", "rejeitar": "rejeitado", "adiar": "adiado"}
    valor = valor_map.get(acao, acao)
    registrar_comando_conselho(
        tipo_comando="deliberacao",
        alvo_tipo="deliberacao",
        alvo_id=delib_id,
        valor=valor,
        justificativa=justificativa or f"Ação '{acao}' via painel do conselho",
    )
    _atualizar_politicas()
    _atualizar_observabilidade()
    return RedirectResponse("/deliberacoes", status_code=303)


# ─── Ações de governança (form POST → redirect) ───────────────────────────────

@app.post("/acao/governanca")
async def acao_governanca(
    tipo_comando:  str = Form(...),
    alvo_id:       str = Form(""),
    valor:         str = Form(""),
    justificativa: str = Form(""),
):
    from core.governanca_conselho import registrar_comando_conselho, registrar_diretriz_conselho
    if tipo_comando == "registrar_diretriz":
        # alvo_id=categoria, valor=titulo, justificativa=descricao
        categoria  = alvo_id or "geral"
        titulo     = valor or "Diretriz do conselho"
        prioridade = "media"
        registrar_diretriz_conselho(categoria, titulo, justificativa or titulo)
    else:
        registrar_comando_conselho(
            tipo_comando=tipo_comando,
            alvo_tipo=_inferir_alvo_tipo(tipo_comando),
            alvo_id=alvo_id,
            valor=valor,
            justificativa=justificativa or f"Comando '{tipo_comando}' via painel",
        )
    _atualizar_politicas()
    _atualizar_observabilidade()
    return RedirectResponse("/governanca", status_code=303)


@app.post("/acao/desativar_diretriz/{dir_id}")
async def acao_desativar_diretriz(dir_id: str):
    from core.governanca_conselho import desativar_diretriz_conselho
    desativar_diretriz_conselho(dir_id)
    _atualizar_politicas()
    _atualizar_observabilidade()
    return RedirectResponse("/governanca", status_code=303)


# ─── API de governança (JSON) ─────────────────────────────────────────────────

@app.post("/api/deliberacoes/{delib_id}/aprovar")
async def api_aprovar(delib_id: str, request: Request):
    body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
    return _api_deliberar(delib_id, "aprovado", body.get("justificativa",""))


@app.post("/api/deliberacoes/{delib_id}/rejeitar")
async def api_rejeitar(delib_id: str, request: Request):
    body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
    return _api_deliberar(delib_id, "rejeitado", body.get("justificativa",""))


@app.post("/api/deliberacoes/{delib_id}/adiar")
async def api_adiar(delib_id: str, request: Request):
    body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
    return _api_deliberar(delib_id, "adiado", body.get("justificativa",""))


def _api_deliberar(delib_id: str, valor: str, justificativa: str):
    from core.governanca_conselho import registrar_comando_conselho
    cmd = registrar_comando_conselho("deliberacao", "deliberacao", delib_id, valor, justificativa)
    _atualizar_observabilidade()
    return JSONResponse({"status": cmd["status"], "comando_id": cmd["id"], "mensagem": cmd["observacoes"]})


@app.post("/api/governanca/comando")
async def api_governanca_comando(request: Request):
    try:
        body = await request.json()
        from core.governanca_conselho import registrar_comando_conselho
        cmd = registrar_comando_conselho(
            tipo_comando=body["tipo_comando"],
            alvo_tipo=body.get("alvo_tipo", _inferir_alvo_tipo(body["tipo_comando"])),
            alvo_id=body.get("alvo_id",""),
            valor=body.get("valor",""),
            justificativa=body.get("justificativa",""),
            origem=body.get("origem","api"),
        )
        _atualizar_observabilidade()
        return JSONResponse({"status": cmd["status"], "comando_id": cmd["id"]})
    except Exception as exc:
        return JSONResponse({"status": "erro", "mensagem": str(exc)}, status_code=400)


@app.get("/contratos", response_class=HTMLResponse)
async def pagina_contratos(request: Request,
                            filtro: str = "",
                            busca: str = ""):
    from core.contratos_empresa import (
        carregar_contratos, carregar_planos, resumir_para_painel as _rct
    )
    contratos = carregar_contratos()
    planos    = carregar_planos()
    resumo    = _rct()
    try:
        from modulos.financeiro.reconciliador_contratos_faturamento import (
            resumir_para_painel as _rrecon
        )
        recon_resumo = _rrecon()
    except Exception:
        recon_resumo = {}

    # Índice plano por contrato
    plano_por_ct = {p["contrato_id"]: p for p in planos}

    # Recebíveis por contrato
    recebiveis_raw = _ler("contas_a_receber.json", [])
    rcv_por_ct: dict = {}
    for r in recebiveis_raw:
        cid = r.get("contrato_id", "")
        if cid:
            rcv_por_ct.setdefault(cid, []).append(r)

    # Filtros
    if filtro:
        contratos = [c for c in contratos if c.get("status") == filtro]
    if busca:
        busca_l = busca.lower()
        contratos = [c for c in contratos
                     if busca_l in c.get("contraparte", "").lower()
                     or busca_l in c.get("oferta_nome", "").lower()]

    # Enriquecer para exibição
    for c in contratos:
        c["_plano"]      = plano_por_ct.get(c["id"])
        c["_recebiveis"] = rcv_por_ct.get(c["id"], [])

    contratos_sorted = sorted(contratos, key=lambda c: c.get("gerado_em", ""), reverse=True)

    return templates.TemplateResponse("contratos.html", {
        "request":      request,
        "page":         "contratos",
        "contratos":    contratos_sorted,
        "resumo":       resumo,
        "recon_resumo": recon_resumo,
        "filtro":       filtro,
        "busca":        busca,
        "total":        len(contratos_sorted),
    })


@app.get("/contratos/{contrato_id}", response_class=HTMLResponse)
async def pagina_contrato_detalhe(request: Request, contrato_id: str):
    from core.contratos_empresa import obter_detalhe_contrato
    detalhe = obter_detalhe_contrato(contrato_id)
    if not detalhe:
        return HTMLResponse("<h2>Contrato não encontrado</h2>", status_code=404)
    return templates.TemplateResponse("contratos.html", {
        "request":   request,
        "page":      "contratos",
        "modo":      "detalhe",
        "detalhe":   detalhe,
        "contrato":  detalhe["contrato"],
        "plano":     detalhe["plano"],
        "recebiveis": detalhe["recebiveis"],
        "historico": detalhe["historico"],
    })


@app.get("/documentos", response_class=HTMLResponse)
async def pagina_documentos(request: Request, tipo: str = "", status: str = ""):
    from core.documentos_empresa import resumir_para_painel as _rdoc
    docs_resumo = _rdoc()
    documentos  = _ler("documentos_oficiais.json", [])
    # Filtros
    if tipo:
        documentos = [d for d in documentos if d.get("tipo_documento") == tipo]
    if status:
        documentos = [d for d in documentos if d.get("status") == status]
    else:
        documentos = [d for d in documentos if d.get("status") != "arquivado"]
    documentos = sorted(documentos, key=lambda d: d.get("gerado_em", ""), reverse=True)
    # Envios de documentos para mostrar status de envio por linha
    envios_docs = _ler("envios_documentos.json", [])
    envio_por_doc = {}
    for ev in envios_docs:
        doc_id = ev.get("documento_id", "")
        if doc_id and ev.get("status") not in {"cancelado"}:
            envio_por_doc[doc_id] = ev
    # Respostas de documentos por envio_doc_id
    try:
        from core.respostas_documentos import carregar_respostas as _cr, resumir_para_painel as _rrespdoc
        _rdocs = _cr()
        respostas_por_envio = {r["envio_documento_id"]: r for r in _rdocs}
        respostas_resumo    = _rrespdoc()
    except Exception:
        respostas_por_envio = {}
        respostas_resumo    = {}
    return templates.TemplateResponse("documentos.html", {
        "request":            request,
        "page":               "documentos",
        "documentos":         documentos,
        "docs_resumo":        docs_resumo,
        "filtro_tipo":        tipo,
        "filtro_status":      status,
        "envio_por_doc":      envio_por_doc,
        "respostas_por_envio": respostas_por_envio,
        "respostas_resumo":   respostas_resumo,
    })


@app.post("/documentos/{doc_id}/preparar-envio", response_class=RedirectResponse)
async def preparar_envio_doc_action(doc_id: str):
    from core.expediente_documentos_email import preparar_envio_documento
    preparar_envio_documento(doc_id, origem="conselho_painel")
    return RedirectResponse("/documentos", status_code=303)


@app.post("/documentos/{doc_id}/enfileirar", response_class=RedirectResponse)
async def enfileirar_doc_action(doc_id: str):
    from core.expediente_documentos_email import (
        carregar_envios_documentos,
        enfileirar_documento_no_email_assistido,
    )
    envios = carregar_envios_documentos()
    envio  = next(
        (e for e in envios
         if e.get("documento_id") == doc_id
         and e.get("status") not in {"cancelado", "em_fila_assistida", "marcado_como_enviado"}),
        None,
    )
    if envio:
        enfileirar_documento_no_email_assistido(envio, origem="conselho_painel")
    return RedirectResponse("/documentos", status_code=303)


@app.post("/documentos/{doc_id}/marcar-enviado", response_class=RedirectResponse)
async def marcar_enviado_doc_action(doc_id: str):
    from core.expediente_documentos_email import (
        carregar_envios_documentos,
        marcar_documento_como_enviado,
    )
    envios = carregar_envios_documentos()
    envio  = next(
        (e for e in envios
         if e.get("documento_id") == doc_id
         and e.get("status") not in {"cancelado", "marcado_como_enviado"}),
        None,
    )
    if envio:
        marcar_documento_como_enviado(envio["id"], origem="conselho_painel")
    return RedirectResponse("/documentos", status_code=303)


@app.post("/documentos/{doc_id}/resposta", response_class=RedirectResponse)
async def registrar_resposta_doc_action(
    doc_id: str,
    tipo_resposta: str = Form(...),
    descricao: str = Form(""),
):
    from core.expediente_documentos_email import carregar_envios_documentos
    from core.respostas_documentos import (
        registrar_resposta_documento,
        aplicar_resposta_documento,
    )
    envios = carregar_envios_documentos()
    envio = next(
        (e for e in envios if e.get("documento_id") == doc_id
         and e.get("status") not in {"cancelado"}),
        None,
    )
    if envio:
        resposta = registrar_resposta_documento(
            envio["id"], tipo_resposta, descricao, origem="conselho_painel"
        )
        if resposta and resposta.get("status_aplicacao") == "pendente":
            aplicar_resposta_documento(resposta)
    return RedirectResponse("/documentos", status_code=303)


@app.get("/documentos/preview/{doc_id}", response_class=HTMLResponse)
async def preview_documento(request: Request, doc_id: str):
    from core.documentos_empresa import registrar_historico_documento
    documentos = _ler("documentos_oficiais.json", [])
    doc = next((d for d in documentos if d.get("id") == doc_id), None)
    if not doc:
        return HTMLResponse("<h3>Documento não encontrado.</h3>", status_code=404)
    caminho = Path(doc.get("caminho_arquivo", ""))
    if not caminho.is_absolute():
        caminho = Path(__file__).parent.parent / caminho
    if not caminho.exists():
        return HTMLResponse("<h3>Arquivo não encontrado.</h3>", status_code=404)
    registrar_historico_documento(doc_id, "preview_consultado",
                                  "Preview consultado no painel", "conselho_app")
    return HTMLResponse(content=caminho.read_text(encoding="utf-8"))


@app.get("/llm", response_class=HTMLResponse)
async def pagina_llm(request: Request):
    try:
        from core.llm_log import resumo_custos_dia, resumo_custos_periodo, carregar_log
        resumo_hoje   = resumo_custos_dia()
        resumo_semana = resumo_custos_periodo(7)
        log_completo  = carregar_log()
        top5 = sorted(log_completo,
                      key=lambda e: e.get("custo_estimado_real", 0),
                      reverse=True)[:5]
    except Exception:
        resumo_hoje = resumo_semana = {}
        log_completo = top5 = []
    return templates.TemplateResponse("llm.html", {
        "request":       request,
        "page":          "llm",
        "resumo_hoje":   resumo_hoje,
        "resumo_semana": resumo_semana,
        "top5":          top5,
        "modo_llm":      getattr(config, "LLM_MODO", "dry-run"),
        "total_log":     len(log_completo),
    })


@app.get("/scheduler", response_class=HTMLResponse)
async def pagina_scheduler(request: Request):
    from datetime import datetime
    estado    = _ler("scheduler_estado.json", {})
    log_sched = _ler("scheduler_log.json", [])
    gov       = _ler("estado_governanca_conselho.json", {})
    _DIA_MAP  = {"seg":0,"ter":1,"qua":2,"qui":3,"sex":4,"sab":5,"dom":6}
    agenda_cfg = getattr(config, "AGENDA_AGENTES", {})
    dia_semana = datetime.now().weekday()
    hoje_str   = datetime.now().strftime("%Y-%m-%d")
    agenda_hoje: list = []
    for agente, cfg in agenda_cfg.items():
        dias_idx = [_DIA_MAP[d] for d in cfg.get("dias", []) if d in _DIA_MAP]
        if dia_semana in dias_idx:
            for horario in cfg.get("horarios", []):
                agenda_hoje.append({"horario": horario, "agente": agente})
    agenda_hoje.sort(key=lambda x: x["horario"])
    exec_hoje   = estado.get("execucoes_hoje", {})
    ciclos_hoje = sum(len(v) for v in exec_hoje.values()) if isinstance(exec_hoje, dict) else 0
    erros_hoje  = sum(1 for e in log_sched
                      if e.get("status") == "erro"
                      and e.get("inicio", "")[:10] == hoje_str)
    return templates.TemplateResponse("scheduler.html", {
        "request":          request,
        "page":             "scheduler",
        "estado":           estado,
        "log_recente":      list(reversed(log_sched[-20:])),
        "agenda_hoje":      agenda_hoje,
        "agentes_pausados": gov.get("agentes_pausados", []),
        "modo_empresa":     gov.get("modo_empresa", "normal"),
        "scheduler_ativo":  getattr(config, "SCHEDULER_ATIVO", True),
        "ciclos_hoje":      ciclos_hoje,
        "erros_hoje":       erros_hoje,
    })


@app.get("/documentos/download/{doc_id}")
async def download_documento(doc_id: str):
    from fastapi.responses import FileResponse
    documentos = _ler("documentos_oficiais.json", [])
    doc = next((d for d in documentos if d.get("id") == doc_id), None)
    if not doc:
        from fastapi.responses import JSONResponse as JR
        return JR({"erro": "não encontrado"}, status_code=404)
    caminho = Path(doc.get("caminho_arquivo", ""))
    if not caminho.is_absolute():
        caminho = Path(__file__).parent.parent / caminho
    if not caminho.exists():
        from fastapi.responses import JSONResponse as JR
        return JR({"erro": "arquivo não encontrado"}, status_code=404)
    return FileResponse(
        path=str(caminho),
        filename=doc.get("nome_arquivo", "documento.html"),
        media_type="text/html",
    )


@app.get("/customer-success", response_class=HTMLResponse)
async def pagina_customer_success(request: Request):
    from core.contas_empresa import carregar_contas
    from core.playbooks_cs import carregar_playbooks

    contas_map = {c["id"]: c for c in carregar_contas()}

    # Relatório CS mais recente
    relatorio = _ler("relatorio_customer_success.json", {})

    # Ações CS — pendentes e executadas recentemente
    acoes_cs = _ler("acoes_customer_success.json", [])
    acoes_pendentes = [a for a in acoes_cs if a.get("status_acao") == "pendente"]
    acoes_executadas = sorted(
        [a for a in acoes_cs if a.get("status_acao") == "executada"],
        key=lambda a: a.get("timestamp", ""), reverse=True,
    )[:10]

    # Saúdes das contas
    saudes_raw = _ler("saude_contas_clientes.json", [])
    dist_saude = {"saudavel": 0, "atencao": 0, "risco": 0, "critico": 0}
    for s in saudes_raw:
        st = s.get("status_saude", "")
        if st in ("excelente", "boa"):
            dist_saude["saudavel"] += 1
        elif st == "atencao":
            dist_saude["atencao"] += 1
        elif st == "risco":
            dist_saude["risco"] += 1
        elif st in ("critica", "critico"):
            dist_saude["critico"] += 1

    # Playbooks ativos: carregar definição e histórico de execuções
    playbooks_def = carregar_playbooks()
    historico_pb  = _ler("historico_playbooks_cs.json", [])
    # Contas únicas com playbook ativo no histórico recente (últimos 30 dias)
    from datetime import datetime as _dt, timedelta as _td
    _cutoff = (_dt.now() - _td(days=30)).isoformat(timespec="seconds")
    pb_ativos_contas: dict = {}
    for exec_pb in historico_pb:
        if exec_pb.get("timestamp", "") >= _cutoff and exec_pb.get("status") == "ativo":
            cid = exec_pb.get("conta_id", "")
            pb_id = exec_pb.get("playbook_id", "")
            if cid and pb_id:
                pb_ativos_contas.setdefault(pb_id, set()).add(cid)
    playbooks_ativos = []
    for pb in playbooks_def:
        pb_id = pb.get("id", "")
        contas_ativas = pb_ativos_contas.get(pb_id, set())
        if contas_ativas:
            playbooks_ativos.append({**pb, "_n_contas": len(contas_ativas)})

    return templates.TemplateResponse("customer_success.html", {
        "request":         request,
        "page":            "customer_success",
        "relatorio":       relatorio,
        "acoes_pendentes": acoes_pendentes,
        "acoes_executadas": acoes_executadas,
        "dist_saude":      dist_saude,
        "playbooks_ativos": playbooks_ativos,
        "n_playbooks_def": len(playbooks_def),
        "contas_map":      contas_map,
    })


@app.get("/expansao", response_class=HTMLResponse)
async def pagina_expansao(request: Request):
    from core.motor_expansao import resumir_para_painel
    from core.contas_empresa import carregar_contas

    resumo     = resumir_para_painel()
    contas_map = {c["id"]: c for c in carregar_contas()}
    expansoes  = _ler("oportunidades_expansao.json", [])

    # Enriquecer com nome da conta
    for x in expansoes:
        x["_nome"] = contas_map.get(x.get("conta_id", ""), {}).get("nome_empresa", "—")

    # Por status
    ativas    = [x for x in expansoes if x.get("status") in ("detectada", "qualificada", "preparada")]
    convertidas = [x for x in expansoes if x.get("status") in ("convertida", "convertida_em_oportunidade")]
    descartadas = [x for x in expansoes if x.get("status") in ("descartada", "arquivada")]

    # Top 5 por score
    top5 = sorted(ativas, key=lambda x: x.get("score_expansao", 0), reverse=True)[:5]

    # Valor estimado (pitches com valor)
    pitches = _ler("propostas_expansao.json", [])
    valor_estimado = sum(
        float(p.get("valor_estimado", 0) or 0) for p in pitches
        if p.get("status") not in ("descartado",)
    )

    return templates.TemplateResponse("expansao.html", {
        "request":        request,
        "page":           "expansao",
        "resumo":         resumo,
        "expansoes_ativas": ativas,
        "top5":           top5,
        "convertidas":    convertidas[:10],
        "descartadas":    descartadas[:5],
        "valor_estimado": valor_estimado,
        "pitches":        pitches[:10],
        "contas_map":     contas_map,
    })


@app.get("/nps", response_class=HTMLResponse)
async def pagina_nps(request: Request):
    from core.nps_feedback import calcular_nps_empresa
    from core.contas_empresa import carregar_contas

    metricas = calcular_nps_empresa()
    contas   = {c["id"]: c for c in carregar_contas()}

    respostas = _ler("nps_respostas.json", [])
    pendentes = _ler("nps_pendentes.json", [])

    detratores  = sorted(
        [r for r in respostas if r.get("score", 10) <= 6],
        key=lambda r: r.get("respondido_em", ""), reverse=True,
    )
    promotores  = sorted(
        [r for r in respostas if r.get("score", 0) >= 9],
        key=lambda r: r.get("respondido_em", ""), reverse=True,
    )
    pendentes_envio = [n for n in pendentes if n.get("status") in ("pendente", "preparado")]
    respostas_recentes = sorted(respostas, key=lambda r: r.get("respondido_em", ""), reverse=True)[:20]

    return templates.TemplateResponse("nps.html", {
        "request":           request,
        "page":              "nps",
        "metricas":          metricas,
        "detratores":        detratores,
        "promotores":        promotores,
        "pendentes":         pendentes_envio,
        "pendentes_count":   len(pendentes_envio),
        "respostas_recentes": respostas_recentes,
        "contas_map":        contas,
    })


@app.get("/ti", response_class=HTMLResponse)
async def pagina_ti(request: Request):
    from core.politicas_ti import carregar_politicas_ti
    # Relatórios TI
    rel_seg   = _ler("relatorio_seguranca.json", None)
    hist_seg  = list(reversed(_ler("historico_auditorias_seguranca.json", [])))[:5]
    rel_qual  = _ler("relatorio_qualidade.json", None)
    hist_qual = list(reversed(_ler("historico_qualidade.json", [])))[:5]
    rel_mel   = _ler("relatorio_melhorias.json", None)
    hist_mel  = list(reversed(_ler("historico_melhorias.json", [])))[:10]
    # Políticas TI
    politicas_ti = carregar_politicas_ti()
    # Backups disponíveis
    backups_dir = config.PASTA_DADOS / "backups"
    backups = []
    if backups_dir.exists():
        backups = sorted(
            [d.name for d in backups_dir.iterdir() if d.is_dir() and d.name.startswith("backup_")],
            reverse=True,
        )[:5]
    # Scheduler estado
    sched_estado = _ler("scheduler_estado.json", {})
    return templates.TemplateResponse("ti.html", {
        "request":      request,
        "page":         "ti",
        "rel_seg":      rel_seg,
        "hist_seg":     hist_seg,
        "rel_qual":     rel_qual,
        "hist_qual":    hist_qual,
        "rel_mel":      rel_mel,
        "hist_mel":     hist_mel,
        "politicas_ti": politicas_ti,
        "backups":      backups,
        "sched":        sched_estado,
    })


@app.post("/acao/ti_politica")
async def acao_ti_politica(
    request:  Request,
    secao:    str = Form(...),
    campo:    str = Form(...),
    valor:    str = Form(...),
):
    from core.politicas_ti import atualizar_politica_ti
    # Converter valor para tipo correto
    val: object = valor
    if valor.lower() in ("true", "false"):
        val = valor.lower() == "true"
    elif valor.isdigit():
        val = int(valor)
    atualizar_politica_ti(secao, campo, val)
    return RedirectResponse("/governanca", status_code=303)


@app.get("/api/nps/resumo")
async def api_nps_resumo():
    from core.nps_feedback import calcular_nps_empresa
    return JSONResponse(calcular_nps_empresa())


@app.get("/api/governanca/resumo")
async def api_governanca_resumo():
    from core.governanca_conselho import resumir_governanca_ativa
    return JSONResponse(resumir_governanca_ativa())


# ─── Auxiliares internos app ──────────────────────────────────────────────────

def _inferir_alvo_tipo(tipo_comando: str) -> str:
    if "agente" in tipo_comando:
        return "agente"
    if "area" in tipo_comando:
        return "area"
    if "modo" in tipo_comando:
        return "empresa"
    if "linha" in tipo_comando or "prioridade" in tipo_comando:
        return "linha_servico"
    if "threshold" in tipo_comando:
        return "threshold"
    return "empresa"


def _atualizar_observabilidade():
    try:
        from core.observabilidade_empresa import executar_observabilidade
        executar_observabilidade()
    except Exception:
        pass


def _atualizar_politicas():
    try:
        from core.politicas_empresa import derivar_e_salvar_politicas
        derivar_e_salvar_politicas()
    except Exception:
        pass
