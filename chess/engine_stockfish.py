import re
import time
import zmq
from stockfish import Stockfish

context = zmq.Context()

# Escuta mensagens de turno publicadas pela State Machine
sub_machine = context.socket(zmq.SUB)
sub_machine.connect("ipc:///tmp/state_machine.ipc")
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')

# Publica no canal DEDICADO da engine
pub_move = context.socket(zmq.PUB)
pub_move.bind("ipc:///tmp/engine_output.ipc")

stockfish = Stockfish(
    path="/usr/games/stockfish", depth=10, parameters={"Threads": 2}
)
print("[STOCKFISH] Engine pronta e aguardando chamadas...", flush=True)

while True:
    try:
        msg = sub_machine.recv_string()

        if "MODEL" in msg:
            parts = msg.split(maxsplit=1)
            if len(parts) > 1:
                raw_fen = parts[1].strip()

                # Sanitização da FEN
                clean_fen = re.sub(
                    r"('?s\s+turn|turn).*$", "", raw_fen, flags=re.IGNORECASE
                ).strip()

                if stockfish.is_fen_valid(clean_fen):
                    print(
                        f"[STOCKFISH] Posição FEN válida: {clean_fen}",
                        flush=True,
                    )
                    stockfish.set_fen_position(clean_fen)
                    best_move = stockfish.get_best_move()

                    if best_move:
                        print(
                            f"[STOCKFISH] Jogada calculada: {best_move}",
                            flush=True,
                        )
                        time.sleep(0.5)
                        pub_move.send_string(best_move)
                else:
                    print(
                        f"[ERRO STOCKFISH] FEN inválida ignorada: '{raw_fen}' -> Limpa: '{clean_fen}'",
                        flush=True,
                    )

    except Exception as e:
        print(f"[ERRO STOCKFISH]: {e}", flush=True)
        time.sleep(0.1)