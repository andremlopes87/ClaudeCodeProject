"""
main_marketing.py — Linha de marketing: análise de presença digital em escala nacional.

Como usar:
    python main_marketing.py

Cidades e nichos configurados em config.py (seção MARKETING).
Não inclui abordagem, histórico nem envio de mensagens.
"""

from core.executor_marketing import executar_marketing

if __name__ == "__main__":
    executar_marketing()
