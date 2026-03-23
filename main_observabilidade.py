"""
main_observabilidade.py — Gera os arquivos de observabilidade sem rodar o ciclo.

Util para atualizar o painel sem precisar executar todos os agentes.

Uso:
  python main_observabilidade.py
"""

import config
from core.observabilidade_empresa import executar_observabilidade


def main():
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    resultado = executar_observabilidade()

    print("\n" + "=" * 56)
    print("OBSERVABILIDADE — CONSOLIDACAO CONCLUIDA")
    print("=" * 56)
    print(f"  Arquivos gerados : {resultado['arquivos_gerados']}")
    print(f"  Eventos no feed  : {resultado['eventos_feed']}")
    print(f"  Atualizado em    : {resultado['atualizado_em']}")
    print("---")
    print("ARQUIVOS:")
    pasta = config.PASTA_DADOS
    for nome in ["painel_conselho.json", "feed_eventos_empresa.json",
                 "metricas_empresa.json", "metricas_agentes.json", "metricas_areas.json"]:
        arq = pasta / nome
        tam = arq.stat().st_size if arq.exists() else 0
        print(f"  {arq}  ({tam:,} bytes)")
    print("=" * 56)


if __name__ == "__main__":
    main()
