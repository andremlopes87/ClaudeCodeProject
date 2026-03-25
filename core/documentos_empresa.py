"""
core/documentos_empresa.py — Camada de documentos oficiais da Vetor.

Transforma os objetos do sistema (proposta, contrato, entrega) em artefatos
externos formais em formato HTML, versionados e rastreáveis.

Fluxo:
  proposta aprovada   → gerar_documento_proposta()
  contrato ativo      → gerar_documento_contrato()
  entrega aberta      → gerar_documento_resumo_entrega()

Cada geração:
  1. Lê o objeto-fonte do JSON correspondente
  2. Renderiza o HTML com dados reais
  3. Salva em artefatos/documentos/
  4. Registra em dados/documentos_oficiais.json
  5. Loga o evento em dados/historico_documentos_oficiais.json

Versionamento: se o objeto-fonte sofreu alteração relevante (checksum),
gera nova versão e marca a anterior como obsoleta.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import uuid
from datetime import datetime, date

log = logging.getLogger(__name__)

# ─── Caminhos ─────────────────────────────────────────────────────────────────
_BASE = pathlib.Path(__file__).parent.parent
_DADOS = _BASE / "dados"
_ARTEFATOS = _BASE / "artefatos" / "documentos"

_ARQ_DOCUMENTOS  = _DADOS / "documentos_oficiais.json"
_ARQ_HISTORICO   = _DADOS / "historico_documentos_oficiais.json"
_ARQ_PROPOSTAS   = _DADOS / "propostas_comerciais.json"
_ARQ_CONTRATOS   = _DADOS / "contratos_clientes.json"
_ARQ_PLANOS      = _DADOS / "planos_faturamento.json"
_ARQ_ENTREGAS    = _DADOS / "pipeline_entrega.json"
_ARQ_CONTAS      = _DADOS / "contas_clientes.json"
_ARQ_IDENTIDADE  = _DADOS / "identidade_empresa.json"
_ARQ_ASSINATURAS = _DADOS / "assinaturas_empresa.json"
_ARQ_GUIA        = _DADOS / "guia_comunicacao_empresa.json"

# ─── Status válidos ────────────────────────────────────────────────────────────
_STATUS_VALIDOS  = ("gerado", "atualizado", "arquivado", "obsoleto")
_TIPOS_VALIDOS   = ("proposta_comercial", "contrato_comercial", "resumo_entrega")

# ─── Propostas que geram documento ────────────────────────────────────────────
_STATUS_PROPOSTA_DOC = ("aprovada_para_envio", "enviada", "aceita")
# ─── Contratos que geram documento ────────────────────────────────────────────
_STATUS_CONTRATO_DOC = ("aguardando_ativacao", "ativo", "concluido")
# ─── Entregas que geram resumo ────────────────────────────────────────────────
_STATUS_ENTREGA_DOC  = ("onboarding", "em_execucao", "em_andamento", "aguardando_insumo", "concluida")


# ─── I/O ──────────────────────────────────────────────────────────────────────
def _ler(arq: pathlib.Path, padrao=None):
    if padrao is None:
        padrao = []
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def _salvar(arq: pathlib.Path, dados) -> None:
    arq.write_bytes(json.dumps(dados, ensure_ascii=False, indent=2).encode("utf-8"))


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hoje() -> str:
    return date.today().isoformat()


def _id_doc() -> str:
    return "doc_" + uuid.uuid4().hex[:8]


def _id_hist() -> str:
    return "hdoc_" + uuid.uuid4().hex[:8]


# ─── Checksum para detectar alteração na fonte ────────────────────────────────
def _checksum(obj: dict) -> str:
    campos_relevantes = {
        k: v for k, v in obj.items()
        if k not in ("atualizado_em", "gerado_em", "registrado_em",
                     "documento_proposta_id", "documento_contrato_id",
                     "documento_entrega_id", "documento_proposta_versao",
                     "documento_contrato_versao", "documento_entrega_versao")
    }
    raw = json.dumps(campos_relevantes, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


# ─── Identidade da empresa ────────────────────────────────────────────────────
def _identidade() -> dict:
    try:
        return _ler(_ARQ_IDENTIDADE, {})
    except Exception:
        return {}


def _assinatura_institucional() -> dict:
    try:
        assinaturas = _ler(_ARQ_ASSINATURAS, {})
        return assinaturas.get("institucional", {})
    except Exception:
        return {}


# ─── Registro de documentos ───────────────────────────────────────────────────
def registrar_documento_oficial(
    tipo_documento: str,
    referencia_tipo: str,
    referencia_id: str,
    conta_id: str,
    proposta_id: str,
    contrato_id: str,
    entrega_id: str,
    nome_arquivo: str,
    formato: str,
    caminho_arquivo: str,
    titulo: str,
    checksum_base: str,
    origem: str,
) -> dict:
    """Registra ou atualiza documento em documentos_oficiais.json."""
    documentos = _ler(_ARQ_DOCUMENTOS)

    # Verificar se já existe documento para esta referência
    existente = None
    for d in documentos:
        if (d.get("referencia_id") == referencia_id
                and d.get("tipo_documento") == tipo_documento
                and d.get("status") not in ("arquivado", "obsoleto")):
            existente = d
            break

    agora = _agora()

    if existente:
        versao_antiga = existente.get("versao", 1)
        novo_status = "atualizado"

        # Se checksum mudou, é nova versão e a antiga vira obsoleta
        if existente.get("checksum_base") != checksum_base:
            existente["status"] = "obsoleto"
            existente["atualizado_em"] = agora
            registrar_historico_documento(
                existente["id"], "documento_substituido",
                f"Substituído por nova versão {versao_antiga + 1}",
                origem,
            )
            # Criar novo documento como nova versão
            novo_doc = _novo_doc_entry(
                tipo_documento, referencia_tipo, referencia_id,
                conta_id, proposta_id, contrato_id, entrega_id,
                nome_arquivo, formato, caminho_arquivo, titulo,
                checksum_base, versao_antiga + 1, "gerado", agora, origem,
            )
            documentos.append(novo_doc)
            _salvar(_ARQ_DOCUMENTOS, documentos)
            registrar_historico_documento(
                novo_doc["id"], "documento_gerado",
                f"Versão {novo_doc['versao']} gerada | {titulo}",
                origem,
            )
            log.info(f"[documentos] nova versão v{novo_doc['versao']} para {referencia_id}")
            return novo_doc
        else:
            # Mesmo checksum — atualiza metadados sem bumpar versão
            existente["nome_arquivo"]    = nome_arquivo
            existente["caminho_arquivo"] = caminho_arquivo
            existente["atualizado_em"]   = agora
            existente["origem"]          = origem
            existente["status"]          = novo_status
            _salvar(_ARQ_DOCUMENTOS, documentos)
            registrar_historico_documento(
                existente["id"], "documento_regenerado",
                f"Regenerado sem alteração de conteúdo | {titulo}",
                origem,
            )
            return existente
    else:
        # Primeiro documento para esta referência
        novo_doc = _novo_doc_entry(
            tipo_documento, referencia_tipo, referencia_id,
            conta_id, proposta_id, contrato_id, entrega_id,
            nome_arquivo, formato, caminho_arquivo, titulo,
            checksum_base, 1, "gerado", agora, origem,
        )
        documentos.append(novo_doc)
        _salvar(_ARQ_DOCUMENTOS, documentos)
        registrar_historico_documento(
            novo_doc["id"], "documento_gerado",
            f"Primeira versão gerada | {titulo}",
            origem,
        )
        log.info(f"[documentos] documento gerado: {titulo}")
        return novo_doc


def _novo_doc_entry(
    tipo, ref_tipo, ref_id, conta_id, proposta_id, contrato_id,
    entrega_id, nome_arquivo, formato, caminho, titulo,
    checksum, versao, status, agora, origem,
) -> dict:
    return {
        "id":               _id_doc(),
        "tipo_documento":   tipo,
        "referencia_tipo":  ref_tipo,
        "referencia_id":    ref_id,
        "conta_id":         conta_id or "",
        "proposta_id":      proposta_id or "",
        "contrato_id":      contrato_id or "",
        "entrega_id":       entrega_id or "",
        "nome_arquivo":     nome_arquivo,
        "formato":          formato,
        "caminho_arquivo":  caminho,
        "versao":           versao,
        "status":           status,
        "titulo":           titulo,
        "checksum_base":    checksum,
        "gerado_em":        agora,
        "atualizado_em":    agora,
        "origem":           origem,
    }


def registrar_historico_documento(
    documento_id: str, evento: str, descricao: str, origem: str
) -> None:
    historico = _ler(_ARQ_HISTORICO)
    historico.append({
        "id":           _id_hist(),
        "documento_id": documento_id,
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HISTORICO, historico)


def obter_ultima_versao_documento(
    referencia_id: str, tipo_documento: str
) -> "dict | None":
    documentos = _ler(_ARQ_DOCUMENTOS)
    candidatos = [
        d for d in documentos
        if d.get("referencia_id") == referencia_id
        and d.get("tipo_documento") == tipo_documento
        and d.get("status") not in ("arquivado",)
    ]
    if not candidatos:
        return None
    return max(candidatos, key=lambda d: d.get("versao", 0))


def detectar_documento_obsoleto(referencia_id: str, tipo_documento: str,
                                 checksum_atual: str) -> bool:
    """Retorna True se o documento existente está desatualizado."""
    doc = obter_ultima_versao_documento(referencia_id, tipo_documento)
    if not doc:
        return False
    return doc.get("checksum_base") != checksum_atual


# ─── PARTE B — Renderização HTML ──────────────────────────────────────────────
_CSS_BASE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         font-size: 14px; color: #1a1a2e; background: #fff; line-height: 1.6; }
  .doc-wrap { max-width: 800px; margin: 0 auto; padding: 48px 40px; }
  .header { border-bottom: 3px solid #6c63ff; padding-bottom: 24px; margin-bottom: 32px; }
  .header .empresa { font-size: 13px; font-weight: 700; color: #6c63ff;
                     letter-spacing: 1px; text-transform: uppercase; }
  .header h1 { font-size: 22px; font-weight: 700; color: #1a1a2e; margin-top: 6px; }
  .header .meta { font-size: 11px; color: #666; margin-top: 8px; }
  .section { margin-bottom: 28px; }
  .section h2 { font-size: 13px; font-weight: 700; color: #6c63ff;
                text-transform: uppercase; letter-spacing: 0.8px;
                margin-bottom: 10px; padding-bottom: 4px;
                border-bottom: 1px solid #e8e6ff; }
  .section p { margin-bottom: 8px; color: #333; }
  .section ul { margin: 6px 0 8px 18px; }
  .section li { margin-bottom: 4px; color: #333; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
               margin-bottom: 10px; }
  .info-item label { font-size: 11px; color: #888; font-weight: 600;
                     text-transform: uppercase; display: block; }
  .info-item span { font-size: 14px; color: #1a1a2e; font-weight: 500; }
  .valor-box { background: #f4f2ff; border: 1px solid #d4cfff;
               border-radius: 8px; padding: 16px 20px; margin: 12px 0; }
  .valor-box .label { font-size: 11px; color: #6c63ff; font-weight: 700;
                      text-transform: uppercase; }
  .valor-box .valor { font-size: 24px; font-weight: 700; color: #1a1a2e; }
  .valor-box .sub { font-size: 12px; color: #666; margin-top: 2px; }
  .footer { margin-top: 48px; padding-top: 20px; border-top: 1px solid #e0e0e0;
            font-size: 12px; color: #888; }
  .footer strong { color: #6c63ff; }
  .tag { display: inline-block; background: #f0eefc; color: #6c63ff;
         font-size: 11px; font-weight: 600; padding: 2px 8px;
         border-radius: 12px; margin-right: 4px; }
  table { width: 100%; border-collapse: collapse; margin: 10px 0; }
  th { font-size: 11px; text-transform: uppercase; color: #888;
       font-weight: 600; text-align: left; padding: 6px 8px;
       border-bottom: 1px solid #e0e0e0; }
  td { padding: 8px; font-size: 13px; border-bottom: 1px solid #f0f0f0; }
  @media print {
    body { font-size: 12px; }
    .doc-wrap { padding: 20px; }
    .header { page-break-after: avoid; }
    .section { page-break-inside: avoid; }
  }
</style>
"""


def _html_wrap(titulo: str, corpo: str, empresa: str = "Vetor") -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titulo}</title>
  {_CSS_BASE}
</head>
<body>
<div class="doc-wrap">
{corpo}
</div>
</body>
</html>"""


def _fmt_brl(valor: float) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {valor}"


def _fmt_data(iso: str) -> str:
    try:
        d = date.fromisoformat(iso[:10])
        return d.strftime("%d/%m/%Y")
    except Exception:
        return iso or "—"


def _lista_html(itens: list) -> str:
    if not itens:
        return "<p class='text-muted'>—</p>"
    items_html = "".join(f"<li>{it}</li>" for it in itens)
    return f"<ul>{items_html}</ul>"


# ─── PARTE B1 — Proposta Comercial ────────────────────────────────────────────
def _render_proposta(proposta: dict, identidade: dict, assinatura: dict) -> str:
    empresa_nome = identidade.get("nome_exibicao") or identidade.get("nome_oficial", "Vetor")
    empresa_desc = identidade.get("descricao_curta", "Operações completas por IA")
    contraparte  = proposta.get("contraparte", "—")
    oferta_nome  = proposta.get("oferta_nome", "—")
    pacote_nome  = proposta.get("pacote_nome", "")
    valor        = proposta.get("proposta_valor", 0)
    prazo        = proposta.get("prazo_referencia", "—")
    escopo       = proposta.get("escopo", "—")
    entregaveis  = proposta.get("entregaveis", [])
    premissas    = proposta.get("premissas", [])
    fora_escopo  = proposta.get("fora_do_escopo", [])
    problema     = proposta.get("resumo_problema", "")
    versao       = proposta.get("versao", 1)
    data_proposta = _fmt_data(proposta.get("gerada_em", _hoje()))
    cidade       = proposta.get("cidade", "")
    categoria    = proposta.get("categoria", "")
    prop_id      = proposta.get("id", "")

    titulo_doc  = f"Proposta Comercial — {contraparte}"
    descricao_oferta = f"{oferta_nome}{' — ' + pacote_nome if pacote_nome else ''}"

    corpo = f"""
  <div class="header">
    <div class="empresa">{empresa_nome} &mdash; Proposta Comercial</div>
    <h1>{descricao_oferta}</h1>
    <div class="meta">
      Para: <strong>{contraparte}</strong>
      {' | ' + cidade if cidade else ''}
      {' | ' + categoria if categoria else ''}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Emitido em: {data_proposta}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Ref: {prop_id}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Versão {versao}
    </div>
  </div>

  <div class="section">
    <h2>Contexto identificado</h2>
    <p>{problema or 'Oportunidade de melhoria identificada na operação.'}</p>
  </div>

  <div class="section">
    <h2>Nossa proposta</h2>
    <p>{escopo}</p>
  </div>

  <div class="section">
    <h2>Entregáveis</h2>
    {_lista_html(entregaveis)}
  </div>

  <div class="section">
    <h2>Premissas de execução</h2>
    {_lista_html(premissas)}
  </div>

  <div class="section">
    <h2>Fora do escopo</h2>
    {_lista_html(fora_escopo)}
  </div>

  <div class="section">
    <h2>Investimento</h2>
    <div class="valor-box">
      <div class="label">Valor total</div>
      <div class="valor">{_fmt_brl(valor)}</div>
      <div class="sub">Prazo de referência: {prazo} dias úteis</div>
    </div>
  </div>

  <div class="section">
    <h2>Próximos passos</h2>
    <p>Para prosseguir, basta confirmar o aceite desta proposta. A {empresa_nome} entra
    em contato para alinhar o início das atividades e coleta de informações necessárias.</p>
  </div>

  <div class="footer">
    <strong>{empresa_nome}</strong><br>
    {empresa_desc}<br>
    {assinatura.get('linha_1', '') or assinatura.get('texto', '')}
  </div>
"""
    return _html_wrap(titulo_doc, corpo, empresa_nome)


# ─── PARTE B2 — Contrato Comercial ────────────────────────────────────────────
def _render_contrato(contrato: dict, proposta: dict, conta: dict,
                     plano: dict, identidade: dict, assinatura: dict) -> str:
    empresa_nome = identidade.get("nome_exibicao") or identidade.get("nome_oficial", "Vetor")
    empresa_desc = identidade.get("descricao_curta", "")
    contraparte  = contrato.get("contraparte", "—")
    oferta_nome  = contrato.get("oferta_nome", "")
    pacote_nome  = contrato.get("pacote_nome", "")
    valor_total  = contrato.get("valor_total", 0)
    modelo_cob   = contrato.get("modelo_cobranca", "avulso")
    n_parcelas   = contrato.get("numero_parcelas", 1)
    periodicidade = contrato.get("periodicidade", "unico")
    data_inicio  = _fmt_data(contrato.get("data_inicio", _hoje()))
    data_venc1   = _fmt_data(contrato.get("data_primeiro_vencimento", ""))
    ct_id        = contrato.get("id", "")
    escopo       = contrato.get("escopo_resumido", "")
    obs          = contrato.get("observacoes", "")
    gerado_em    = _fmt_data(contrato.get("gerado_em", _hoje()))

    escopo_proposta = proposta.get("escopo", "") if proposta else ""
    premissas       = proposta.get("premissas", []) if proposta else []
    fora_escopo     = proposta.get("fora_do_escopo", []) if proposta else []
    entregaveis     = proposta.get("entregaveis", []) if proposta else []

    conta_nome   = conta.get("nome_empresa", contraparte) if conta else contraparte
    conta_cidade = conta.get("cidade", "") if conta else ""
    conta_email  = conta.get("email_comercial", "") if conta else ""

    descricao_modelo = {
        "avulso":               "Pagamento único",
        "parcela_fixa":         f"{n_parcelas} parcela(s) fixas",
        "recorrente_mensal":    "Recorrente mensal",
        "recorrente_trimestral": "Recorrente trimestral",
    }.get(modelo_cob, modelo_cob)

    # Parcelas do plano
    parcelas_html = ""
    if plano and plano.get("parcelas"):
        rows = ""
        for p in plano["parcelas"]:
            rows += f"<tr><td>Parcela {p['numero']}</td><td>{_fmt_brl(p['valor'])}</td><td>{_fmt_data(p['vencimento'])}</td><td>{p.get('status','—')}</td></tr>"
        parcelas_html = f"""
    <table>
      <thead><tr><th>Parcela</th><th>Valor</th><th>Vencimento</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""

    titulo_doc = f"Compromisso Comercial — {contraparte}"

    corpo = f"""
  <div class="header">
    <div class="empresa">{empresa_nome} &mdash; Compromisso Comercial</div>
    <h1>{oferta_nome}{' — ' + pacote_nome if pacote_nome else ''}</h1>
    <div class="meta">
      Cliente: <strong>{conta_nome}</strong>
      {' | ' + conta_cidade if conta_cidade else ''}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Emitido em: {gerado_em}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Ref: {ct_id}
    </div>
  </div>

  <div class="section">
    <h2>Identificação das partes</h2>
    <div class="info-grid">
      <div class="info-item">
        <label>Prestador</label>
        <span>{empresa_nome}</span>
      </div>
      <div class="info-item">
        <label>Cliente</label>
        <span>{conta_nome}{' | ' + conta_email if conta_email else ''}</span>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Objeto</h2>
    <p>{escopo or escopo_proposta or 'Prestação de serviços conforme oferta acordada.'}</p>
  </div>

  <div class="section">
    <h2>Entregáveis</h2>
    {_lista_html(entregaveis)}
  </div>

  <div class="section">
    <h2>Premissas operacionais</h2>
    {_lista_html(premissas)}
  </div>

  <div class="section">
    <h2>Fora do escopo</h2>
    {_lista_html(fora_escopo)}
  </div>

  <div class="section">
    <h2>Modelo financeiro</h2>
    <div class="valor-box">
      <div class="label">Valor total</div>
      <div class="valor">{_fmt_brl(valor_total)}</div>
      <div class="sub">{descricao_modelo} · Início: {data_inicio} · 1º vencimento: {data_venc1}</div>
    </div>
    {parcelas_html}
  </div>

  <div class="section">
    <h2>Vigência</h2>
    <p>Início em <strong>{data_inicio}</strong>. Validade conforme execução e recebimento dos entregáveis acordados.</p>
    {'<p>' + obs + '</p>' if obs else ''}
  </div>

  <div class="footer">
    <strong>{empresa_nome}</strong><br>
    {empresa_desc}<br>
    {assinatura.get('linha_1', '') or assinatura.get('texto', '')}
  </div>
"""
    return _html_wrap(titulo_doc, corpo, empresa_nome)


# ─── PARTE B3 — Resumo de Entrega / Onboarding ────────────────────────────────
def _render_entrega(entrega: dict, proposta: dict, contrato: dict,
                    identidade: dict, assinatura: dict) -> str:
    empresa_nome  = identidade.get("nome_exibicao") or identidade.get("nome_oficial", "Vetor")
    empresa_desc  = identidade.get("descricao_curta", "")
    contraparte   = entrega.get("contraparte", "—")
    linha_servico = entrega.get("linha_servico", "—")
    tipo_entrega  = entrega.get("tipo_entrega", "")
    etapa_atual   = entrega.get("etapa_atual", "")
    prioridade    = entrega.get("prioridade", "media")
    cidade        = entrega.get("cidade", "")
    ent_id        = entrega.get("id", "")
    criado_em     = _fmt_data(entrega.get("registrado_em") or entrega.get("criado_em", _hoje()))

    # Contexto da proposta
    escopo        = (proposta or {}).get("escopo", "") or (contrato or {}).get("escopo_resumido", "")
    entregaveis   = (proposta or {}).get("entregaveis", [])
    premissas     = (proposta or {}).get("premissas", [])
    checklist_ex  = (proposta or {}).get("checklist_execucao", [])
    oferta_nome   = (proposta or {}).get("oferta_nome", "") or (entrega.get("linha_servico", "").replace("_", " ").title())

    # Checklist de entrega
    checklist_ent = entrega.get("checklist", [])
    bloqueios     = entrega.get("bloqueios", [])
    pct           = entrega.get("percentual_conclusao", 0)

    titulo_doc = f"Resumo de Entrega — {contraparte}"

    corpo = f"""
  <div class="header">
    <div class="empresa">{empresa_nome} &mdash; Resumo de Entrega</div>
    <h1>{oferta_nome or tipo_entrega or linha_servico}</h1>
    <div class="meta">
      Cliente: <strong>{contraparte}</strong>
      {' | ' + cidade if cidade else ''}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Abertura: {criado_em}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Ref: {ent_id}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      Etapa: {etapa_atual or '—'}
      &nbsp;&nbsp;·&nbsp;&nbsp;
      <span class="tag">Prioridade {prioridade}</span>
    </div>
  </div>

  <div class="section">
    <h2>Objetivo da entrega</h2>
    <p>{escopo or 'Execução dos serviços contratados conforme escopo acordado.'}</p>
  </div>

  <div class="section">
    <h2>Entregáveis</h2>
    {_lista_html(entregaveis) if entregaveis else '<p>Ver escopo do contrato.</p>'}
  </div>

  <div class="section">
    <h2>Premissas e insumos esperados</h2>
    {_lista_html(premissas)}
  </div>

  <div class="section">
    <h2>Checklist de execução</h2>
    {_lista_html(checklist_ex or checklist_ent)}
  </div>

  {'<div class="section"><h2>Bloqueios ativos</h2>' + _lista_html(bloqueios) + '</div>' if bloqueios else ''}

  <div class="section">
    <h2>Status atual</h2>
    <div class="info-grid">
      <div class="info-item">
        <label>Progresso</label>
        <span>{pct}%</span>
      </div>
      <div class="info-item">
        <label>Etapa</label>
        <span>{etapa_atual or '—'}</span>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Próxima etapa</h2>
    <p>Confirmar recebimento dos insumos necessários e avançar conforme checklist.
    A {empresa_nome} manterá o cliente atualizado a cada marco concluído.</p>
  </div>

  <div class="footer">
    <strong>{empresa_nome}</strong><br>
    {empresa_desc}<br>
    {assinatura.get('linha_1', '') or assinatura.get('texto', '')}
  </div>
"""
    return _html_wrap(titulo_doc, corpo, empresa_nome)


# ─── PARTE C — Funções de geração ─────────────────────────────────────────────
def salvar_documento_gerado(nome_arquivo: str, conteudo: str) -> str:
    """Salva HTML em artefatos/documentos/ e retorna o caminho relativo."""
    _ARTEFATOS.mkdir(parents=True, exist_ok=True)
    caminho = _ARTEFATOS / nome_arquivo
    caminho.write_bytes(conteudo.encode("utf-8"))
    return str(caminho.relative_to(_BASE)).replace("\\", "/")


def gerar_documento_proposta(proposta_id: str, origem: str = "") -> "dict | None":
    """
    Gera (ou regenera) o documento HTML oficial de uma proposta.
    Retorna o registro do documento ou None em caso de erro.
    """
    propostas = _ler(_ARQ_PROPOSTAS)
    proposta  = next((p for p in propostas if p.get("id") == proposta_id), None)
    if not proposta:
        log.warning(f"[documentos] proposta {proposta_id} não encontrada")
        return None

    identidade  = _identidade()
    assinatura  = _assinatura_institucional()
    checksum    = _checksum(proposta)
    versao_atual = 1
    doc_existente = obter_ultima_versao_documento(proposta_id, "proposta_comercial")
    if doc_existente:
        versao_atual = doc_existente.get("versao", 1)
        if doc_existente.get("checksum_base") == checksum:
            versao_atual = versao_atual
        else:
            versao_atual = versao_atual + 1

    nome_arquivo = f"proposta_{proposta_id}_v{versao_atual}.html"
    html = _render_proposta(proposta, identidade, assinatura)
    caminho = salvar_documento_gerado(nome_arquivo, html)

    conta_id   = proposta.get("conta_id", "")
    titulo     = f"Proposta Comercial — {proposta.get('contraparte', '—')}"

    doc = registrar_documento_oficial(
        tipo_documento   = "proposta_comercial",
        referencia_tipo  = "proposta",
        referencia_id    = proposta_id,
        conta_id         = conta_id,
        proposta_id      = proposta_id,
        contrato_id      = "",
        entrega_id       = "",
        nome_arquivo     = nome_arquivo,
        formato          = "html",
        caminho_arquivo  = caminho,
        titulo           = titulo,
        checksum_base    = checksum,
        origem           = origem,
    )

    # Atualizar campo na proposta
    _atualizar_campo_propostas(proposta_id, {
        "documento_proposta_id":     doc["id"],
        "documento_proposta_versao": doc["versao"],
    })

    return doc


def gerar_documento_contrato(contrato_id: str, origem: str = "") -> "dict | None":
    """
    Gera (ou regenera) o documento HTML oficial de um contrato/compromisso.
    """
    contratos = _ler(_ARQ_CONTRATOS)
    contrato  = next((c for c in contratos if c.get("id") == contrato_id), None)
    if not contrato:
        log.warning(f"[documentos] contrato {contrato_id} não encontrado")
        return None

    propostas   = _ler(_ARQ_PROPOSTAS)
    proposta    = next((p for p in propostas
                        if p.get("id") == contrato.get("proposta_id")), None)
    planos      = _ler(_ARQ_PLANOS)
    plano       = next((p for p in planos
                        if p.get("contrato_id") == contrato_id), None)
    contas      = _ler(_ARQ_CONTAS)
    conta       = next((c for c in contas
                        if c.get("id") == contrato.get("conta_id")), None)
    identidade  = _identidade()
    assinatura  = _assinatura_institucional()

    checksum    = _checksum(contrato)
    versao_atual = 1
    doc_existente = obter_ultima_versao_documento(contrato_id, "contrato_comercial")
    if doc_existente:
        versao_atual = doc_existente.get("versao", 1)
        if doc_existente.get("checksum_base") != checksum:
            versao_atual += 1

    nome_arquivo = f"contrato_{contrato_id}_v{versao_atual}.html"
    html = _render_contrato(contrato, proposta, conta, plano, identidade, assinatura)
    caminho = salvar_documento_gerado(nome_arquivo, html)

    titulo = f"Compromisso Comercial — {contrato.get('contraparte', '—')}"

    doc = registrar_documento_oficial(
        tipo_documento   = "contrato_comercial",
        referencia_tipo  = "contrato",
        referencia_id    = contrato_id,
        conta_id         = contrato.get("conta_id", ""),
        proposta_id      = contrato.get("proposta_id", ""),
        contrato_id      = contrato_id,
        entrega_id       = "",
        nome_arquivo     = nome_arquivo,
        formato          = "html",
        caminho_arquivo  = caminho,
        titulo           = titulo,
        checksum_base    = checksum,
        origem           = origem,
    )

    _atualizar_campo_contratos(contrato_id, {
        "documento_contrato_id":     doc["id"],
        "documento_contrato_versao": doc["versao"],
    })

    return doc


def gerar_documento_resumo_entrega(entrega_id: str, origem: str = "") -> "dict | None":
    """
    Gera (ou regenera) o resumo oficial de onboarding/entrega.
    """
    entregas = _ler(_ARQ_ENTREGAS)
    entrega  = next((e for e in entregas if e.get("id") == entrega_id), None)
    if not entrega:
        log.warning(f"[documentos] entrega {entrega_id} não encontrada")
        return None

    propostas = _ler(_ARQ_PROPOSTAS)
    proposta  = None
    opp_id = entrega.get("oportunidade_id", "")
    if opp_id:
        proposta = next((p for p in propostas
                         if p.get("oportunidade_id") == opp_id), None)
    if not proposta:
        # tenta por conta_id
        conta_id = entrega.get("conta_id", "")
        if conta_id:
            proposta = next((p for p in propostas
                             if p.get("conta_id") == conta_id
                             and p.get("status") in ("aceita", "aprovada_para_envio")), None)

    contratos = _ler(_ARQ_CONTRATOS)
    contrato  = None
    if opp_id:
        contrato = next((c for c in contratos
                         if c.get("oportunidade_id") == opp_id), None)

    identidade = _identidade()
    assinatura = _assinatura_institucional()

    checksum    = _checksum(entrega)
    versao_atual = 1
    doc_existente = obter_ultima_versao_documento(entrega_id, "resumo_entrega")
    if doc_existente:
        versao_atual = doc_existente.get("versao", 1)
        if doc_existente.get("checksum_base") != checksum:
            versao_atual += 1

    nome_arquivo = f"onboarding_{entrega_id}_v{versao_atual}.html"
    html = _render_entrega(entrega, proposta, contrato, identidade, assinatura)
    caminho = salvar_documento_gerado(nome_arquivo, html)

    titulo = f"Resumo de Entrega — {entrega.get('contraparte', '—')}"

    doc = registrar_documento_oficial(
        tipo_documento   = "resumo_entrega",
        referencia_tipo  = "entrega",
        referencia_id    = entrega_id,
        conta_id         = entrega.get("conta_id", ""),
        proposta_id      = proposta.get("id", "") if proposta else "",
        contrato_id      = contrato.get("id", "") if contrato else "",
        entrega_id       = entrega_id,
        nome_arquivo     = nome_arquivo,
        formato          = "html",
        caminho_arquivo  = caminho,
        titulo           = titulo,
        checksum_base    = checksum,
        origem           = origem,
    )

    _atualizar_campo_entregas(entrega_id, {
        "documento_entrega_id":     doc["id"],
        "documento_entrega_versao": doc["versao"],
    })

    return doc


# ─── PARTE D — Atualização de campos nas fontes ───────────────────────────────
def _atualizar_campo_propostas(proposta_id: str, campos: dict) -> None:
    try:
        propostas = _ler(_ARQ_PROPOSTAS)
        for p in propostas:
            if p.get("id") == proposta_id:
                p.update(campos)
                break
        _salvar(_ARQ_PROPOSTAS, propostas)
    except Exception as exc:
        log.debug(f"[documentos] atualizar campo proposta: {exc}")


def _atualizar_campo_contratos(contrato_id: str, campos: dict) -> None:
    try:
        contratos = _ler(_ARQ_CONTRATOS)
        for c in contratos:
            if c.get("id") == contrato_id:
                c.update(campos)
                break
        _salvar(_ARQ_CONTRATOS, contratos)
    except Exception as exc:
        log.debug(f"[documentos] atualizar campo contrato: {exc}")


def _atualizar_campo_entregas(entrega_id: str, campos: dict) -> None:
    try:
        entregas = _ler(_ARQ_ENTREGAS)
        for e in entregas:
            if e.get("id") == entrega_id:
                e.update(campos)
                break
        _salvar(_ARQ_ENTREGAS, entregas)
    except Exception as exc:
        log.debug(f"[documentos] atualizar campo entrega: {exc}")


# ─── PARTE E — Processamento em lote ──────────────────────────────────────────
def processar_documentos_pendentes(origem: str = "") -> dict:
    """
    Batch: gera documentos para propostas/contratos/entregas que ainda não têm
    documento gerado (ou cujo objeto-fonte foi alterado).
    """
    n_propostas = n_contratos = n_entregas = n_erros = 0

    # Propostas elegíveis
    for prop in _ler(_ARQ_PROPOSTAS):
        if prop.get("status") not in _STATUS_PROPOSTA_DOC:
            continue
        prop_id = prop.get("id", "")
        if not prop_id:
            continue
        try:
            chk = _checksum(prop)
            if detectar_documento_obsoleto(prop_id, "proposta_comercial", chk) \
                    or not obter_ultima_versao_documento(prop_id, "proposta_comercial"):
                doc = gerar_documento_proposta(prop_id, origem)
                if doc:
                    n_propostas += 1
        except Exception as exc:
            log.warning(f"[documentos] proposta {prop_id}: {exc}")
            n_erros += 1

    # Contratos elegíveis
    for ct in _ler(_ARQ_CONTRATOS):
        if ct.get("status") not in _STATUS_CONTRATO_DOC:
            continue
        ct_id = ct.get("id", "")
        if not ct_id:
            continue
        try:
            chk = _checksum(ct)
            if detectar_documento_obsoleto(ct_id, "contrato_comercial", chk) \
                    or not obter_ultima_versao_documento(ct_id, "contrato_comercial"):
                doc = gerar_documento_contrato(ct_id, origem)
                if doc:
                    n_contratos += 1
        except Exception as exc:
            log.warning(f"[documentos] contrato {ct_id}: {exc}")
            n_erros += 1

    # Entregas elegíveis
    for ent in _ler(_ARQ_ENTREGAS):
        st = ent.get("status_entrega", ent.get("status", ""))
        if st not in _STATUS_ENTREGA_DOC:
            continue
        ent_id = ent.get("id", "")
        if not ent_id:
            continue
        try:
            chk = _checksum(ent)
            if detectar_documento_obsoleto(ent_id, "resumo_entrega", chk) \
                    or not obter_ultima_versao_documento(ent_id, "resumo_entrega"):
                doc = gerar_documento_resumo_entrega(ent_id, origem)
                if doc:
                    n_entregas += 1
        except Exception as exc:
            log.warning(f"[documentos] entrega {ent_id}: {exc}")
            n_erros += 1

    log.info(
        f"[documentos] batch: {n_propostas} prop | "
        f"{n_contratos} ct | {n_entregas} ent | {n_erros} erros"
    )
    return {
        "documentos_proposta":  n_propostas,
        "documentos_contrato":  n_contratos,
        "documentos_entrega":   n_entregas,
        "erros":                n_erros,
        "total":                n_propostas + n_contratos + n_entregas,
    }


# ─── PARTE F — KPIs para painel ───────────────────────────────────────────────
def resumir_para_painel() -> dict:
    documentos = _ler(_ARQ_DOCUMENTOS)
    propostas  = _ler(_ARQ_PROPOSTAS)
    contratos  = _ler(_ARQ_CONTRATOS)
    entregas   = _ler(_ARQ_ENTREGAS)

    ativos = [d for d in documentos if d.get("status") not in ("arquivado",)]

    total          = len(ativos)
    n_prop_doc     = len([d for d in ativos if d["tipo_documento"] == "proposta_comercial" and d["status"] != "obsoleto"])
    n_ct_doc       = len([d for d in ativos if d["tipo_documento"] == "contrato_comercial" and d["status"] != "obsoleto"])
    n_ent_doc      = len([d for d in ativos if d["tipo_documento"] == "resumo_entrega" and d["status"] != "obsoleto"])
    n_obsoletos    = len([d for d in documentos if d.get("status") == "obsoleto"])

    props_elegiveis = [p for p in propostas if p.get("status") in _STATUS_PROPOSTA_DOC]
    cts_elegiveis   = [c for c in contratos if c.get("status") in _STATUS_CONTRATO_DOC]
    ents_elegiveis  = [e for e in entregas
                       if e.get("status_entrega", e.get("status", "")) in _STATUS_ENTREGA_DOC]

    prop_ids_com_doc = {d["proposta_id"] for d in ativos
                        if d["tipo_documento"] == "proposta_comercial" and d["status"] != "obsoleto"}
    ct_ids_com_doc   = {d["contrato_id"] for d in ativos
                        if d["tipo_documento"] == "contrato_comercial" and d["status"] != "obsoleto"}
    ent_ids_com_doc  = {d["entrega_id"] for d in ativos
                        if d["tipo_documento"] == "resumo_entrega" and d["status"] != "obsoleto"}

    sem_doc_prop = len([p for p in props_elegiveis if p.get("id") not in prop_ids_com_doc])
    sem_doc_ct   = len([c for c in cts_elegiveis   if c.get("id") not in ct_ids_com_doc])
    sem_doc_ent  = len([e for e in ents_elegiveis   if e.get("id") not in ent_ids_com_doc])

    return {
        "total_documentos":           total,
        "propostas_com_documento":    n_prop_doc,
        "contratos_com_documento":    n_ct_doc,
        "entregas_com_resumo":        n_ent_doc,
        "documentos_obsoletos":       n_obsoletos,
        "propostas_sem_documento":    sem_doc_prop,
        "contratos_sem_documento":    sem_doc_ct,
        "entregas_sem_resumo":        sem_doc_ent,
    }
