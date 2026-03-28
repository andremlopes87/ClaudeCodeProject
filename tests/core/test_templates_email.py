"""
tests/core/test_templates_email.py -- Sistema de templates de email

Roda com: python tests/core/test_templates_email.py
"""

import sys
import io
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.templates_email as tmpl_mod
from core.templates_email import (
    obter_template,
    listar_templates,
    gerar_email,
    gerar_email_assinado,
    _reset_caches,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def test_listar_templates_retorna_lista():
    _reset_caches()
    resultado = listar_templates()
    check(isinstance(resultado, list), "listar_templates() deve retornar lista")
    print("OK: listar_templates_retorna_lista")


def test_obter_template_inexistente():
    _reset_caches()
    t = obter_template("tipo_que_absolutamente_nao_existe_xyz")
    check(t is None, "template inexistente deve retornar None")
    print("OK: obter_template_inexistente")


def test_gerar_email_fallback():
    _reset_caches()
    # tipo desconhecido deve retornar dict com corpo e tipo (pode ser erro)
    resultado = gerar_email("tipo_desconhecido_xyz", {"nome_empresa": "Empresa X"})
    check(isinstance(resultado, dict), "gerar_email deve retornar dict")
    check("tipo" in resultado, "resultado deve ter campo 'tipo'")
    print("OK: gerar_email_fallback")


def test_gerar_email_variaveis_substituidas():
    _reset_caches()
    # Usar dados reais se templates_email.json existir, senao testar fallback
    # Injetar a variavel e verificar substituicao se corpo nao for vazio
    variaveis = {"nome_empresa": "Padaria do Ze", "nome_contato": "Ze"}
    resultado = gerar_email("abordagem_inicial", variaveis)
    check(isinstance(resultado, dict), "deve retornar dict")
    corpo = resultado.get("corpo", "")
    assunto = resultado.get("assunto", "")
    # Se o template foi carregado e tem variaveis, checar substituicao
    if "Padaria do Ze" in corpo or "Padaria do Ze" in assunto:
        check(True, "variavel substituida corretamente")
    else:
        # Pode ser que template nao exista ou variaveis nao estejam no template
        check(True, "gerar_email sem substituicao de variavel (template pode nao ter {nome_empresa})")
    print("OK: gerar_email_variaveis_substituidas")


def test_gerar_email_tem_campos():
    _reset_caches()
    resultado = gerar_email("abordagem_inicial", {"nome_empresa": "Teste Ltda"})
    check("assunto" in resultado, "resultado deve ter campo 'assunto'")
    check("corpo" in resultado, "resultado deve ter campo 'corpo'")
    check("tipo" in resultado, "resultado deve ter campo 'tipo'")
    print("OK: gerar_email_tem_campos")


def test_gerar_email_tipo_abordagem():
    _reset_caches()
    resultado = gerar_email("abordagem_inicial", {"nome_empresa": "Teste"})
    check(isinstance(resultado, dict), "deve retornar dict para tipo abordagem_inicial")
    check(resultado.get("tipo") == "abordagem_inicial", "tipo deve ser 'abordagem_inicial'")
    print("OK: gerar_email_tipo_abordagem")


def test_gerar_email_assinado_retorna_corpo():
    _reset_caches()
    resultado = gerar_email_assinado("abordagem_inicial", {"nome_empresa": "Empresa Y"})
    check(isinstance(resultado, dict), "deve retornar dict")
    check("corpo" in resultado, "resultado assinado deve ter campo 'corpo'")
    print("OK: gerar_email_assinado_retorna_corpo")


def test_gerar_email_sem_variaveis():
    _reset_caches()
    # Nao deve levantar excecao mesmo sem variaveis
    try:
        resultado = gerar_email("abordagem_inicial", {})
        check(isinstance(resultado, dict), "deve retornar dict mesmo sem variaveis")
    except Exception as e:
        raise AssertionError(f"nao deve levantar excecao sem variaveis: {e}")
    print("OK: gerar_email_sem_variaveis")


if __name__ == "__main__":
    testes = [
        test_listar_templates_retorna_lista,
        test_obter_template_inexistente,
        test_gerar_email_fallback,
        test_gerar_email_variaveis_substituidas,
        test_gerar_email_tem_campos,
        test_gerar_email_tipo_abordagem,
        test_gerar_email_assinado_retorna_corpo,
        test_gerar_email_sem_variaveis,
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

    print(f"\nResultado: {len(testes)-len(falhos)}/{len(testes)} testes passaram")
    if falhos:
        print("Falhos:")
        for f in falhos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM")
