"""
main.py — Ponto de entrada do sistema de prospecção.

Como usar:
    python main.py

O fluxo completo será executado automaticamente:
busca → análise → diagnóstico → salvamento → resumo no terminal
"""

from core.executor import executar

if __name__ == "__main__":
    executar()
