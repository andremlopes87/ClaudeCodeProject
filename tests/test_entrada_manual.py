"""
tests/test_entrada_manual.py

Valida o canal de entrada manual de empresas (v0.38).

Testa:
  1. avaliacao_manual: empresa avaliada, score e plano gerados, sem injeção
  2. injetar_no_fluxo: empresa avaliada + injetada na fila_execucao_comercial
  3. venda_manual: negócio registrado → pipeline_comercial + pipeline_entrega
  4. Deduplição: segunda submissão do mesmo nome é bloqueada
  5. Normalização: campos limpos corretamente
"""

import sys
import io
import json
import shutil
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from modulos.entrada_manual.processador_entrada_manual import (
    processar_entrada_manual,
    normalizar_entrada_manual,
    deduplicar_entrada_manual,
    carregar_todas_entradas_manuais,
    _ARQ_ENTRADAS,
    _ARQ_AVALIACOES,
    _ARQ_HISTORICO,
)

_ARQ_FILA    = config.PASTA_DADOS / "fila_execucao_comercial.json"
_ARQ_PIPELINE = config.PASTA_DADOS / "pipeline_comercial.json"
_ARQ_ENTREGA  = config.PASTA_DADOS / "pipeline_entrega.json"


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _limpar_estado_teste():
    """Remove arquivos de entrada manual para testes isolados."""
    for arq in [_ARQ_ENTRADAS, _ARQ_AVALIACOES, _ARQ_HISTORICO]:
        if arq.exists():
            arq.unlink()
    # Limpar entradas manuais da fila e pipelines (não apaga outros)
    for arq in [_ARQ_FILA, _ARQ_PIPELINE, _ARQ_ENTREGA]:
        if arq.exists():
            dados = json.loads(arq.read_text(encoding="utf-8"))
            filtrados = [d for d in dados if d.get("origem_oportunidade") != "manual_conselho"]
            arq.write_text(json.dumps(filtrados, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── Teste 1: avaliacao_manual ───────────────────────────────────────────────

def test_avaliacao_manual():
    print("\n=== Teste 1: Avaliação Manual ===")
    _limpar_estado_teste()

    resultado = processar_entrada_manual({
        "nome":      "Barbearia do Zé",
        "categoria": "barbearia",
        "cidade":    "São Paulo",
        "estado":    "SP",
        "telefone":  "11 99999-1234",
        "instagram": "@barbearia_ze",
        "modo":      "avaliacao_manual",
        "observacoes": "indicação do conselho",
    })

    check(resultado["status"] == "ok", "status=ok")
    check(resultado["injetado"] is False, "não injetado na fila (modo avaliacao)")

    entrada = resultado["entrada"]
    check(bool(entrada.get("id")), "entrada tem id")
    check(entrada["nome"] == "Barbearia do Zé", "nome preservado")
    check(entrada["status"] == "avaliado", "status=avaliado")
    check(entrada["modo"] == "avaliacao_manual", "modo correto")

    aval = resultado["avaliacao"]
    check(aval["score_presenca"] > 0, f"score_presenca > 0 (got {aval['score_presenca']})")
    check(aval["prioridade_abordagem"] in ("alta", "media", "baixa"), "prioridade válida")
    check(bool(aval.get("oferta_principal_comercial")), "oferta gerada")
    print(f"    Score presença: {aval['score_presenca']} | Prioridade: {aval['prioridade_abordagem']}")
    print(f"    Oferta: {aval['oferta_principal_comercial'][:60]}")

    # Não deve ter injetado na fila
    fila = json.loads(_ARQ_FILA.read_text(encoding="utf-8")) if _ARQ_FILA.exists() else []
    injetados_manuais = [f for f in fila if f.get("origem_oportunidade") == "manual_conselho"]
    check(len(injetados_manuais) == 0, "não injetado na fila_execucao_comercial")

    # Histórico deve ter o evento
    historico = json.loads(_ARQ_HISTORICO.read_text(encoding="utf-8")) if _ARQ_HISTORICO.exists() else []
    check(any(h["evento"] == "entrada_registrada" for h in historico), "historico: entrada_registrada")
    print(f"    Histórico: {[h['evento'] for h in historico]}")


# ─── Teste 2: injetar_no_fluxo ───────────────────────────────────────────────

def test_injetar_no_fluxo():
    print("\n=== Teste 2: Injetar no Fluxo Comercial ===")
    _limpar_estado_teste()

    resultado = processar_entrada_manual({
        "nome":      "Restaurante Sabor Caseiro",
        "categoria": "restaurante",
        "cidade":    "Campinas",
        "estado":    "SP",
        "telefone":  "19 3333-5678",
        "whatsapp":  "+5519933335678",
        "email":     "contato@saborcaseiro.com.br",
        "modo":      "injetar_no_fluxo",
    })

    check(resultado["status"] == "ok", "status=ok")
    check(resultado["injetado"] is True, "injetado=True")
    check("registro_fila" in resultado, "registro_fila presente no resultado")

    reg = resultado["registro_fila"]
    check(reg["origem_oportunidade"] == "manual_conselho", "origem=manual_conselho")
    check(reg["nome"] == "Restaurante Sabor Caseiro", "nome correto na fila")
    print(f"    Injetado: id={reg['id']} | prioridade={reg['nivel_prioridade_comercial']}")
    print(f"    Canal: {reg['canal_abordagem_sugerido']} | Contato: {reg['contato_principal']}")

    # Verificar que está no arquivo de fila
    fila = json.loads(_ARQ_FILA.read_text(encoding="utf-8")) if _ARQ_FILA.exists() else []
    no_arquivo = [f for f in fila if f.get("id") == reg["id"]]
    check(len(no_arquivo) == 1, "registro presente no arquivo fila_execucao_comercial.json")

    # Histórico: injetado_comercial
    historico = json.loads(_ARQ_HISTORICO.read_text(encoding="utf-8")) if _ARQ_HISTORICO.exists() else []
    check(any(h["evento"] == "injetado_comercial" for h in historico), "historico: injetado_comercial")


# ─── Teste 3: venda_manual ───────────────────────────────────────────────────

def test_venda_manual():
    print("\n=== Teste 3: Venda Manual ===")
    _limpar_estado_teste()

    resultado = processar_entrada_manual({
        "nome":             "Oficina Mecânica Irmãos Costa",
        "categoria":        "oficina mecânica",
        "cidade":           "São Bernardo do Campo",
        "estado":           "SP",
        "telefone":         "11 4444-9999",
        "whatsapp":         "+5511944449999",
        "site":             "https://irmaoscosta.com.br",
        "modo":             "venda_manual",
        "servico_vendido":  "site + botão WhatsApp",
        "valor_venda":      "1500",
        "observacoes":      "fechado presencialmente pelo fundador",
    })

    check(resultado["status"] == "ok", "status=ok")
    check(resultado["entrega"] is not None, "entrega criada")

    entrega_resultado = resultado["entrega"]
    opp     = entrega_resultado["oportunidade"]
    entrega = entrega_resultado["entrega"]

    check(opp["estagio"] == "ganho", "oportunidade com estagio=ganho")
    check(opp["origem_oportunidade"] == "manual_conselho", "origem=manual_conselho")
    check(opp["valor_estimado"] == 1500.0, f"valor_estimado=1500 (got {opp['valor_estimado']})")
    print(f"    Oportunidade: {opp['id']} | estagio={opp['estagio']} | valor={opp['valor_estimado']}")

    check(bool(entrega["id"]), "entrega tem id")
    check(entrega["status_entrega"] == "nova", "status_entrega=nova")
    check(entrega["linha_servico"] in ("marketing_presenca_digital", "automacao_atendimento"), "linha_servico válida")
    print(f"    Entrega: {entrega['id']} | linha={entrega['linha_servico']} | status={entrega['status_entrega']}")

    # Verificar arquivos
    pipeline_c = json.loads(_ARQ_PIPELINE.read_text(encoding="utf-8")) if _ARQ_PIPELINE.exists() else []
    opp_no_arq = [o for o in pipeline_c if o.get("id") == opp["id"]]
    check(len(opp_no_arq) == 1, "oportunidade no pipeline_comercial.json")

    pipeline_e = json.loads(_ARQ_ENTREGA.read_text(encoding="utf-8")) if _ARQ_ENTREGA.exists() else []
    ent_no_arq = [e for e in pipeline_e if e.get("id") == entrega["id"]]
    check(len(ent_no_arq) == 1, "entrega no pipeline_entrega.json")

    # Histórico: venda_registrada
    historico = json.loads(_ARQ_HISTORICO.read_text(encoding="utf-8")) if _ARQ_HISTORICO.exists() else []
    check(any(h["evento"] == "venda_registrada" for h in historico), "historico: venda_registrada")


# ─── Teste 4: Deduplição ─────────────────────────────────────────────────────

def test_deduplicacao():
    print("\n=== Teste 4: Deduplição ===")
    _limpar_estado_teste()

    dados_base = {
        "nome":     "Padaria Pão de Ouro",
        "telefone": "11 98765-4321",
        "cidade":   "São Paulo",
        "modo":     "avaliacao_manual",
    }

    # Primeira inserção: deve funcionar
    r1 = processar_entrada_manual(dados_base)
    check(r1["status"] == "ok", "primeira inserção ok")
    print(f"    Primeira: {r1['status']} | id={r1['entrada']['id']}")

    # Segunda inserção com mesmo nome: deve detectar duplicata
    r2 = processar_entrada_manual(dados_base)
    check(r2["status"] == "duplicata", f"segunda inserção = duplicata (got {r2['status']})")
    check("duplicata" in r2, "campo duplicata presente")
    print(f"    Segunda: {r2['status']} | ref={r2['duplicata'].get('nome','?')}")

    # Com forcar_insercao: deve permitir
    dados_forcado = dict(dados_base, forcar_insercao=True)
    r3 = processar_entrada_manual(dados_forcado)
    check(r3["status"] == "ok", "forcar_insercao=True permite inserção")
    print(f"    Forçada: {r3['status']} | id={r3['entrada']['id']}")

    # Dedup por telefone igual mas nome diferente
    dados_tel_igual = {"nome": "Outra Empresa", "telefone": "11 98765-4321", "modo": "avaliacao_manual"}
    r4 = processar_entrada_manual(dados_tel_igual)
    check(r4["status"] == "duplicata", "dedup por telefone igual detectado")
    print(f"    Dedup telefone: {r4['status']}")


# ─── Teste 5: Normalização ───────────────────────────────────────────────────

def test_normalizacao():
    print("\n=== Teste 5: Normalização de Campos ===")

    # Instagram com @
    e = normalizar_entrada_manual({"instagram": "@minha_empresa", "nome": "X", "modo": "avaliacao_manual"})
    check(e["instagram"] == "minha_empresa", f"instagram sem @ (got {e['instagram']})")

    # Instagram com URL completa
    e2 = normalizar_entrada_manual({"instagram": "https://www.instagram.com/barbearia_top/", "nome": "X", "modo": "avaliacao_manual"})
    check(e2["instagram"] == "barbearia_top", f"instagram URL → handle (got {e2['instagram']})")

    # Site sem schema → https://
    e3 = normalizar_entrada_manual({"site": "meunegocio.com.br", "nome": "X", "modo": "avaliacao_manual"})
    check(e3["site"] == "https://meunegocio.com.br", f"site com schema (got {e3['site']})")

    # Telefone só dígitos (fixo 10 dígitos — DDD + 8 dígitos)
    e4 = normalizar_entrada_manual({"telefone": "(17) 3333-5678", "nome": "X", "modo": "avaliacao_manual"})
    check(e4["telefone"] == "1733335678", f"telefone só dígitos (got {e4['telefone']})")

    # Nome all-caps → title case
    e5 = normalizar_entrada_manual({"nome": "BARBEARIA DO ZÉ", "modo": "avaliacao_manual"})
    check(e5["nome"] == "Barbearia Do Zé", f"nome title case (got {e5['nome']})")

    # Email lowercase
    e6 = normalizar_entrada_manual({"email": "Contato@Empresa.COM", "nome": "X", "modo": "avaliacao_manual"})
    check(e6["email"] == "contato@empresa.com", f"email lowercase (got {e6['email']})")

    # Estado uppercase
    e7 = normalizar_entrada_manual({"estado": "sp", "nome": "X", "modo": "avaliacao_manual"})
    check(e7["estado"] == "SP", f"estado uppercase (got {e7['estado']})")

    # Modo inválido → avaliacao_manual
    e8 = normalizar_entrada_manual({"modo": "modo_inexistente", "nome": "X"})
    check(e8["modo"] == "avaliacao_manual", f"modo inválido → avaliacao_manual (got {e8['modo']})")

    print("    Todos os campos normalizados corretamente.")


# ─── Runner ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    testes = [
        test_normalizacao,
        test_avaliacao_manual,
        test_injetar_no_fluxo,
        test_venda_manual,
        test_deduplicacao,
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
        finally:
            _limpar_estado_teste()

    print("\n" + "=" * 60)
    print(f"Resultado: {len(testes)-len(falhos)}/{len(testes)} testes passaram")
    if falhos:
        print("Falhos:")
        for f in falhos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM")
