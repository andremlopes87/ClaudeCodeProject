"""
tests/test_identidade_empresa.py

Valida a camada de identidade operacional da empresa (v0.39).

Testa:
  1. Inicialização: arquivos criados com padrões corretos
  2. Salvar identidade completa e verificar persistência
  3. Salvar guia de comunicação
  4. Salvar assinaturas e renderizar com variáveis
  5. Salvar canais e verificar status
  6. obter_contexto_remetente: campos obrigatórios presentes
  7. obter_contexto_comercial: campos para agente_comercial
  8. Histórico: eventos registrados em cada operação
  9. _avaliar_completude: percentual e campos pendentes corretos
"""

import sys
import io
import json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from core.identidade_empresa import (
    carregar_identidade, carregar_guia_comunicacao,
    carregar_assinaturas, carregar_canais,
    salvar_identidade, salvar_guia_comunicacao,
    salvar_assinaturas, salvar_canais,
    obter_assinatura, obter_contexto_remetente,
    obter_contexto_comercial, resumir_identidade_para_painel,
    _ARQ_IDENTIDADE, _ARQ_GUIA, _ARQ_ASSINATURAS,
    _ARQ_CANAIS, _ARQ_HISTORICO,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _limpar():
    for arq in [_ARQ_IDENTIDADE, _ARQ_GUIA, _ARQ_ASSINATURAS, _ARQ_CANAIS, _ARQ_HISTORICO]:
        if arq.exists():
            arq.unlink()


# ─── Teste 1: Inicialização ──────────────────────────────────────────────────

def test_inicializacao():
    print("\n=== Teste 1: Inicialização com Padrões ===")
    _limpar()

    ident = carregar_identidade()
    check(bool(ident.get("nome_oficial")), "nome_oficial presente")
    check(bool(ident.get("criado_em")), "criado_em preenchido na primeira carga")
    check(_ARQ_IDENTIDADE.exists(), "identidade_empresa.json criado")

    guia = carregar_guia_comunicacao()
    check(bool(guia.get("tom_voz")), "tom_voz presente")
    check(_ARQ_GUIA.exists(), "guia_comunicacao_empresa.json criado")

    assin = carregar_assinaturas()
    check(bool(assin.get("assinatura_comercial_texto")), "assinatura_comercial_texto presente")
    check(_ARQ_ASSINATURAS.exists(), "assinaturas_empresa.json criado")

    canais = carregar_canais()
    check(canais.get("status_configuracao_email") == "nao_definido", "status email=nao_definido padrão")
    check(_ARQ_CANAIS.exists(), "canais_empresa.json criado")

    print(f"    Identidade padrão: nome='{ident['nome_oficial']}' | criado={ident['criado_em'][:10]}")


# ─── Teste 2: Salvar identidade completa ─────────────────────────────────────

def test_salvar_identidade():
    print("\n=== Teste 2: Salvar Identidade Completa ===")

    dados = carregar_identidade()
    dados.update({
        "nome_oficial":           "PresençaDigital Soluções Ltda",
        "nome_exibicao":          "PresençaDigital",
        "descricao_curta":        "Fazemos sua empresa aparecer online e vender mais com tecnologia simples.",
        "descricao_media":        "Ajudamos pequenos negócios a construir presença digital real e automatizar atendimento.",
        "proposta_valor_resumida": "Presença online e automação para quem não tem tempo de cuidar disso sozinho.",
        "publico_alvo":           "Pequenos negócios locais: barbearias, restaurantes, oficinas, padarias.",
        "linhas_servico":         ["marketing_presenca_digital", "automacao_atendimento"],
        "cidade_base":            "São Paulo",
        "pais_base":              "Brasil",
        "idioma_padrao":          "pt-BR",
    })
    resultado = salvar_identidade(dados, origem="teste")

    lido = json.loads(_ARQ_IDENTIDADE.read_text(encoding="utf-8"))
    check(lido["nome_oficial"] == "PresençaDigital Soluções Ltda", "nome_oficial salvo corretamente")
    check(lido["cidade_base"] == "São Paulo", "cidade_base salva")
    check(len(lido["linhas_servico"]) == 2, "linhas_servico salvas")
    check(bool(lido["atualizado_em"]), "atualizado_em preenchido")
    print(f"    Identidade salva: {lido['nome_oficial']} | {lido['cidade_base']}")


# ─── Teste 3: Guia de comunicação ────────────────────────────────────────────

def test_guia_comunicacao():
    print("\n=== Teste 3: Guia de Comunicação ===")

    dados = carregar_guia_comunicacao()
    dados.update({
        "tom_voz":           "claro, objetivo, consultivo, sem floreio",
        "nivel_formalidade": "medio",
        "postura_comercial": "diagnostica, sem pressão — mostrar o problema, deixar o cliente decidir",
        "postura_cobranca":  "firme e respeitosa",
        "estilo_abertura":   "direto ao ponto: apresentar o problema identificado antes de qualquer oferta",
        "estilo_fechamento": "ação clara: próximo passo concreto, sem pressão",
        "palavras_que_usa":  ["resultado", "simples", "prático", "rápido"],
        "palavras_que_evita": ["incrível", "revolucionário", "disruptivo"],
        "observacoes":       "Nunca prometer resultado que depende de terceiros.",
    })
    salvar_guia_comunicacao(dados, origem="teste")

    lido = json.loads(_ARQ_GUIA.read_text(encoding="utf-8"))
    check(lido["tom_voz"] == "claro, objetivo, consultivo, sem floreio", "tom_voz salvo")
    check(len(lido["palavras_que_usa"]) == 4, "palavras_que_usa salvas")
    check(len(lido["palavras_que_evita"]) == 3, "palavras_que_evita salvas")
    print(f"    Tom: '{lido['tom_voz']}' | Formalidade: {lido['nivel_formalidade']}")


# ─── Teste 4: Assinaturas ────────────────────────────────────────────────────

def test_assinaturas():
    print("\n=== Teste 4: Assinaturas e Renderização ===")

    dados = carregar_assinaturas()
    dados.update({
        "nome_remetente_padrao":  "Equipe PresençaDigital",
        "cargo_remetente_padrao": "Consultoria de Presença Digital",
        "assinatura_comercial_texto": (
            "\n---\n{nome_remetente}\n{cargo}\n{nome_empresa}\n{email_comercial}"
        ),
        "assinatura_institucional_texto": (
            "\n---\n{nome_empresa}\n{descricao_curta}\n{site_oficial}"
        ),
    })
    salvar_assinaturas(dados, origem="teste")

    # Renderizar assinatura comercial
    assin = obter_assinatura("comercial")
    check("PresençaDigital" in assin or "Equipe" in assin, "nome_empresa ou remetente na assinatura comercial")
    check("Consultoria" in assin, "cargo na assinatura")
    print(f"    Assinatura comercial:\n{assin}")

    # Assinatura institucional
    assin_inst = obter_assinatura("institucional")
    check(bool(assin_inst), "assinatura institucional gerada")
    print(f"    Assinatura institucional:\n{assin_inst}")


# ─── Teste 5: Canais ─────────────────────────────────────────────────────────

def test_canais():
    print("\n=== Teste 5: Canais Oficiais ===")

    dados = carregar_canais()
    dados.update({
        "dominio_oficial_planejado":  "presencadigital.com.br",
        "email_principal_planejado":  "contato@presencadigital.com.br",
        "email_comercial_planejado":  "comercial@presencadigital.com.br",
        "email_financeiro_planejado": "financeiro@presencadigital.com.br",
        "instagram_oficial":          "@presencadigital",
        "site_oficial":               "https://presencadigital.com.br",
        "whatsapp_oficial":           "11999990000",
        "status_configuracao_email":  "definido_sem_configurar",
        "status_configuracao_site":   "nao_definido",
        "observacoes":                "Domínio registrado. Email ainda não configurado.",
    })
    salvar_canais(dados, origem="teste")

    lido = json.loads(_ARQ_CANAIS.read_text(encoding="utf-8"))
    check(lido["dominio_oficial_planejado"] == "presencadigital.com.br", "domínio salvo")
    check(lido["status_configuracao_email"] == "definido_sem_configurar", "status_email salvo")
    check(lido["email_comercial_planejado"] == "comercial@presencadigital.com.br", "email_comercial salvo")
    print(f"    Domínio: {lido['dominio_oficial_planejado']} | Status email: {lido['status_configuracao_email']}")


# ─── Teste 6: Contexto do remetente ─────────────────────────────────────────

def test_contexto_remetente():
    print("\n=== Teste 6: Contexto do Remetente ===")

    ctx = obter_contexto_remetente()
    check(bool(ctx.get("nome_empresa")), "nome_empresa presente")
    check(bool(ctx.get("nome_remetente")), "nome_remetente presente")
    check("status_email" in ctx, "status_email presente")
    check("assinatura_comercial" in ctx, "assinatura_comercial presente")
    print(f"    Empresa: '{ctx['nome_empresa']}' | Remetente: '{ctx['nome_remetente']}'")
    print(f"    Email comercial: '{ctx['email_comercial']}' | Status: '{ctx['status_email']}'")


# ─── Teste 7: Contexto comercial ─────────────────────────────────────────────

def test_contexto_comercial():
    print("\n=== Teste 7: Contexto Comercial ===")

    ctx = obter_contexto_comercial()
    check(bool(ctx.get("nome_empresa")), "nome_empresa presente")
    check(bool(ctx.get("tom_voz")), "tom_voz presente")
    check(bool(ctx.get("postura_comercial")), "postura_comercial presente")
    check(isinstance(ctx.get("linhas_servico"), list), "linhas_servico é lista")
    print(f"    Empresa: '{ctx['nome_empresa']}' | Tom: '{ctx['tom_voz']}'")
    print(f"    Postura: '{ctx['postura_comercial']}'")


# ─── Teste 8: Histórico ──────────────────────────────────────────────────────

def test_historico():
    print("\n=== Teste 8: Histórico de Alterações ===")

    historico = json.loads(_ARQ_HISTORICO.read_text(encoding="utf-8")) if _ARQ_HISTORICO.exists() else []
    check(len(historico) >= 3, f"pelo menos 3 eventos no histórico (got {len(historico)})")

    eventos = {h["evento"] for h in historico}
    check("identidade_atualizada" in eventos, "evento identidade_atualizada registrado")
    check("guia_comunicacao_atualizado" in eventos, "evento guia_comunicacao_atualizado registrado")
    check("canais_atualizados" in eventos, "evento canais_atualizados registrado")
    print(f"    Eventos registrados: {sorted(eventos)}")


# ─── Teste 9: Completude ─────────────────────────────────────────────────────

def test_completude():
    print("\n=== Teste 9: Avaliação de Completude ===")

    resumo = resumir_identidade_para_painel()
    status = resumo["status_completo"]

    check("percentual" in status, "percentual presente")
    check("campos_ok" in status, "campos_ok presente")
    check("campos_pendentes" in status, "campos_pendentes presente")
    check(status["percentual"] > 0, f"percentual > 0 (got {status['percentual']})")
    check(status["status"] in ("completo", "parcial", "inicial"), "status válido")

    print(f"    Completude: {status['percentual']}% | status={status['status']}")
    print(f"    OK: {status['campos_ok']}")
    print(f"    Pendentes: {status['campos_pendentes']}")


# ─── Runner ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    testes = [
        test_inicializacao,
        test_salvar_identidade,
        test_guia_comunicacao,
        test_assinaturas,
        test_canais,
        test_contexto_remetente,
        test_contexto_comercial,
        test_historico,
        test_completude,
    ]

    falhos = []
    for t in testes:
        try:
            t()
        except AssertionError as e:
            falhos.append(f"{t.__name__}: {e}")
        except Exception as e:
            falhos.append(f"{t.__name__}: ERRO INESPERADO: {e}")
            import traceback; traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Resultado: {len(testes)-len(falhos)}/{len(testes)} testes passaram")
    if falhos:
        print("Falhos:")
        for f in falhos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM")
