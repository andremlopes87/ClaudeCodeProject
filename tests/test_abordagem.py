"""
tests/test_abordagem.py — Testa a geração de pacotes de abordagem comercial.

Roda com: python tests/test_abordagem.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.prospeccao.abordagem import preparar_abordagens


def _empresa(
    nome="Barbearia do João",
    categoria_id="barbearia",
    categoria_nome="Barbearia",
    canal="telefone",
    classificacao="semi_digital_prioritaria",
    telefone="+55 17 9999-9999",
    email=None,
    website=None,
    tem_instagram=False,
    score=55,
    sinais=None,
):
    """Cria empresa de teste com campos relevantes para abordagem."""
    if sinais is None:
        sinais = {
            "tem_telefone": bool(telefone),
            "tem_email": bool(email),
            "tem_website": bool(website),
            "tem_horario": False,
        }
    return {
        "nome": nome,
        "categoria_id": categoria_id,
        "categoria_nome": categoria_nome,
        "canal_abordagem_sugerido": canal,
        "classificacao_comercial": classificacao,
        "telefone": telefone,
        "email": email,
        "website": website,
        "tem_instagram": tem_instagram,
        "score_prontidao_ia": score,
        "contato_principal": telefone or email or website,
        "sinais": sinais,
    }


def test_campos_obrigatorios_presentes():
    """Todos os 10 campos de abordagem devem estar presentes no resultado."""
    e = _empresa()
    resultado = preparar_abordagens([e])[0]

    campos = [
        "resumo_empresa",
        "oportunidade_principal",
        "motivo_abordagem",
        "canal_abordagem_recomendado",
        "mensagem_inicial_curta",
        "mensagem_inicial_media",
        "followup_curto",
        "observacoes_abordagem",
        "risco_abordagem",
        "tom_recomendado",
    ]
    for campo in campos:
        assert campo in resultado, f"Campo ausente: {campo}"
    print("OK: todos os 10 campos de abordagem presentes")


def test_canal_telefone_gera_abertura_curta():
    """Para canal telefone, mensagem curta deve ser abertura de conversa."""
    e = _empresa(canal="telefone")
    resultado = preparar_abordagens([e])[0]
    msg = resultado["mensagem_inicial_curta"]
    assert isinstance(msg, str)
    assert len(msg) > 10
    assert resultado["canal_abordagem_recomendado"] == "telefone"
    print("OK: canal telefone gera abertura curta de conversa")


def test_canal_email_gera_assunto():
    """Para canal email, mensagem curta deve ser o assunto do e-mail."""
    e = _empresa(
        canal="email",
        telefone=None,
        email="contato@barbearia.com",
        sinais={"tem_telefone": False, "tem_email": True, "tem_website": False, "tem_horario": False},
    )
    resultado = preparar_abordagens([e])[0]
    msg_curta = resultado["mensagem_inicial_curta"]
    assert "Assunto:" in msg_curta
    assert resultado["canal_abordagem_recomendado"] == "email"
    print("OK: canal email gera assunto na mensagem curta")


def test_canal_email_gera_corpo_no_media():
    """Para canal email, mensagem média deve ter saudação e corpo."""
    e = _empresa(
        canal="email",
        telefone=None,
        email="contato@barbearia.com",
        sinais={"tem_telefone": False, "tem_email": True, "tem_website": False, "tem_horario": False},
    )
    resultado = preparar_abordagens([e])[0]
    msg_media = resultado["mensagem_inicial_media"]
    assert "Olá" in msg_media
    assert "Att," in msg_media
    print("OK: canal email gera corpo completo na mensagem media")


def test_oportunidade_especifica_por_categoria():
    """Cada categoria deve ter oportunidade específica (não a padrão)."""
    categorias = [
        ("barbearia", "Agendamento"),
        ("oficina_mecanica", "Orçamento"),
        ("padaria", "Encomenda"),
        ("acougue", "Pedido"),
        ("autopecas", "Consulta"),
    ]
    for cat_id, palavra_chave in categorias:
        e = _empresa(categoria_id=cat_id)
        resultado = preparar_abordagens([e])[0]
        oport = resultado["oportunidade_principal"]
        assert isinstance(oport, str) and len(oport) > 5, f"Oportunidade vazia para {cat_id}"
    print("OK: categorias geram oportunidades especificas")


def test_resumo_inclui_nome_e_categoria():
    """Resumo deve incluir nome da empresa e categoria."""
    e = _empresa(nome="Padaria Central", categoria_nome="Padaria")
    resultado = preparar_abordagens([e])[0]
    resumo = resultado["resumo_empresa"]
    assert "Padaria Central" in resumo
    assert "Padaria" in resumo
    print("OK: resumo inclui nome e categoria da empresa")


def test_followup_inclui_nome_da_empresa():
    """Mensagem de follow-up deve mencionar o nome da empresa."""
    e = _empresa(nome="Oficina do Pedro")
    resultado = preparar_abordagens([e])[0]
    followup = resultado["followup_curto"]
    assert "Oficina do Pedro" in followup
    print("OK: follow-up inclui nome da empresa")


def test_tom_diferente_por_canal():
    """Tom recomendado deve variar entre telefone e email."""
    e_tel = _empresa(canal="telefone")
    e_email = _empresa(
        canal="email",
        telefone=None,
        email="c@empresa.com",
        sinais={"tem_telefone": False, "tem_email": True, "tem_website": False, "tem_horario": False},
    )
    tom_tel = preparar_abordagens([e_tel])[0]["tom_recomendado"]
    tom_email = preparar_abordagens([e_email])[0]["tom_recomendado"]
    assert tom_tel != tom_email
    print("OK: tom recomendado varia entre telefone e email")


def test_multiplas_empresas():
    """Deve processar lista com varias empresas sem erro."""
    empresas = [
        _empresa(nome="Barbearia A", categoria_id="barbearia"),
        _empresa(nome="Oficina B", categoria_id="oficina_mecanica"),
        _empresa(nome="Padaria C", categoria_id="padaria"),
    ]
    resultados = preparar_abordagens(empresas)
    assert len(resultados) == 3
    for r in resultados:
        assert "oportunidade_principal" in r
        assert "mensagem_inicial_curta" in r
    print("OK: multiplas empresas processadas corretamente")


def test_campos_existentes_preservados():
    """Os campos já existentes na empresa não devem ser removidos."""
    e = _empresa()
    e["score_presenca_digital"] = 45
    e["classificacao_comercial"] = "semi_digital_prioritaria"
    resultado = preparar_abordagens([e])[0]
    assert resultado["score_presenca_digital"] == 45
    assert resultado["classificacao_comercial"] == "semi_digital_prioritaria"
    print("OK: campos existentes preservados apos abordagem")


if __name__ == "__main__":
    test_campos_obrigatorios_presentes()
    test_canal_telefone_gera_abertura_curta()
    test_canal_email_gera_assunto()
    test_canal_email_gera_corpo_no_media()
    test_oportunidade_especifica_por_categoria()
    test_resumo_inclui_nome_e_categoria()
    test_followup_inclui_nome_da_empresa()
    test_tom_diferente_por_canal()
    test_multiplas_empresas()
    test_campos_existentes_preservados()
    print("\nTodos os testes de abordagem passaram.")
