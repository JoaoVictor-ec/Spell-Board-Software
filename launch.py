import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# path pro diretório raíz dos nós
BASE_DIR = Path(__file__).parent.resolve()

# pasta para armazenar os logs de cada nó, muito util pro debug, usando cat ou grep
LOGS_DIR = Path("/tmp/chess_logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# mapeamento dos nós agrupados pelas suas pastas
NODES = [
    ("Orquestrador (State Machine)", "control/state_machine.py"),
    ("Verificador de Regras", "chess/verifier.py"),
    ("Engine Stockfish", "chess/engine_stockfish.py"),  
    ("Serial / Simulação do Robô", "control/serial_node.py"),
    ("Nó Whisper STT", "stt/whisper_node.py"),
    ("Nó Áudio / DeepFilter", "stt/deepfilter.py"),
]

# nó de interface visual que roda no terminal ativo, temporário só pra debug
VISUALIZER_NODE = ("Visualizador de Tabuleiro", "chess/board_visualizer_node.py")

processes = []#lista para guardar todas as referencias dos processos que foram lançados em segundo plano

#função que finaliza os processos criados e fecha os logs
def stop_all_nodes(sig, frame):
    print("\n\n[LAUNCHER] Encerrando todos os nós do ecossistema...")
    for name, proc, log_file in reversed(processes):
        print(f"[LAUNCHER] Parando {name} (PID: {proc.pid})...")
        proc.terminate()
        log_file.close()

    print("[LAUNCHER] Todos os nós foram desligados com sucesso!")
    sys.exit(0)


# registra os sinais de interrupção tipo Ctrl+C
signal.signal(signal.SIGINT, stop_all_nodes)
signal.signal(signal.SIGTERM, stop_all_nodes)


def main():
    #printa aviso de funcionamento
    print("=" * 65)
    print("   ECOSSISTEMA DE XADREZ AUTÔNOMO - INICIALIZANDO NÓS   ")
    print(f"   Diretório Raiz: {BASE_DIR}")
    print("=" * 65)

    # inicia os nós, usando os paths encontrados anteriormente
    for name, relative_script_path in NODES:
        script_full_path = BASE_DIR / relative_script_path

        # checa se  arquivo existe no path passado
        if not script_full_path.exists():
            print(
                f"[ERRO LAUNCHER] Arquivo não encontrado: {relative_script_path}"
            )
            continue
        
        #salva os logs temporários no caminho indicado
        log_filename = (
            f"{Path(relative_script_path).stem}.log"  # ex: state_machine.log
        )
        #cria arquivo texto para botar os logs
        log_file = open(LOGS_DIR / log_filename, "w")

        #printa o nó sendo iniciado e o log dele
        print(
            f"[LAUNCHER] Subindo {name:<30} -> Logs: /tmp/chess_logs/{log_filename}"
        )

        # executa no ambiente python ativo usando a raiz como diretório de trabalho --> talvez mudar dps pra não precisar de venv
        proc = subprocess.Popen(
            [sys.executable, "-u", str(script_full_path)],
            stdout=log_file,
            stderr=log_file,
            cwd=str(BASE_DIR),
        )

        #adiciona a lista de processos, o nome, objeto(proc) do próprio SO e arquivo log respectivos
        processes.append((name, proc, log_file))

        # pausa de 1s para o bind/connect dos sockets IPC não colidirem
        time.sleep(1)

    #quando acaba de inicializar os nós imprime
    print("\n" + "=" * 65)
    print(" [SISTEMA ATIVO] Todos os nós de fundo estão operando.")
    print(" Iniciando interface visual do tabuleiro no terminal...")
    print("=" * 65 + "\n")
    time.sleep(1)

    #executa a interface do tabuleiro no terminal ativo --> temporário só pra teste mesmo
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