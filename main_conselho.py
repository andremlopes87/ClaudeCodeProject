"""
main_conselho.py — Inicia o Painel do Conselho localmente.

Uso:
  python main_conselho.py
  python main_conselho.py --port 8080

Acesso:
  http://localhost:8000
"""

import sys

def main():
    port = 8000
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    try:
        import uvicorn
    except ImportError:
        print("Erro: uvicorn nao instalado.")
        print("Execute: pip install fastapi uvicorn jinja2")
        sys.exit(1)

    print("=" * 56)
    print("PAINEL DO CONSELHO")
    print("=" * 56)
    print(f"  URL: http://localhost:{port}")
    print(f"  Dados: dados/painel_conselho.json")
    print(f"  Refresh automatico: a cada 15s")
    print("=" * 56)
    print()

    uvicorn.run(
        "conselho_app.app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
