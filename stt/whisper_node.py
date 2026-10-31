import os
import re
import time
import numpy as np
import zmq
from pywhispercpp.model import Model

# Sockets ZeroMQ
context_a = zmq.Context()
receiver_a = context_a.socket(zmq.PULL)
receiver_a.bind("ipc:///tmp/audio_filtrado.ipc")

context_machine = zmq.Context()
subscriber_machine = context_machine.socket(zmq.SUB)
subscriber_machine.connect("ipc:///tmp/state_machine.ipc")
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')

context_move = zmq.Context()
subscriber_move = context_move.socket(zmq.PUB)
subscriber_move.bind("ipc:///tmp/movement.ipc")

poller = zmq.Poller()
poller.register(subscriber_machine, zmq.POLLIN)
poller.register(receiver_a, zmq.POLLIN)

MODEL_PATH = (
    '/home/joao/oficinas2/Spell_nodes/stt/whisper.cpp/models/ggml-base.en.bin'
)

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


def clean_transcription(text):
    text = text.lower().strip()
    text = re.sub(r'\[.*?\]|\(.*?\)', '', text).strip()

    if not text or text in ['chew.', 'chew', 'you', 'thank you.']:
        return ''

    for pattern, replacement in PHONETIC_FIXES.items():
        text = re.sub(pattern, replacement, text)

    squares = re.findall(r'\b[a-h][1-8]\b', text)
    if len(squares) == 2:
        uci_move = f"{squares[0]}{squares[1]}"
        print(
            f"[WHISPER] Coordenadas extraídas diretamente: {uci_move}",
            flush=True,
        )
        return uci_move

    return text


def load_model_whisper(model_path):
    if not os.path.exists(model_path):
        print(f"[ERRO WHISPER] Modelo não encontrado em: {model_path}", flush=True)
        return None

    print("[WHISPER] Carregando modelo base do Whisper...", flush=True)
    try:
        model = Model(model_path, n_threads=4, print_realtime=False)
        print("[WHISPER] STT pronto com resgate de coordenadas!", flush=True)
        return model
    except Exception as e:
        print(f"[ERRO WHISPER] Falha ao carregar modelo: {e}", flush=True)
        return None


def transcribe(whisper_model, audio_bytes):
    audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
    chess_prompt = "Chess move: pawn e4, knight b1 to c3, e2 e4, bishop c4, rook, queen, king."
    segments = whisper_model.transcribe(audio_array, initial_prompt=chess_prompt)
    raw_text = "".join([segment.text for segment in segments])
    return clean_transcription(raw_text)


whisper_model = load_model_whisper(MODEL_PATH)
if whisper_model is None:
    exit(1)

current_turn = 'PLAYER'

while True:
    try:
        sockets = dict(poller.poll(100))

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

        if receiver_a in sockets:
            audio_bytes = receiver_a.recv()

            if current_turn == 'PLAYER':
                print("[WHISPER] Áudio recebido. Transcrevendo...", flush=True)
                command = transcribe(whisper_model, audio_bytes)

                if command:
                    print(f"*** JOGADA RECONHECIDA: '{command}' ***", flush=True)
                    subscriber_move.send_string(command)
                else:
                    print("[WHISPER] Áudio ignorado (sem coordenadas ou peças válidas).", flush=True)
            else:
                print(f"[WHISPER] Áudio descartado (turno atual: {current_turn}).", flush=True)

    except Exception as e:
        print(f"[ERRO WHISPER]: {e}", flush=True)
        time.sleep(0.1)