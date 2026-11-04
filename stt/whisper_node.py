import os
import re
import time
import numpy as np
import zmq
from pywhispercpp.model import Model

# inicia a comunicação do zeromq para receber o áudio que já passou pelo filtro de ruído
context_a = zmq.Context()
receiver_a = context_a.socket(zmq.PULL)
receiver_a.bind("ipc:///tmp/audio_filtrado.ipc")

# conecta no canal da máquina de estados para saber de quem é o turno
context_machine = zmq.Context()
subscriber_machine = context_machine.socket(zmq.SUB)
subscriber_machine.connect("ipc:///tmp/state_machine.ipc")
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')

# canal onde vai publicar o movimento em texto quando a fala for reconhecida com sucesso
context_move = zmq.Context()
subscriber_move = context_move.socket(zmq.PUB)
subscriber_move.bind("ipc:///tmp/movement.ipc")

# registra os dois canais no poller para monitorar a chegada de dados sem travar a execução
poller = zmq.Poller()
poller.register(subscriber_machine, zmq.POLLIN)
poller.register(receiver_a, zmq.POLLIN)

# monta o caminho dinâmico para encontrar o modelo do whisper no projeto
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "ggml-base.en.bin")

# se o modelo não estiver na raiz do script procura dentro da pasta models
if not os.path.exists(MODEL_PATH):
    MODEL_PATH = os.path.join(SCRIPT_DIR, "models", "ggml-base.en.bin")

# correções fonéticas para trocar palavras em inglês que soam parecidas com peças ou números
PHONETIC_FIXES = {
    r'\bnight\b': 'knight',
    r'\blight\b': 'knight',
    r'\blike\b': 'knight',
    r'\bright\b': 'knight',
    r'\bpalm\b': 'pawn',
    r'\bball\b': 'pawn',
    r'\bbone\b': 'pawn',
    r'\bpool\b': 'pawn',
    r'\bphone\b': 'pawn',
    r'\bfor\b': '4',
    r'\bto\b': '2',
    r'\btoo\b': '2',
    r'\btwo\b': '2',
}


# limpa o texto transcrito, aplica as correções e tenta extrair as casas do tabuleiro
def clean_transcription(text):
    text = text.lower().strip()
    text = re.sub(r'\[.*?\]|\(.*?\)', '', text).strip()

    # descarta ruídos de respiração e estalos comuns que o whisper transcreve como palavras soltas
    if not text or text in ['chew.', 'chew', 'you', 'thank you.']:
        return ''

    # substitui os erros fonéticos mapeados
    for pattern, replacement in PHONETIC_FIXES.items():
        text = re.sub(pattern, replacement, text)

    # procura duas coordenadas válidas de xadrez no texto como e2 e e4
    squares = re.findall(r'\b[a-h][1-8]\b', text)
    if len(squares) == 2:
        uci_move = f"{squares[0]}{squares[1]}"
        print(
            f"[WHISPER] Coordenadas extraídas diretamente: {uci_move}",
            flush=True,
        )
        return uci_move

    return text


# carrega o modelo do whisper na memória usando threads para rodar mais rápido
def load_model_whisper(model_path):
    if not os.path.exists(model_path):
        print(f"[ERRO WHISPER] Modelo não encontrado em: {model_path}", flush=True)
        print("Certifique-se de que o 'ggml-base.en.bin' está salvo em stt/ ou stt/models/", flush=True)
        return None

    print(f"[WHISPER] Carregando modelo Whisper ({model_path})...", flush=True)
    try:
        model = Model(model_path, n_threads=4, print_realtime=False)
        print("[WHISPER] STT pronto com resgate de coordenadas!", flush=True)
        return model
    except Exception as e:
        print(f"[ERRO WHISPER] Falha ao carregar modelo: {e}", flush=True)
        return None


# converte os bytes do áudio para array e manda pro whisper com um prompt de xadrez pra ajudar o contexto
def transcribe(whisper_model, audio_bytes):
    audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
    chess_prompt = "Chess move: pawn e4, knight b1 to c3, e2 e4, bishop c4, rook, queen, king."
    segments = whisper_model.transcribe(audio_array, initial_prompt=chess_prompt)
    raw_text = "".join([segment.text for segment in segments])
    return clean_transcription(raw_text)


# inicializa o modelo e encerra o script se der erro no arquivo
whisper_model = load_model_whisper(MODEL_PATH)
if whisper_model is None:
    exit(1)

# guarda o estado do turno atual da partida
current_turn = 'PLAYER'

# loop principal que escuta os dois sockets continuamente
while True:
    try:
        # checa o poller com timeout baixo pra não travar o loop
        sockets = dict(poller.poll(100))

        # se recebeu mensagem da máquina de estados atualiza a variável do turno
        if subscriber_machine in sockets:
            while True:
                try:
                    state_msg = subscriber_machine.recv_string(flags=zmq.NOBLOCK)
                    state_tag = state_msg.split()[0] if state_msg else ''
                    if state_tag.startswith('MODEL'):
                        current_turn = 'MODEL'
                    else:
                        current_turn = 'PLAYER'
                except zmq.Again:
                    break

        # se chegou áudio novo do filtro verifica se pode processar
        if receiver_a in sockets:
            audio_bytes = receiver_a.recv()

            # só faz a transcrição se for a vez do jogador humano
            if current_turn == 'PLAYER':
                print("[WHISPER] Áudio recebido. Transcrevendo...", flush=True)
                command = transcribe(whisper_model, audio_bytes)

                # se achou uma jogada válida publica o movimento pro verificador
                if command:
                    print(f"*** JOGADA RECONHECIDA: '{command}' ***", flush=True)
                    subscriber_move.send_string(command)
                else:
                    print("[WHISPER] Áudio ignorado (sem coordenadas ou peças válidas).", flush=True)
            # descarta o áudio capturado enquanto a ia ou o robô estiverem jogando
            else:
                print(f"[WHISPER] Áudio descartado (turno atual: {current_turn}).", flush=True)

    # captura erros no loop sem derrubar o nó
    except Exception as e:
        print(f"[ERRO WHISPER]: {e}", flush=True)
        time.sleep(0.1)