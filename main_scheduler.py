"""
main_scheduler.py — Loop contínuo de execução dos agentes da Vetor.

Uso:
  python main_scheduler.py                    # loop contínuo (Ctrl+C para parar)
  python main_scheduler.py --dry-run          # mostra agenda do dia, não executa
  python main_scheduler.py --once             # executa agentes devidos agora e sai
  python main_scheduler.py --agente comercial # força execução de um agente específico

Agenda configurada em config.py → AGENDA_AGENTES.
Governança respeitada via dados/estado_governanca_conselho.json.
Log em dados/scheduler_log.json.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.scheduler import Scheduler


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scheduler de agentes da Vetor",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra a agenda do dia sem executar nenhum agente",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Executa os agentes devidos agora e encerra",
    )
    parser.add_argument(
        "--agente",
        metavar="NOME",
        help="Força execução de um agente específico (ex: comercial, secretario)",
    )

    args = parser.parse_args()
    scheduler = Scheduler()

    if args.agente:
        resultado = scheduler.executar_agente(args.agente)
        if resultado["sucesso"]:
            print(f"[Scheduler] {args.agente} finalizado em {resultado['duracao_ms']}ms")
        else:
            print(f"[Scheduler] {args.agente} falhou: {resultado['erro']}")
            sys.exit(1)
        return

    scheduler.run(dry_run=args.dry_run, once=args.once)


if __name__ == "__main__":
    main()
