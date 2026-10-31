import os
import re
import time
import unicodedata
import zmq
import chess

# Mapeia números por extenso para numerais
NUM_MAP = {
    'one': '1', 'two': '2', 'to': '2', 'too': '2',
    'three': '3', 'four': '4', 'for': '4',
    'five': '5', 'six': '6', 'seven': '7',
    'eight': '8', 'ate': '8'
}

# Palavras de ruído para ignorar na transcrição
NOISE_WORDS = ['to', 'at', 'goes', 'takes', 'captures', 'on', 'in', 'move', 'please', 'the']


def clean_speech_text(text: str) -> str:
    text = text.lower().strip()
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'MN')
    text = re.sub(r'[^\w\s]', '', text)
    words = text.split()
    cleaned_words = [NUM_MAP.get(w, w) for w in words]
    text = " ".join(cleaned_words)
    for word in NOISE_WORDS:
        text = re.sub(r'\b' + word + r'\b', '', text)
    return ' '.join(text.split())


def parse_speech_to_uci(speech_text: str, board: chess.Board) -> str | None:
    text = clean_speech_text(speech_text)
    
    # Tratamento de Roque
    if "short castle" in text or "kingside castle" in text or text == "castle":
        if chess.Move.from_uci("e1g1") in board.legal_moves: return "e1g1"
        if chess.Move.from_uci("e8g8") in board.legal_moves: return "e8g8"
    elif "long castle" in text or "queenside castle" in text:
        if chess.Move.from_uci("e1c1") in board.legal_moves: return "e1c1"
        if chess.Move.from_uci("e8c8") in board.legal_moves: return "e8c8"

    # Coordenadas diretas (ex: b1c3)
    found_squares = re.findall(r'[a-h][1-8]', text)
    if len(found_squares) == 2:
        possible_uci = f"{found_squares[0]}{found_squares[1]}"
        try:
            move = chess.Move.from_uci(possible_uci)
            if move in board.legal_moves:
                return move.uci()
        except ValueError:
            pass

    # Validação via Notação Algébrica SAN
    for move in board.legal_moves:
        uci = move.uci()
        san = board.san(move)
        dest_match = re.search(r'([a-h][1-8])', san)
        if not dest_match:
            continue
        dest_square = dest_match.group(1)
        piece_symbol = san[0] if san[0] in ['N', 'B', 'R', 'Q', 'K'] else ''
        
        possible_phrases = []
        if piece_symbol == 'N':
            possible_phrases.extend([f"knight {dest_square}", f"night {dest_square}", f"knight on {dest_square}"])
        elif piece_symbol == 'B':
            possible_phrases.extend([f"bishop {dest_square}", f"bishop on {dest_square}"])
        elif piece_symbol == 'R':
            possible_phrases.extend([f"rook {dest_square}", f"rook on {dest_square}"])
        elif piece_symbol == 'Q':
            possible_phrases.extend([f"queen {dest_square}"])
        elif piece_symbol == 'K':
            possible_phrases.extend([f"king {dest_square}"])
        else:
            possible_phrases.extend([dest_square, f"pawn {dest_square}"])

        possible_phrases.append(uci)
        possible_phrases.append(f"{uci[:2]} {uci[2:]}")

        for phrase in possible_phrases:
            if phrase in text:
                return uci

    return None


context = zmq.Context()

# Escuta o estado/turno publicado pela State Machine
sub_machine = context.socket(zmq.SUB)
sub_machine.connect("ipc:///tmp/state_machine.ipc")
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')

# Escuta a voz transcrita do jogador (Whisper)
sub_player_move = context.socket(zmq.SUB)
sub_player_move.connect("ipc:///tmp/movement.ipc")
sub_player_move.setsockopt_string(zmq.SUBSCRIBE, "")

# Escuta a resposta da engine (Stockfish)
sub_engine_move = context.socket(zmq.SUB)
sub_engine_move.connect("ipc:///tmp/engine_output.ipc")
sub_engine_move.setsockopt_string(zmq.SUBSCRIBE, "")

# Publica eventos de movimento validado para a State Machine
pub_verified = context.socket(zmq.PUB)
pub_verified.bind("ipc:///tmp/verified_state.ipc")

# Publica o tabuleiro visual renderizado para a tela do terminal
pub_board = context.socket(zmq.PUB)
pub_board.bind("ipc:///tmp/verified_board.ipc")


def send_board_visualizer(last_move_text, next_turn_text):
    msg = f"{last_move_text}|{next_turn_text}|{str(board)}"
    pub_board.send_string(msg)


poller = zmq.Poller()
poller.register(sub_machine, zmq.POLLIN)
poller.register(sub_player_move, zmq.POLLIN)
poller.register(sub_engine_move, zmq.POLLIN)

board = chess.Board()
current_turn = 'PLAYER'

print("[VERIFICADOR] Verificador de regras iniciado.", flush=True)
print(board)
print(f"FEN : {board.fen()}")

send_board_visualizer("Início da Partida", "BRANCAS (Jogador)")

while True:
    try:
        sockets = dict(poller.poll(100))

        # 1. Atualização do estado do turno recebido do Orquestrador
        if sub_machine in sockets:
            state_msg = sub_machine.recv_string().strip()
            state_tag = state_msg.split()[0] if state_msg else ''

            if state_tag == 'RESET':
                board.reset()
                print("Reseting the game", flush=True)
                pub_verified.send_string(f"BOARD_RESET {board.fen()}")
                send_board_visualizer("Jogo Reiniciado", "BRANCAS (Jogador)")
                current_turn = 'PLAYER'
            else:
                if state_tag.startswith('MODEL'):
                    current_turn = 'MODEL'
                else:
                    current_turn = 'PLAYER'
                print(f"Switching to {current_turn}s turn", flush=True)

        # 2. Processamento da jogada do Jogador
        if sub_player_move in sockets:
            raw_speech = sub_player_move.recv_string().strip()
            print(f"Transcription received '{raw_speech}'", flush=True)

            if current_turn == 'PLAYER':
                uci_move = parse_speech_to_uci(raw_speech, board)

                if uci_move:
                    move_obj = chess.Move.from_uci(uci_move)
                    board.push(move_obj)
                    
                    new_fen = board.fen()
                    print(f"Move: {uci_move}", flush=True)
                    print(f"New FEN: {new_fen}", flush=True)

                    send_board_visualizer(f"Jogador ({uci_move})", "PRETAS (Stockfish)")
                    pub_verified.send_string(f"PLAYER_MOVE {uci_move}|{new_fen}")
                    
                    if board.is_game_over():
                        print(f"Check if it was mate: {board.result()}", flush=True)
                        pub_verified.send_string(f"GAME_OVER {board.result()}")
                else:
                    print(f" Invalid move: '{raw_speech}'", flush=True)
                    pub_verified.send_string(f"INVALID_MOVE {raw_speech}")

        # 3. Processamento da jogada do Stockfish
        if sub_engine_move in sockets:
            engine_msg = sub_engine_move.recv_string().strip()
            print(f"engines move: '{engine_msg}'", flush=True)

            if current_turn == 'MODEL':
                try:
                    uci_move = engine_msg.split()[-1] if " " in engine_msg else engine_msg
                    move_obj = chess.Move.from_uci(uci_move)

                    if move_obj in board.legal_moves:
                        board.push(move_obj)
                        new_fen = board.fen()
                        print(f"confirming engines move {uci_move}", flush=True)
                        print(f"new FEN: {new_fen}", flush=True)

                        send_board_visualizer(f"Stockfish ({uci_move})", "BRANCAS (Jogador)")
                        pub_verified.send_string(f"ENGINE_MOVE_VALIDATED {uci_move}|{new_fen}")

                        if board.is_game_over():
                            print(f"Game end: {board.result()}", flush=True)
                            pub_verified.send_string(f"GAME_OVER {board.result()}")
                    else:
                        print(f"Engine tried ilegal move: {uci_move}", flush=True)
                except Exception as err:
                    print(f"ERROR: {err}", flush=True)

    except Exception as e:
        print(f"Error at the verification: {e}", flush=True)
        time.sleep(0.1)