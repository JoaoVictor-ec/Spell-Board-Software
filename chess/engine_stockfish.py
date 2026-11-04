import re
import time
import zmq
from stockfish import Stockfish

#inicia a comunicação via zeromq
context = zmq.Context()

#escuta mensagens de turno publicadas pela state machine
sub_machine = context.socket(zmq.SUB)
sub_machine.connect("ipc:///tmp/state_machine.ipc")
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')

# publica no canal único da engine
pub_move = context.socket(zmq.PUB)
pub_move.bind("ipc:///tmp/engine_output.ipc")

#path pro stockfish
stockfish = Stockfish(
    path="/usr/games/stockfish", depth=10, parameters={"Threads": 2}
)
print("[STOCKFISH] Engine pronta e aguardando chamadas...", flush=True)

#loop recebendo mensagem no socket, verificando de quem é o turno e executando a ação dele, então publicando
while True:
    try:
        #variável que recebe string que indica o turno e a notação FEN que indica o estado do tabuleiro, ...
        msg = sub_machine.recv_string()

        if "MODEL" in msg:
            #separa a mensagem em vez do jogador e coisas da FEN
            parts = msg.split(maxsplit=1)
            if len(parts) > 1:
                raw_fen = parts[1].strip()# limpa a notação fen, garantindo que não tem espaços e tabs 

                # no texto da FEN remove qualquer coisa que tenha vindo com a string do turno
                clean_fen = re.sub(
                    r"('?s\s+turn|turn).*$", "", raw_fen, flags=re.IGNORECASE
                ).strip()

                # usa um método do stockfish pra ver se o fen está valido, se estiver avisa e a engine joga
                if stockfish.is_fen_valid(clean_fen):
                    print(
                        f"[STOCKFISH] Posição FEN válida: {clean_fen}",
                        flush=True,
                    )
                    stockfish.set_fen_position(clean_fen)
                    best_move = stockfish.get_best_move()#pega o melhor movimento a partir de onde o jogo tava

                    if best_move:
                        print(
                            f"[STOCKFISH] Jogada calculada: {best_move}",
                            flush=True,
                        )
                        time.sleep(0.5)
                        pub_move.send_string(best_move)
                #tinha erro na fen
                else:
                    print(
                        f"[ERRO STOCKFISH] FEN inválida ignorada: '{raw_fen}' -> Limpa: '{clean_fen}'",
                        flush=True,
                    )
    #erro no stockfish, costuma dar quando não consegue carregar o modelo
    except Exception as e:
        print(f"[ERRO STOCKFISH]: {e}", flush=True)
        time.sleep(0.1)