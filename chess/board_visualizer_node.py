#ESSE CÓDIGO FOI CRIADO EXCLUSIVAMENTE PARA TESTES MESMO SENDO LEGALZINHO NÃO ENTRA NO PROJETO FINAL

import os
import sys
import zmq

# Conexão ZMQ
context = zmq.Context()
sub_verified = context.socket(zmq.SUB)
sub_verified.connect("ipc:///tmp/verified_board.ipc")
sub_verified.setsockopt_string(zmq.SUBSCRIBE, "")

# Cores ANSI para o terminal
COLOR_WHITE_PIECE = "\033[96m"  # Ciano brilhante (Brancas - Jogador)
COLOR_BLACK_PIECE = "\033[91m"  # Vermelho (Pretas - Stockfish)
COLOR_RESET = "\033[0m"

#desenho das peças e códigos correspondentes
UNICODE_PIECES = {
    'R': f'{COLOR_WHITE_PIECE}♖{COLOR_RESET}',
    'N': f'{COLOR_WHITE_PIECE}♘{COLOR_RESET}',
    'B': f'{COLOR_WHITE_PIECE}♗{COLOR_RESET}',
    'Q': f'{COLOR_WHITE_PIECE}♕{COLOR_RESET}',
    'K': f'{COLOR_WHITE_PIECE}♔{COLOR_RESET}',
    'P': f'{COLOR_WHITE_PIECE}♙{COLOR_RESET}',
    'r': f'{COLOR_BLACK_PIECE}♜{COLOR_RESET}',
    'n': f'{COLOR_BLACK_PIECE}♞{COLOR_RESET}',
    'b': f'{COLOR_BLACK_PIECE}♝{COLOR_RESET}',
    'q': f'{COLOR_BLACK_PIECE}♛{COLOR_RESET}',
    'k': f'{COLOR_BLACK_PIECE}♚{COLOR_RESET}',
    'p': f'{COLOR_BLACK_PIECE}♟{COLOR_RESET}',
    '.': '⭘',
}

#inicia o tabuleiro
INITIAL_BOARD = """r n b q k b n r
p p p p p p p p
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
P P P P P P P P
R N B Q K B N R"""

# carrega corzinha nas peças pra não ficar feio no terminal
def render_colored_board(board_str):
    lines = board_str.strip().split('\n')
    rendered_lines = []
    #percorre as linhas e colunas pintando as peças e carregando na lista de já coloridas
    for line in lines:
        rendered_row = []
        for char in line.split():
            rendered_row.append(UNICODE_PIECES.get(char, char))
        rendered_lines.append(" |".join(rendered_row))

    return "\n -----------------\n".join(rendered_lines)

# limpa o terminal e desenha na tela o tabuleiro, e mostra ultima jogada
def draw_screen(last_move, current_turn, raw_board):
    os.system('clear' if os.name == 'posix' else 'cls')
    print("====================================")
    print(f"  ÚLTIMA JOGADA: {last_move}")
    print("====================================")
    print("  -----------------")

    board_rendered = render_colored_board(raw_board)
    board_rows = board_rendered.split('\n')

    for idx, row in enumerate(board_rows):
        if "-----------------" in row:
            print(f"  {row}")
        else:
            rank_num = 8 - (idx // 2)
            print(f"{rank_num} |{row}|")

    print("  -----------------")
    print("    a b c d e f g h")
    print("====================================")
    print(f"  Turno atual: {current_turn}\n", flush=True)


print("[VISUALIZADOR] Nó visualizador de tabuleiro iniciado.", flush=True)# mensagem pro launch

# desenha o tabuleiro inicial assim que rodar o script
draw_screen("Início da Partida", "BRANCAS (Jogador)", INITIAL_BOARD)

# loop continuo de atualização via ZMQ
while True:
    try:
        msg = sub_verified.recv_string()#recebe do verifier a ultima jogada, o turno atual e o tabuleiro como está
        parts = msg.split('|')#separa a mensagem recebido usando os |

        #checa se chegou tudo que precisa e desenha no terminal
        if len(parts) >= 3:
            last_move = parts[0]
            current_turn = parts[1]
            raw_board = parts[2]
            draw_screen(last_move, current_turn, raw_board)
        elif len(parts) == 1 and len(msg.strip()) > 10:
            # fallback caso receba apenas o tabuleiro bruto sem cabeçalho
            draw_screen("Atualizado", "Aguardando...", msg)

    except Exception as e:
        print(f"[ERRO VISUALIZADOR]: {e}", flush=True)