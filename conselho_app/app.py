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
        "prov_email":     prov_resumo,
        "ofertas_resumo": ofertas_resumo,
    })


@app.get("/agentes", response_class=HTMLResponse)
async def pagina_agentes(request: Request):
    from core.governanca_conselho import resumir_governanca_ativa
    return templates.TemplateResponse("agentes.html", {
        "request": request,
        "page":    "agentes",
        "agentes": _agentes(),
        "gov":     resumir_governanca_ativa(),
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
    return templates.TemplateResponse("financeiro.html", {
        "request":  request,
        "page":     "financeiro",
        "fin":      areas.get("financeiro", {}),
        "caixa":    caixa,
        "previsao": previsao,
        "riscos":   riscos,
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
    from core.integrador_email import carregar_config_canal_email, gerar_fila_envio_email
    config_canal = carregar_config_canal_email()
    fila         = gerar_fila_envio_email()
    estado       = _ler("estado_canal_email.json", {})
    historico    = _ler("historico_email.json", [])
    historico_recente = sorted(historico, key=lambda x: x.get("registrado_em",""), reverse=True)[:30]
    preparados   = [e for e in fila if e.get("status") == "preparado"]
    bloqueados   = [e for e in fila if e.get("status") == "bloqueado"]
    return templates.TemplateResponse("email.html", {
        "request":           request,
        "page":              "email",
        "config_canal":      config_canal,
        "estado":            estado,
        "fila_email":        fila,
        "preparados":        preparados,
        "bloqueados":        bloqueados,
        "historico_recente": historico_recente,
    })


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
    gov     = resumir_governanca_ativa()
    politicas_resumo = resumir_politicas_ativas()
    historico = _ler("historico_comandos_conselho.json", [])
    historico_recente = sorted(historico, key=lambda x: x.get("registrado_em",""), reverse=True)[:20]
    return templates.TemplateResponse("governanca.html", {
        "request":    request,
        "page":       "governanca",
        "gov":        gov,
        "politicas":  politicas_resumo,
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
