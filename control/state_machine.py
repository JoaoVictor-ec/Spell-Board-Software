import time
import zmq

def main():
    #inicia a comunicação via zeromq
    context = zmq.Context()

    # publica estados para os outros nós
    # tópicos que podem ser publicados: 'PLAYER', 'MODEL_THINKING <FEN>', 'RESET', 'ROBOT_MOVING'
    pub_state = context.socket(zmq.PUB)
    pub_state.bind("ipc:///tmp/state_machine.ipc")

    # escuta o verificador e o serial
    sub_verified = context.socket(zmq.SUB)
    sub_verified.connect("ipc:///tmp/verified_state.ipc")
    sub_verified.setsockopt_string(zmq.SUBSCRIBE, "")

    #timeout pra conexões inciarem automaticamente
    print("Orquestrador iniciado. Aguardando estabilização das conexões IPC...", flush=True)
    time.sleep(2)

    #inicia como player turn, talvez mudar? ver melhor isso quando for implementar 2 players
    current_state = "PLAYER"
    print(f"\nStarting match, now its: {current_state} turn to play", flush=True)# avisa quem deve jogar
    pub_state.send_string(current_state)#manda estado para socket

    #loop de eventos
    while True:
        try:
            #recebe a mensagem do verificador/serial
            msg = sub_verified.recv_string()
            print(f"\nEvent received: {msg}", flush=True)#mostra o evento recebido

            #ve se a mensagem recebida começa com PLAYER_MOVE
            if msg.startswith("PLAYER_MOVE"):
                _, data = msg.split(" ", 1)#corta o primeiro espaço que encontrar
                uci_move, fen = data.split("|")# a variável data tinha o comando em 2 notações aqui separa
                print(f"Human move alright ({uci_move})", flush=True)#dado que é vez do player e ele fez uma jogada válida
                
                current_state = f"MODEL_THINKING {fen}" #muda o estado para model thinking por que o player já jogou
                print(f"Changing state to: {current_state}", flush=True)
                pub_state.send_string(current_state)#manda o novo estado
            #se o jogador fez um movimento ilegal, o turno ainda é do player e reenvia
            elif msg.startswith("INVALID_MOVE"):
                print("Invalid move, player tries again", flush=True)
                current_state = "PLAYER"
                pub_state.send_string(current_state)
            
            # stockfish fez um movimento legal
            elif msg.startswith("ENGINE_MOVE_VALIDATED"):
                _, data = msg.split(" ", 1)
                uci_move, fen = data.split("|")
                print(f"Engines move: ({uci_move}) validated.", flush=True)
                
                # essa parte de esperar 1 sec é só enquanto o nó serial não existe, quando tiver a integração com o arduino mudar pra esperar sinal
                time.sleep(1)
                current_state = "PLAYER" #muda direto pro turno do player
                print(f"Back to: {current_state}", flush=True)
                pub_state.send_string(current_state)

            #isso é pra quanto tivermos integrado as parada
            elif msg.startswith("ROBOT_DONE"):
                print("Robot finished physical movement. Back to player state", flush=True)
                current_state = "PLAYER"
                pub_state.send_string(current_state)

            #verifica estado que o jogo acabou
            elif msg.startswith("GAME_OVER"):
                result = msg.split(" ", 1)[1]
                print(f"\nMate detected, result is: {result}", flush=True)

            #verifica estado que reseta o tabuleiro
            elif msg.startswith("BOARD_RESET"):
                print("Reseting board", flush=True)
                current_state = "PLAYER"
                pub_state.send_string(current_state)

        #ctrl + C
        except KeyboardInterrupt:
            print("\nEncerrando orquestrador...", flush=True)
            break
        except Exception as e:
            print(f"Error in the state machine: {e}", flush=True)
            time.sleep(0.1)

if __name__ == "__main__":
    main()