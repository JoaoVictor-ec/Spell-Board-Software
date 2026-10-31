import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Diretório raiz (Spell_nodes)
BASE_DIR = Path(__file__).parent.resolve()

# Pasta para armazenar os logs de cada nó
LOGS_DIR = Path("/tmp/chess_logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Mapeamento dos nós agrupados pelas suas pastas
NODES = [
    ("Orquestrador (State Machine)", "control/state_machine.py"),
    ("Verificador de Regras", "chess/verifier.py"),
    ("Engine Stockfish", "chess/engine_stockfish.py"),  
    ("Serial / Simulação do Robô", "control/serial_node.py"),
    ("Nó Whisper STT", "stt/whisper_node.py"),
    ("Nó Áudio / DeepFilter", "stt/deepfilter.py"),
]

# Nó de interface visual que roda no terminal ativo
VISUALIZER_NODE = ("Visualizador de Tabuleiro", "chess/board_visualizer_node.py")

processes = []


def stop_all_nodes(sig, frame):
    print("\n\n[LAUNCHER] Encerrando todos os nós do ecossistema...")
    for name, proc, log_file in reversed(processes):
        print(f"[LAUNCHER] Parando {name} (PID: {proc.pid})...")
        proc.terminate()
        log_file.close()

    print("[LAUNCHER] Todos os nós foram desligados com sucesso!")
    sys.exit(0)


# Registra os sinais de interrupção (Ctrl+C ou finalização do sistema)
signal.signal(signal.SIGINT, stop_all_nodes)
signal.signal(signal.SIGTERM, stop_all_nodes)


def main():
    print("=" * 65)
    print("   ECOSSISTEMA DE XADREZ AUTÔNOMO - INICIALIZANDO NÓS   ")
    print(f"   Diretório Raiz: {BASE_DIR}")
    print("=" * 65)

    # 1. Inicia os nós em background
    for name, relative_script_path in NODES:
        script_full_path = BASE_DIR / relative_script_path

        # Caso o arquivo tenha outro nome na pasta, evita quebrar o script sem aviso
        if not script_full_path.exists():
            print(
                f"[ERRO LAUNCHER] Arquivo não encontrado: {relative_script_path}"
            )
            continue

        log_filename = (
            f"{Path(relative_script_path).stem}.log"  # ex: state_machine.log
        )
        log_file = open(LOGS_DIR / log_filename, "w")

        print(
            f"[LAUNCHER] Subindo {name:<30} -> Logs: /tmp/chess_logs/{log_filename}"
        )

        # Executa no ambiente Python ativo usando a raiz como diretório de trabalho (cwd)
        proc = subprocess.Popen(
            [sys.executable, "-u", str(script_full_path)],
            stdout=log_file,
            stderr=log_file,
            cwd=str(BASE_DIR),
        )
        processes.append((name, proc, log_file))

        # Pausa de 1s para o bind/connect dos sockets IPC não colidirem
        time.sleep(1)

    print("\n" + "=" * 65)
    print(" [SISTEMA ATIVO] Todos os nós de fundo estão operando.")
    print(" Iniciando interface visual do tabuleiro no terminal...")
    print("=" * 65 + "\n")
    time.sleep(1)

    # 2. Executa a interface do tabuleiro no terminal ativo
    visualizer_full_path = BASE_DIR / VISUALIZER_NODE[1]
    if visualizer_full_path.exists():
        try:
            subprocess.run(
                [sys.executable, str(visualizer_full_path)], cwd=str(BASE_DIR)
            )
        except KeyboardInterrupt:
            stop_all_nodes(None, None)
    else:
        print(
            f"[ALERTA] Visualizador não encontrado em: {VISUALIZER_NODE[1]}"
        )
        print(
            "Mantendo os nós em background rodando. Pressione Ctrl+C para sair."
        )
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()