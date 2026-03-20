"""
tests/test_historico.py — Testa a camada de memória e histórico de prospecção.

Roda com: python tests/test_historico.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modulos.prospeccao_operacional.historico import (
    gerar_empresa_id,
    atualizar_historico,
    gerar_fila_revisao,
    gerar_resumo_execucao,
)

TIMESTAMP_1 = "2026-03-20T10:00:00"
TIMESTAMP_2 = "2026-03-21T10:00:00"


def _empresa(
    osm_id=None,
    nome="Empresa Teste",
    categoria_id="barbearia",
    classificacao="semi_digital_prioritaria",
    prioridade="alta",
    abordavel=True,
    canal="telefone",
    contato="+55 17 9999-9999",
    score_presenca=50,
    score_prontidao=55,
):
    return {
        "osm_id": osm_id,
        "nome": nome,
        "categoria_id": categoria_id,
        "categoria_nome": "Barbearia",
        "classificacao_comercial": classificacao,
        "prioridade_abordagem": prioridade,
        "abordavel_agora": abordavel,
        "canal_abordagem_sugerido": canal,
        "contato_principal": contato,
        "score_presenca_digital": score_presenca,
        "score_prontidao_ia": score_prontidao,
    }


# ---------------------------------------------------------------------------
# gerar_empresa_id
# ---------------------------------------------------------------------------


def test_id_com_osm_id():
    """ID com osm_id deve usar prefixo 'osm_'."""
    e = _empresa(osm_id=123456)
    assert gerar_empresa_id(e) == "osm_123456"
    print("OK: ID com osm_id usa prefixo osm_")


def test_id_sem_osm_id_estavel():
    """ID sem osm_id deve ser hash estável (mesma entrada = mesmo ID)."""
    e = _empresa(nome="Barbearia Teste", categoria_id="barbearia")
    id1 = gerar_empresa_id(e)
    id2 = gerar_empresa_id(e)
    assert id1 == id2
    assert id1.startswith("hash_")
    print("OK: ID sem osm_id e estavel (hash)")


def test_id_diferente_para_empresas_diferentes():
    """Duas empresas diferentes devem ter IDs diferentes."""
    e1 = _empresa(osm_id=111)
    e2 = _empresa(osm_id=222)
    assert gerar_empresa_id(e1) != gerar_empresa_id(e2)
    print("OK: IDs diferentes para empresas diferentes")


# ---------------------------------------------------------------------------
# atualizar_historico — primeira execução
# ---------------------------------------------------------------------------


def test_primeira_execucao_gera_novos():
    """Na primeira execução (histórico vazio), todas as empresas devem ter status 'novo'."""
    empresas = [_empresa(osm_id=1), _empresa(osm_id=2, nome="Oficina B")]
    historico, mudancas, stats = atualizar_historico({}, empresas, TIMESTAMP_1)

    assert len(historico) == 2
    for entrada in historico.values():
        assert entrada["status_interno"] == "novo"
        assert entrada["vezes_encontrada"] == 1
        assert entrada["primeira_vez_encontrada"] == TIMESTAMP_1
    print("OK: primeira execucao gera status 'novo' para todas")


def test_primeira_execucao_detecta_mudanca_nova_empresa():
    """Cada empresa nova deve gerar uma mudança do tipo 'nova_empresa'."""
    empresas = [_empresa(osm_id=1), _empresa(osm_id=2)]
    _, mudancas, _ = atualizar_historico({}, empresas, TIMESTAMP_1)

    tipos = [m["tipo"] for m in mudancas]
    assert tipos.count("nova_empresa") == 2
    print("OK: mudancas do tipo 'nova_empresa' geradas na primeira execucao")


# ---------------------------------------------------------------------------
# atualizar_historico — segunda execução
# ---------------------------------------------------------------------------


def test_segunda_execucao_incrementa_vezes_encontrada():
    """Empresa vista duas vezes deve ter vezes_encontrada = 2."""
    empresas = [_empresa(osm_id=1)]
    historico, _, _ = atualizar_historico({}, empresas, TIMESTAMP_1)
    historico2, _, _ = atualizar_historico(historico, empresas, TIMESTAMP_2)

    entrada = historico2["osm_1"]
    assert entrada["vezes_encontrada"] == 2
    assert entrada["ultima_vez_encontrada"] == TIMESTAMP_2
    assert entrada["primeira_vez_encontrada"] == TIMESTAMP_1
    print("OK: segunda execucao incrementa vezes_encontrada")


def test_empresa_sem_mudanca_nao_eh_novo():
    """Empresa vista pela segunda vez sem mudança não deve ter status 'novo'."""
    empresas = [_empresa(osm_id=1)]
    historico, _, _ = atualizar_historico({}, empresas, TIMESTAMP_1)
    historico2, _, _ = atualizar_historico(historico, empresas, TIMESTAMP_2)

    assert historico2["osm_1"]["status_interno"] != "novo"
    print("OK: empresa na segunda execucao nao tem mais status 'novo'")


def test_empresa_pronta_para_abordagem():
    """Empresa abordável e priorizada (não nova) deve ser 'pronto_para_abordagem'."""
    e = _empresa(osm_id=1, abordavel=True, classificacao="semi_digital_prioritaria")
    historico, _, _ = atualizar_historico({}, [e], TIMESTAMP_1)
    historico2, _, _ = atualizar_historico(historico, [e], TIMESTAMP_2)

    assert historico2["osm_1"]["status_interno"] == "pronto_para_abordagem"
    print("OK: empresa abordavel e priorizada vira 'pronto_para_abordagem'")


# ---------------------------------------------------------------------------
# Detecção de mudanças
# ---------------------------------------------------------------------------


def test_detecta_mudanca_de_classificacao():
    """Mudança de classificação entre execuções deve ser detectada."""
    e1 = _empresa(osm_id=5, classificacao="analogica", prioridade="media")
    historico, _, _ = atualizar_historico({}, [e1], TIMESTAMP_1)

    e2 = _empresa(osm_id=5, classificacao="semi_digital_prioritaria", prioridade="alta")
    historico2, mudancas, _ = atualizar_historico(historico, [e2], TIMESTAMP_2)

    tipos = [m["tipo"] for m in mudancas]
    assert "classificacao_mudou" in tipos
    print("OK: mudanca de classificacao detectada")


def test_detecta_ganho_de_contato():
    """Empresa que ganhou contato deve ter mudança 'ganhou_contato'."""
    e1 = _empresa(osm_id=6, abordavel=False, canal="sem_canal_identificado", contato=None)
    historico, _, _ = atualizar_historico({}, [e1], TIMESTAMP_1)

    e2 = _empresa(osm_id=6, abordavel=True, canal="telefone", contato="+55 17 9999-9999")
    _, mudancas, _ = atualizar_historico(historico, [e2], TIMESTAMP_2)

    tipos = [m["tipo"] for m in mudancas]
    assert "ganhou_contato" in tipos
    print("OK: ganho de contato detectado")


def test_detecta_perda_de_contato():
    """Empresa que perdeu contato deve ter mudança 'perdeu_contato'."""
    e1 = _empresa(osm_id=7, abordavel=True, canal="telefone")
    historico, _, _ = atualizar_historico({}, [e1], TIMESTAMP_1)

    e2 = _empresa(osm_id=7, abordavel=False, canal="sem_canal_identificado", contato=None)
    _, mudancas, _ = atualizar_historico(historico, [e2], TIMESTAMP_2)

    tipos = [m["tipo"] for m in mudancas]
    assert "perdeu_contato" in tipos
    print("OK: perda de contato detectada")


def test_detecta_empresa_que_sumiu():
    """Empresa que estava no histórico e não foi encontrada deve gerar 'empresa_sumiu'."""
    e = _empresa(osm_id=8, classificacao="semi_digital_prioritaria")
    historico, _, _ = atualizar_historico({}, [e], TIMESTAMP_1)

    # Segunda execução sem esta empresa
    _, mudancas, _ = atualizar_historico(historico, [], TIMESTAMP_2)

    tipos = [m["tipo"] for m in mudancas]
    assert "empresa_sumiu" in tipos
    print("OK: empresa que sumiu detectada")


def test_empresa_sumida_vira_revisar():
    """Empresa não encontrada na execução atual deve ter status 'revisar'."""
    e = _empresa(osm_id=9, classificacao="semi_digital_prioritaria")
    historico, _, _ = atualizar_historico({}, [e], TIMESTAMP_1)
    historico2, _, _ = atualizar_historico(historico, [], TIMESTAMP_2)

    assert historico2["osm_9"]["status_interno"] == "revisar"
    assert historico2["osm_9"]["encontrada_execucao_atual"] is False
    print("OK: empresa sumida tem status 'revisar'")


def test_pouco_util_vira_descartar():
    """Empresa com classificação pouco_util (não nova) deve ter status 'descartar'."""
    e = _empresa(osm_id=10, classificacao="pouco_util", prioridade="nula", abordavel=False, canal="sem_canal_identificado", contato=None)
    historico, _, _ = atualizar_historico({}, [e], TIMESTAMP_1)
    historico2, _, _ = atualizar_historico(historico, [e], TIMESTAMP_2)

    assert historico2["osm_10"]["status_interno"] == "descartar"
    print("OK: pouco_util vira 'descartar' na segunda execucao")


# ---------------------------------------------------------------------------
# Fila de revisão
# ---------------------------------------------------------------------------


def test_fila_inclui_pronto_para_abordagem():
    """Leads prontos para abordagem devem estar na fila."""
    e = _empresa(osm_id=11, abordavel=True, classificacao="semi_digital_prioritaria")
    historico, _, _ = atualizar_historico({}, [e], TIMESTAMP_1)
    historico2, _, _ = atualizar_historico(historico, [e], TIMESTAMP_2)

    fila = gerar_fila_revisao(historico2)
    ids_fila = [f["empresa_id"] for f in fila]
    assert "osm_11" in ids_fila
    print("OK: pronto_para_abordagem esta na fila de revisao")


def test_fila_inclui_novos_bons():
    """Leads novos com boa classificação devem estar na fila."""
    e = _empresa(osm_id=12, classificacao="semi_digital_prioritaria")
    historico, _, _ = atualizar_historico({}, [e], TIMESTAMP_1)

    fila = gerar_fila_revisao(historico)
    ids_fila = [f["empresa_id"] for f in fila]
    assert "osm_12" in ids_fila
    print("OK: novo lead bom esta na fila de revisao")


def test_fila_exclui_baixa_prioridade():
    """Leads de baixa prioridade não devem aparecer na fila de revisão."""
    e = _empresa(osm_id=13, classificacao="digital_basica", prioridade="baixa", abordavel=False, canal="sem_canal_identificado", contato=None)
    historico, _, _ = atualizar_historico({}, [e], TIMESTAMP_1)
    historico2, _, _ = atualizar_historico(historico, [e], TIMESTAMP_2)

    fila = gerar_fila_revisao(historico2)
    ids_fila = [f["empresa_id"] for f in fila]
    assert "osm_13" not in ids_fila
    print("OK: baixa_prioridade excluido da fila de revisao")


def test_fila_ordenada_por_relevancia():
    """Fila deve colocar pronto_para_abordagem antes de revisar."""
    e_pronto = _empresa(osm_id=20, abordavel=True, classificacao="semi_digital_prioritaria")
    e_revisar = _empresa(osm_id=21, abordavel=False, classificacao="analogica", canal="sem_canal_identificado", contato=None)

    historico, _, _ = atualizar_historico({}, [e_pronto, e_revisar], TIMESTAMP_1)
    historico2, _, _ = atualizar_historico(historico, [e_pronto, e_revisar], TIMESTAMP_2)
    # forçar mudança em e_revisar para ele virar 'revisar'
    historico2["osm_21"]["status_interno"] = "revisar"

    fila = gerar_fila_revisao(historico2)
    status_ordenados = [f["status_interno"] for f in fila]
    idx_pronto = status_ordenados.index("pronto_para_abordagem") if "pronto_para_abordagem" in status_ordenados else 999
    idx_revisar = status_ordenados.index("revisar") if "revisar" in status_ordenados else 999
    assert idx_pronto < idx_revisar
    print("OK: pronto_para_abordagem aparece antes de revisar na fila")


# ---------------------------------------------------------------------------
# Resumo de execução
# ---------------------------------------------------------------------------


def test_resumo_conta_empresas_novas():
    """Resumo deve contar corretamente empresas novas."""
    empresas = [_empresa(osm_id=30), _empresa(osm_id=31, nome="Padaria X")]
    historico, mudancas, stats = atualizar_historico({}, empresas, TIMESTAMP_1)
    resumo = gerar_resumo_execucao({}, historico, mudancas, stats, TIMESTAMP_1)

    assert resumo["empresas_novas_nesta_execucao"] == 2
    assert resumo["total_no_historico"] == 2
    print("OK: resumo conta empresas novas corretamente")


def test_resumo_tem_contagem_por_status():
    """Resumo deve ter contagem por status interno."""
    empresas = [_empresa(osm_id=40)]
    historico, mudancas, stats = atualizar_historico({}, empresas, TIMESTAMP_1)
    resumo = gerar_resumo_execucao({}, historico, mudancas, stats, TIMESTAMP_1)

    assert "contagem_por_status_interno" in resumo
    assert resumo["contagem_por_status_interno"].get("novo", 0) >= 1
    print("OK: resumo tem contagem por status interno")


if __name__ == "__main__":
    test_id_com_osm_id()
    test_id_sem_osm_id_estavel()
    test_id_diferente_para_empresas_diferentes()
    test_primeira_execucao_gera_novos()
    test_primeira_execucao_detecta_mudanca_nova_empresa()
    test_segunda_execucao_incrementa_vezes_encontrada()
    test_empresa_sem_mudanca_nao_eh_novo()
    test_empresa_pronta_para_abordagem()
    test_detecta_mudanca_de_classificacao()
    test_detecta_ganho_de_contato()
    test_detecta_perda_de_contato()
    test_detecta_empresa_que_sumiu()
    test_empresa_sumida_vira_revisar()
    test_pouco_util_vira_descartar()
    test_fila_inclui_pronto_para_abordagem()
    test_fila_inclui_novos_bons()
    test_fila_exclui_baixa_prioridade()
    test_fila_ordenada_por_relevancia()
    test_resumo_conta_empresas_novas()
    test_resumo_tem_contagem_por_status()
    print("\nTodos os testes de historico passaram.")
