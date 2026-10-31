import time
import zmq

def main():
    context = zmq.Context()

    # Publica estados para os outros nós
    # Tópicos publicados: 'PLAYER', 'MODEL_THINKING <FEN>', 'RESET', 'ROBOT_MOVING'
    pub_state = context.socket(zmq.PUB)
    pub_state.bind("ipc:///tmp/state_machine.ipc")

    # Escuta o verificador e o nó serial
    sub_verified = context.socket(zmq.SUB)
    sub_verified.connect("ipc:///tmp/verified_state.ipc")
    sub_verified.setsockopt_string(zmq.SUBSCRIBE, "")

    print("Orquestrador iniciado. Aguardando estabilização das conexões IPC...", flush=True)
    time.sleep(2)

    current_state = "PLAYER"
    print(f"\nStarting match, now its: {current_state} turn to play", flush=True)
    pub_state.send_string(current_state)

    while True:
        try:
            msg = sub_verified.recv_string()
            print(f"\nEvent received: {msg}", flush=True)

            if msg.startswith("PLAYER_MOVE"):
                _, data = msg.split(" ", 1)
                uci_move, fen = data.split("|")
                print(f"Human move alright ({uci_move})", flush=True)
                
                current_state = f"MODEL_THINKING {fen}"
                print(f"Changing state to: {current_state}", flush=True)
                pub_state.send_string(current_state)

            elif msg.startswith("INVALID_MOVE"):
                print("Invalid move, player tries again", flush=True)
                current_state = "PLAYER"
                pub_state.send_string(current_state)

            elif msg.startswith("ENGINE_MOVE_VALIDATED"):
                _, data = msg.split(" ", 1)
                uci_move, fen = data.split("|")
                print(f"Engines move: ({uci_move}) validated.", flush=True)
                
                # MODO LAPTOP / TESTE SEM ROBÔ:
                # Dá 1 segundo de pausa e devolve a vez direto para o jogador
                time.sleep(1)
                current_state = "PLAYER"
                print(f"Back to: {current_state}", flush=True)
                pub_state.send_string(current_state)

            elif msg.startswith("ROBOT_DONE"):
                print("Robot finished physical movement. Back to player state", flush=True)
                current_state = "PLAYER"
                pub_state.send_string(current_state)

            elif msg.startswith("GAME_OVER"):
                result = msg.split(" ", 1)[1]
                print(f"\nMate detected, result is: {result}", flush=True)

            elif msg.startswith("BOARD_RESET"):
                print("Reseting board", flush=True)
                current_state = "PLAYER"
                pub_state.send_string(current_state)

        except KeyboardInterrupt:
            print("\nEncerrando orquestrador...", flush=True)
            break
        except Exception as e:
            print(f"Error in the state machine: {e}", flush=True)
            time.sleep(0.1)

if __name__ == "__main__":
    main()