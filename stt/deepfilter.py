import os
import time
import numpy as np
import onnxruntime as ort
import sounddevice as sd
import zmq

# busca o microfone usb conectado no computador
def find_mic_index():
    try:
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            dev_name = dev['name'].lower()
            # se achar um dispositivo com usb ou composite no nome e que tenha entrada de áudio
            if ('usb' in dev_name or 'composite' in dev_name) and dev['max_input_channels'] > 0:
                print(f"[ÁUDIO] Microfone USB detectado: '{dev['name']}' (Índice {idx})", flush=True)
                return idx
    except Exception as e:
        print(f"[AVISO ÁUDIO] Erro ao listar dispositivos: {e}", flush=True)
    
    # se não achar nenhum usb específico usa o microfone padrão do sistema
    print("[ÁUDIO] Microfone USB específico não listado pelo nome. Usando o dispositivo padrão.", flush=True)
    return None

# converte a taxa de amostragem do áudio para 16khz que é o formato exigido pelo silero vad e whisper
def resample_audio(audio_chunk, orig_sr, target_sr=16000):
    if orig_sr == target_sr:
        return audio_chunk.astype(np.float32)
    duration = len(audio_chunk) / orig_sr
    target_length = int(duration * target_sr)
    orig_time = np.linspace(0, duration, len(audio_chunk), endpoint=False)
    target_time = np.linspace(0, duration, target_length, endpoint=False)
    return np.interp(target_time, orig_time, audio_chunk).astype(np.float32)

# cria o socket push para enviar o áudio gravado e cortado direto pro nó do whisper
context_a = zmq.Context()
sender_a = context_a.socket(zmq.PUSH)
sender_a.connect("ipc:///tmp/audio_filtrado.ipc")

# escuta os sinais de estado enviados pela máquina de estados
context_machine = zmq.Context()
subscriber_machine = context_machine.socket(zmq.SUB)
subscriber_machine.connect("ipc:///tmp/state_machine.ipc")
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'PLAYER')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'MODEL')
subscriber_machine.setsockopt_string(zmq.SUBSCRIBE, 'RESET')

# configurações de áudio e tamanho das janelas de tempo pra processar em blocos
TARGET_SAMPLE_RATE = 16000
FRAME_DURATION = 0.032  # 32 milissegundos por bloco
TARGET_FRAME_SIZE = int(TARGET_SAMPLE_RATE * FRAME_DURATION)  # 512 amostras de áudio
CONTEXT_SIZE = 64  # tamanho da memória do modelo vad

# carrega o modelo do silero vad em onnx salvo na mesma pasta do script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAD_MODEL_PATH = os.path.join(SCRIPT_DIR, 'silero_vad.onnx')

# fecha o nó se o arquivo do modelo não existir
if not os.path.exists(VAD_MODEL_PATH):
    print(f"[ERRO ÁUDIO] Modelo VAD não encontrado em: {VAD_MODEL_PATH}", flush=True)
    exit(1)

# abre a sessão do onnx para rodar o detector de voz
vad_session = ort.InferenceSession(VAD_MODEL_PATH)
vad_state = np.zeros((2, 1, 128), dtype=np.float32)
vad_context = np.zeros(CONTEXT_SIZE, dtype=np.float32)

# executa o modelo de voz e calcula se o pedaço de áudio tem voz humana ou volume alto
def is_speech_silero(audio_chunk, threshold=0.2, vol_threshold=0.12):
    global vad_state, vad_context
    
    # prepara o áudio juntando com o contexto da janela anterior
    input_audio = np.concatenate([vad_context, audio_chunk]).reshape(1, -1).astype(np.float32)
    vad_context = audio_chunk[-CONTEXT_SIZE:]
    
    inputs = {
        'input': input_audio,
        'state': vad_state,
        'sr': np.array(TARGET_SAMPLE_RATE, dtype=np.int64)
    }
    
    # roda o silero vad no onnx
    try:
        outputs = vad_session.run(None, inputs)
        prob_speech = float(outputs[0].flatten()[0])
        vad_state = outputs[1]
    except Exception:
        prob_speech = 0.0

    # calcula o volume pico do bloco de áudio
    max_vol = float(np.max(np.abs(audio_chunk)))
    speech_detected = (prob_speech > threshold) or (max_vol > vol_threshold)
    
    return prob_speech, max_vol, speech_detected

# limpa as variáveis de memória do modelo vad quando troca de turno ou finaliza a fala
def reset_vad_state():
    global vad_state, vad_context
    vad_state = np.zeros((2, 1, 128), dtype=np.float32)
    vad_context = np.zeros(CONTEXT_SIZE, dtype=np.float32)

# descobre o índice do microfone que vai usar
mic_idx = find_mic_index()

# descobre a taxa de amostragem padrão do microfone pra não dar erro ao abrir
try:
    dev_info = sd.query_devices(mic_idx, 'input')
    native_sr = int(dev_info['default_samplerate'])
except Exception:
    native_sr = 44100

# tenta abrir o microfone direto em 16khz, se o hardware recusar usa a taxa nativa e converte dps
try:
    capture_sr = TARGET_SAMPLE_RATE
    capture_frame_size = TARGET_FRAME_SIZE
    stream = sd.InputStream(
        device=mic_idx,
        samplerate=capture_sr,
        channels=1,
        dtype='float32',
        blocksize=capture_frame_size
    )
    stream.start()
    print("[ÁUDIO] Capturando em 16 kHz nativo do dispositivo.", flush=True)
except Exception as err:
    capture_sr = native_sr
    capture_frame_size = int(native_sr * FRAME_DURATION)
    print(f"[AVISO ÁUDIO] Dispositivo não aceita 16 kHz diretamente ({err}). Usando taxa nativa ({capture_sr} Hz) com re-amostragem automática.", flush=True)
    stream = sd.InputStream(
        device=mic_idx,
        samplerate=capture_sr,
        channels=1,
        dtype='float32',
        blocksize=capture_frame_size
    )
    stream.start()

# variáveis para controlar se a pessoa está falando e o buffer do áudio
current_turn = 'PLAYER'
speech_buffer = []
is_speaking = False
silence_counter = 0
MAX_SILENCE_CHUNKS = 25  # espera dar mais ou menos 800ms de silêncio para considerar que a frase acabou

last_debug_time = time.time()

try:
    # loop principal de captura de áudio do microfone
    while True:
        try:
            # lê se chegou alguma atualização do turno vinda da máquina de estados sem travar o loop
            while True:
                try:
                    raw_turn = subscriber_machine.recv_string(flags=zmq.NOBLOCK)
                    state_tag = raw_turn.split()[0] if raw_turn else ''
                    
                    if state_tag.startswith('MODEL'):
                        new_turn = 'MODEL'
                    else:
                        new_turn = 'PLAYER'

                    # se mudou de turno e não é mais a vez do jogador limpa os buffers de áudio gravados
                    if new_turn != current_turn:
                        current_turn = new_turn
                        if current_turn != 'PLAYER':
                            speech_buffer.clear()
                            is_speaking = False
                            reset_vad_state()
                except zmq.Again:
                    break

            # lê o pedaço de áudio direto da placa de som
            frame, _ = stream.read(capture_frame_size)

            # só grava e processa o áudio se for a vez do jogador humano
            if current_turn == 'PLAYER':
                raw_audio = frame.flatten()

                # se o microfone gravou em outra taxa tipo 44.1khz converte pra 16khz agora
                if capture_sr != TARGET_SAMPLE_RATE:
                    audio_16k = resample_audio(raw_audio, capture_sr, TARGET_SAMPLE_RATE)
                else:
                    audio_16k = raw_audio

                # verifica se tem fala ou barulho alto no bloco de áudio
                prob_speech, max_vol, speech_detected = is_speech_silero(audio_16k)

                # printa o volume e a probabilidade de fala a cada meio segundo ou quando detecta voz
                if time.time() - last_debug_time > 0.5 or speech_detected:
                    print(f"[DEBUG ÁUDIO] Vol: {max_vol:.4f} | Prob VAD: {prob_speech:.4f}", flush=True)
                    last_debug_time = time.time()

                # se detectou voz começa a guardar o áudio no buffer
                if speech_detected:
                    if not is_speaking:
                        print(f"*** VOZ DETECTADA! (Vol: {max_vol:.2f} | Prob: {prob_speech:.4f}) ***", flush=True)
                        is_speaking = True
                    speech_buffer.append(audio_16k)
                    silence_counter = 0

                # se já estava falando e agora ficou em silêncio vai acumulando a pausa
                elif is_speaking:
                    speech_buffer.append(audio_16k)
                    silence_counter += 1

                    # quando atinge o tempo limite de silêncio junta tudo e manda o áudio completo pro whisper
                    if silence_counter >= MAX_SILENCE_CHUNKS:
                        print("[ÁUDIO] Fim da fala. Enviando para o Whisper...", flush=True)
                        full_audio = np.concatenate(speech_buffer)
                        sender_a.send(full_audio.tobytes())

                        # reseta as variáveis para a próxima frase
                        speech_buffer.clear()
                        is_speaking = False
                        silence_counter = 0
                        reset_vad_state()

        except Exception as e:
            print(f"[ERRO ÁUDIO]: {e}", flush=True)
# garante que fecha a captura do microfone ao encerrar o nó
finally:
    stream.stop()
    stream.close()