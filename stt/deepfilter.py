import os
import time
import numpy as np
import onnxruntime as ort
import sounddevice as sd
import zmq

context_a = zmq.Context()
sender_a = context_a.socket(zmq.PUSH)
sender_a.connect("ipc:///tmp/audio_filtrado.ipc")

context_machine = zmq.Context()
subscriber_machine = context_machine.socket(zmq.SUB)
subscriber_machine.connect("ipc:///tmp/state_machine.ipc")
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')

SAMPLE_RATE = 16000
FRAME_DURATION = 0.032  # 32ms = 512 amostras
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION)  # 512
CONTEXT_SIZE = 64  # Buffer de contexto exigido pelo Silero VAD v5 ONNX

VAD_MODEL_PATH = '/home/joao/oficinas2/Spell_nodes/stt/silero_vad.onnx'
if not os.path.exists(VAD_MODEL_PATH):
    print(f"[ERRO ÁUDIO] Modelo VAD não encontrado em: {VAD_MODEL_PATH}", flush=True)
    exit(1)

vad_session = ort.InferenceSession(VAD_MODEL_PATH)

vad_state = np.zeros((2, 1, 128), dtype=np.float32)
vad_context = np.zeros(CONTEXT_SIZE, dtype=np.float32)

def is_speech_silero(audio_chunk, threshold=0.2, vol_threshold=0.12):
    global vad_state, vad_context
    
    input_audio = np.concatenate([vad_context, audio_chunk]).reshape(1, -1).astype(np.float32)
    vad_context = audio_chunk[-CONTEXT_SIZE:]
    
    inputs = {
        'input': input_audio,
        'state': vad_state,
        'sr': np.array(SAMPLE_RATE, dtype=np.int64)
    }
    
    try:
        outputs = vad_session.run(None, inputs)
        prob_speech = float(outputs[0].flatten()[0])
        vad_state = outputs[1]
    except Exception:
        prob_speech = 0.0

    max_vol = float(np.max(np.abs(audio_chunk)))
    speech_detected = (prob_speech > threshold) or (max_vol > vol_threshold)
    
    return prob_speech, max_vol, speech_detected

def reset_vad_state():
    global vad_state, vad_context
    vad_state = np.zeros((2, 1, 128), dtype=np.float32)
    vad_context = np.zeros(CONTEXT_SIZE, dtype=np.float32)

current_turn = 'PLAYER'
speech_buffer = []
is_speaking = False
silence_counter = 0
MAX_SILENCE_CHUNKS = 25  # ~800ms de silêncio encerra a frase

print("[ÁUDIO] Captura iniciada em 16 kHz (ONNX + Context Buffer 64)...", flush=True)

with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32', blocksize=FRAME_SIZE) as stream:
    last_debug_time = time.time()
    
    while True:
        try:
            # Drena e trata mensagens da State Machine sanitizando o sufixo FEN
            while True:
                try:
                    raw_turn = subscriber_machine.recv_string(flags=zmq.NOBLOCK)
                    state_tag = raw_turn.split()[0] if raw_turn else ''
                    
                    if state_tag.startswith('MODEL'):
                        new_turn = 'MODEL'
                    else:
                        new_turn = 'PLAYER'

                    if new_turn != current_turn:
                        current_turn = new_turn
                        if current_turn != 'PLAYER':
                            speech_buffer.clear()
                            is_speaking = False
                            reset_vad_state()
                except zmq.Again:
                    break

            frame, _ = stream.read(FRAME_SIZE)

            if current_turn == 'PLAYER':
                audio_16k = frame.flatten()
                prob_speech, max_vol, speech_detected = is_speech_silero(audio_16k)

                if time.time() - last_debug_time > 0.5 or speech_detected:
                    print(f"[DEBUG ÁUDIO] Vol: {max_vol:.4f} | Prob VAD: {prob_speech:.4f}", flush=True)
                    last_debug_time = time.time()

                if speech_detected:
                    if not is_speaking:
                        print(f"*** VOZ DETECTADA! (Vol: {max_vol:.2f} | Prob: {prob_speech:.4f}) ***", flush=True)
                        is_speaking = True
                    speech_buffer.append(audio_16k)
                    silence_counter = 0

                elif is_speaking:
                    speech_buffer.append(audio_16k)
                    silence_counter += 1

                    if silence_counter >= MAX_SILENCE_CHUNKS:
                        print("[ÁUDIO] Fim da fala. Enviando para o Whisper...", flush=True)
                        full_audio = np.concatenate(speech_buffer)
                        sender_a.send(full_audio.tobytes())

                        speech_buffer.clear()
                        is_speaking = False
                        silence_counter = 0
                        reset_vad_state()

        except Exception as e:
            print(f"[ERRO ÁUDIO]: {e}", flush=True)