import time
import zmq
import serial

# Serial Port Configuration (Leave as None to simulate)
SERIAL_PORT = '/dev/ttyUSB0' 
BAUD_RATE = 115200

def uci_to_coordinates(uci_move):
    """
    Placeholder Function: Converts 'e2e4' to physical XY positions.
    In the future, you will add the millimeter spacing logic of your board here.
    """
    origem = uci_move[:2]
    destino = uci_move[2:]
    return f"MOVE_FROM_{origem}_TO_{destino}"

def main():
    context = zmq.Context()

    # Listens for validated moves coming from the verifier
    sub_verified = context.socket(zmq.SUB)
    sub_verified.connect("ipc:///tmp/verified_state.ipc")
    sub_verified.setsockopt_string(zmq.SUBSCRIBE, "ENGINE_MOVE_VALIDATED")

    # Sends events back to the State Machine (Warns that the Arduino has finished)
    pub_machine = context.socket(zmq.PUB)
    pub_machine.connect("ipc:///tmp/verified_state.ipc") # Uses the same bus as the verifier

    # Tries to connect to the Arduino, if it fails, enters Simulation Mode
    arduino = None
    try:
        arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"[SERIAL] Connected to Arduino on port {SERIAL_PORT}")
        time.sleep(2) # Time for the Arduino to restart after serial connection
    except Exception as e:
        print(f"[SERIAL] Arduino not found on {SERIAL_PORT}. Running in SIMULATION MODE.")

    print("[SERIAL] Serial Node started and waiting for moves...")

    while True:
        try:
            msg = sub_verified.recv_string()
            
            if msg.startswith("ENGINE_MOVE_VALIDATED"):
                _, data = msg.split(" ", 1)
                uci_move, fen = data.split("|")
                
                print(f"\n[SERIAL] Received command to move: {uci_move}")
                comando_fisico = uci_to_coordinates(uci_move)
                
                if arduino:
                    # Sends to the physical Arduino
                    arduino.write(f"{comando_fisico}\n".encode('utf-8'))
                    print(f"[SERIAL] Sent to Arduino: {comando_fisico}")
                    
                    # Keeps reading the response until the Arduino sends a "DONE" (example)
                    while True:
                        resposta = arduino.readline().decode('utf-8').strip()
                        if resposta == "DONE":
                            break
                        time.sleep(0.1)
                else:
                    # Simulation Mode: Pretends the arm took 3 seconds to move
                    print(f"[SERIAL SIMULATION] Moving the robot physically... ({comando_fisico})")
                    time.sleep(3) 

                print("[SERIAL] Movement completed!")
                
                # Publishes to the ZMQ bus that the robot has finished, 
                # so the state_machine can return the turn to the player.
                pub_machine.send_string("ROBOT_DONE")

        except Exception as e:
            print(f"[SERIAL ERROR]: {e}")
            time.sleep(0.1)

if __name__ == "__main__":
    main()