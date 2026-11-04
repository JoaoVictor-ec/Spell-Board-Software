import os
import re
import time
import unicodedata
import zmq
import chess

# mapeia palavras de números e sons parecidos em inglês para dígitos
NUM_MAP = {
    'one': '1', 'two': '2', 'to': '2', 'too': '2',
    'three': '3', 'four': '4', 'for': '4',
    'five': '5', 'six': '6', 'seven': '7',
    'eight': '8', 'ate': '8'
}

# palavras de preenchimento e conectivos em inglês para remover da transcrição
NOISE_WORDS = ['to', 'at', 'goes', 'takes', 'captures', 'on', 'in', 'move', 'please', 'the']


# limpa o texto transcrito tirando acentos, pontuação e palavras inúteis
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


# tenta converter o texto falado em um movimento uci válido para o tabuleiro atual
def parse_speech_to_uci(speech_text: str, board: chess.Board) -> str | None:
    text = clean_speech_text(speech_text)
    
    # verifica se foi um comando de roque curto ou longo para as brancas ou pretas
    if "short castle" in text or "kingside castle" in text or text == "castle":
        if chess.Move.from_uci("e1g1") in board.legal_moves: return "e1g1"
        if chess.Move.from_uci("e8g8") in board.legal_moves: return "e8g8"
    elif "long castle" in text or "queenside castle" in text:
        if chess.Move.from_uci("e1c1") in board.legal_moves: return "e1c1"
        if chess.Move.from_uci("e8c8") in board.legal_moves: return "e8c8"

    # procura por duas coordenadas diretas no texto tipo b1 c3 ou e2 e4
    found_squares = re.findall(r'[a-h][1-8]', text)
    if len(found_squares) == 2:
        possible_uci = f"{found_squares[0]}{found_squares[1]}"
        try:
            move = chess.Move.from_uci(possible_uci)
            if move in board.legal_moves:
                return move.uci()
        except ValueError:
            pass

    # se não achou coordenadas diretas compara a fala com todos os movimentos legais do tabuleiro
    for move in board.legal_moves:
        uci = move.uci()
        san = board.san(move)
        dest_match = re.search(r'([a-h][1-8])', san)
        if not dest_match:
            continue
        dest_square = dest_match.group(1)
        piece_symbol = san[0] if san[0] in ['N', 'B', 'R', 'Q', 'K'] else ''
        
        # monta as frases possíveis em inglês que o jogador poderia ter dito pra essa peça
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

        # se a frase bate com a transcrição retorna o movimento uci correspondente
        for phrase in possible_phrases:
            if phrase in text:
                return uci

    return None


context = zmq.Context()

# escuta as atualizações de estado do orquestrador
sub_machine = context.socket(zmq.SUB)
sub_machine.connect("ipc:///tmp/state_machine.ipc")
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
sub_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')

# escuta as jogadas em texto vindas do nó do whisper
sub_player_move = context.socket(zmq.SUB)
sub_player_move.connect("ipc:///tmp/movement.ipc")
sub_player_move.setsockopt_string(zmq.SUBSCRIBE, "")

# escuta a jogada calculada pela engine do stockfish
sub_engine_move = context.socket(zmq.SUB)
sub_engine_move.connect("ipc:///tmp/engine_output.ipc")
sub_engine_move.setsockopt_string(zmq.SUBSCRIBE, "")

# publica o resultado da validação para a máquina de estados
pub_verified = context.socket(zmq.PUB)
pub_verified.bind("ipc:///tmp/verified_state.ipc")

# publica o estado do tabuleiro formatado para a tela do visualizador
pub_board = context.socket(zmq.PUB)
pub_board.bind("ipc:///tmp/verified_board.ipc")


# empacota a última jogada o turno e a matriz do tabuleiro para o visualizador
def send_board_visualizer(last_move_text, next_turn_text):
    msg = f"{last_move_text}|{next_turn_text}|{str(board)}"
    pub_board.send_string(msg)


# registra os três sockets no poller para monitorar tudo sem travar a execução
poller = zmq.Poller()
poller.register(sub_machine, zmq.POLLIN)
poller.register(sub_player_move, zmq.POLLIN)
poller.register(sub_engine_move, zmq.POLLIN)

# inicia o tabuleiro virtual da biblioteca python-chess
board = chess.Board()
current_turn = 'PLAYER'

print("[VERIFICADOR] Verificador de regras iniciado.", flush=True)
print(board)
print(f"FEN : {board.fen()}")

# desenha a tela inicial do jogo no visualizador
send_board_visualizer("Início da Partida", "BRANCAS (Jogador)")

# loop principal de validação de regras
while True:
    try:
        sockets = dict(poller.poll(100))

        # 1. se chegou atualização da máquina de estados atualiza o turno ou reseta o jogo
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

        # 2. se chegou texto do whisper tenta validar a jogada do humano
        if sub_player_move in sockets:
            raw_speech = sub_player_move.recv_string().strip()
            print(f"Transcription received '{raw_speech}'", flush=True)

            if current_turn == 'PLAYER':
                uci_move = parse_speech_to_uci(raw_speech, board)

                # se a jogada for válida aplica no tabuleiro e avisa o orquestrador
                if uci_move:
                    move_obj = chess.Move.from_uci(uci_move)
                    board.push(move_obj)
                    
                    new_fen = board.fen()
                    print(f"Move: {uci_move}", flush=True)
                    print(f"New FEN: {new_fen}", flush=True)

                    send_board_visualizer(f"Jogador ({uci_move})", "PRETAS (Stockfish)")
                    pub_verified.send_string(f"PLAYER_MOVE {uci_move}|{new_fen}")
                    
                    # checa se o movimento resultou em xeque-mate ou empate
                    if board.is_game_over():
                        print(f"Check if it was mate: {board.result()}", flush=True)
                        pub_verified.send_string(f"GAME_OVER {board.result()}")
                # se a jogada for inválida avisa a máquina de estados para manter a vez do jogador
                else:
                    print(f" Invalid move: '{raw_speech}'", flush=True)
                    pub_verified.send_string(f"INVALID_MOVE {raw_speech}")

        # 3. se chegou a jogada da ia verifica se é válida e aplica no tabuleiro
        if sub_engine_move in sockets:
            engine_msg = sub_engine_move.recv_string().strip()
            print(f"engines move: '{engine_msg}'", flush=True)

            if current_turn == 'MODEL':
                try:
                    uci_move = engine_msg.split()[-1] if " " in engine_msg else engine_msg
                    move_obj = chess.Move.from_uci(uci_move)

                    # se o movimento do stockfish for válido atualiza o jogo e notifica os nós
                    if move_obj in board.legal_moves:
                        board.push(move_obj)
                        new_fen = board.fen()
                        print(f"confirming engines move {uci_move}", flush=True)
                        print(f"new FEN: {new_fen}", flush=True)

                        send_board_visualizer(f"Stockfish ({uci_move})", "BRANCAS (Jogador)")
                        pub_verified.send_string(f"ENGINE_MOVE_VALIDATED {uci_move}|{new_fen}")

                        # checa se a ia deu xeque-mate
                        if board.is_game_over():
                            print(f"Game end: {board.result()}", flush=True)
                            pub_verified.send_string(f"GAME_OVER {board.result()}")
                    else:
                        print(f"Engine tried ilegal move: {uci_move}", flush=True)
                except Exception as err:
                    print(f"ERROR: {err}", flush=True)

    # evita que o nó quebre em caso de exceção no loop
    except Exception as e:
        print(f"Error at the verification: {e}", flush=True)
        time.sleep(0.1)