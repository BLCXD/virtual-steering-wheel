import eventlet
import eventlet.wsgi
import ssl
import sys
from flask import Flask, render_template, request
from flask_socketio import SocketIO
from engineio.payload import Payload
import vgamepad as vg
import time
import logging
import threading
import cv2
import mediapipe as mp
import math

# Global flag to prioritize webcam steering
WEBCAM_STEERING_ACTIVE = False

# Make console output safe on non-UTF-8 (e.g. cp1250) consoles, so emoji prints don't crash
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Reduce logging overhead
logging.getLogger('socketio').setLevel(logging.ERROR)
logging.getLogger('engineio').setLevel(logging.ERROR)

# Flask app setup
app = Flask(__name__, static_url_path='/static')
app.config['SECRET_KEY'] = 'secret!'

# Increase max payload size
Payload.max_decode_packets = 10000

# Use eventlet for lower latency WebSockets
socketio = SocketIO(app, async_mode='eventlet', logging=False, cors_allowed_origins='*', max_http_buffer_size=10**7)

def create_gamepad():
    """ Create the virtual Xbox 360 gamepad with retries.
    ViGEmBus can transiently fail to attach a target right after install/boot,
    so retry before giving up. """
    for attempt in range(1, 11):
        try:
            gp = vg.VX360Gamepad()
            print(f"✅ Virtual Xbox 360 gamepad created (attempt {attempt})")
            return gp
        except AssertionError as e:
            print(f"! Gamepad creation failed (attempt {attempt}/10): {e}")
            time.sleep(0.5)
    raise RuntimeError("Could not create virtual Xbox 360 gamepad. Is ViGEmBus installed?")


gamepad = create_gamepad()

# Constants for the gamepad 
LAST_UPDATE = 0
UPDATE_INTERVAL = 0.01  # 10ms

@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('index.html')

# Button Mapping
BUTTON_LIST = {
    'dU': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    'dD': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    'dL': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    'dR': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    'start': vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    'back': vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    'LT': vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    'RT': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
    'LS': vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    'RS': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    'G': vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
    'A': vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    'B': vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    'X': vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    'Y': vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
}

@socketio.on('gyro')
def gyro(data):
    """ Process gyroscope input with minimal latency """
    global LAST_UPDATE

    current_time = time.time()
    if current_time - LAST_UPDATE < UPDATE_INTERVAL:
        return  # Skip update if not enough time has passed

    LAST_UPDATE = current_time

    STEERING = data.get('steering', 0)  # Ensure data exists
    y = 0  # Initialize y
    if STEERING >= 45:
        y = 45
    elif STEERING <= -45:
        y = -45
    else:
        y = (STEERING / 45) * 45

    MAX_STEERING = 45
    MULTIPLIER = 100 / MAX_STEERING

    STEERING = max(min(y, MAX_STEERING), -MAX_STEERING)  # Clamp values
    TRIGGER = round((y * MULTIPLIER / 100), 2)  # Normalize

    if not WEBCAM_STEERING_ACTIVE:
        gamepad.left_joystick_float(x_value_float=TRIGGER, y_value_float=0)
        gamepad.update()

    print(f"🎮 Gyro Input: {TRIGGER:.2f} | Steering: {STEERING}")

@socketio.on('buttonPress')
def handle_button_press(data):
    button = data.get("button", "")
    if button in BUTTON_LIST:
        gamepad.press_button(button=BUTTON_LIST[button])
        gamepad.update()
        print(f"🟢 Button {button} pressed")

@socketio.on('buttonTouchStart')
def handle_button_touch_start(data):
    button = data.get("button", "")
    if button == "RT":
        gamepad.right_trigger_float(1)
    elif button == "LT":
        gamepad.left_trigger_float(1)
    elif button in BUTTON_LIST:
        gamepad.press_button(button=BUTTON_LIST[button])

    gamepad.update()
    print(f"🔵 Button {button} long press start")

@socketio.on('buttonTouchEnd')
def handle_button_touch_end(data):
    button = data.get("button", "")
    if button == "RT":
        gamepad.right_trigger_float(0)
    elif button == "LT":
        gamepad.left_trigger_float(0)
    elif button in BUTTON_LIST:
        gamepad.release_button(button=BUTTON_LIST[button])

    gamepad.update()
    print(f"🟠 Button {button} released")


def webcam_steering_loop(gamepad_ref):
    global WEBCAM_STEERING_ACTIVE
    
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        min_detection_confidence=0.7, 
        min_tracking_confidence=0.7, 
        max_num_hands=2
    )
    
    cap = None
    for index in [0, 1, 2]:
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            print(f"✅ Camera found at index {index}")
            break
        cap.release()
        
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            print(f"✅ Camera found at index {index} (DirectShow)")
            break
        cap.release()
    
    if cap is None or not cap.isOpened():
        print("❌ Error: Could not open webcam for steering. Using phone gyro steering only.")
        return
        
    print("🚗 Virtual Steering Wheel Started!")
    print("Show both hands to the camera to steer.")
    
    WEBCAM_STEERING_ACTIVE = True
    smoothed_steering = 0.0
    smoothing_factor = 0.2
    
    while cap.isOpened():
        success, image = cap.read()
        if not success:
            continue
            
        image = cv2.flip(image, 1)
        h, w, c = image.shape
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        results = hands.process(image_rgb)
        
        if results.multi_hand_landmarks and len(results.multi_hand_landmarks) == 2:
            hand1 = results.multi_hand_landmarks[0].landmark[mp_hands.HandLandmark.MIDDLE_FINGER_MCP]
            hand2 = results.multi_hand_landmarks[1].landmark[mp_hands.HandLandmark.MIDDLE_FINGER_MCP]
            
            x1, y1 = int(hand1.x * w), int(hand1.y * h)
            x2, y2 = int(hand2.x * w), int(hand2.y * h)
            
            if x1 > x2:
                x1, y1, x2, y2 = x2, y2, x1, y1
                
            dx = x2 - x1
            dy = y2 - y1
            
            angle = math.degrees(math.atan2(dy, dx))
            max_angle = 45.0
            raw_steering = angle / max_angle
            raw_steering = max(min(raw_steering, 1.0), -1.0)
            
            smoothed_steering = (smoothed_steering * (1.0 - smoothing_factor)) + (raw_steering * smoothing_factor)
            
            gamepad_ref.left_joystick_float(x_value_float=smoothed_steering, y_value_float=0.0)
            
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            radius = int(math.hypot(dx, dy) / 2)
            cv2.circle(image, (center_x, center_y), radius, (0, 255, 255), 4)
            cv2.line(image, (x1, y1), (x2, y2), (0, 255, 255), 4)
            cv2.circle(image, (center_x, center_y), 10, (0, 0, 255), -1)
            steer_percent = int(smoothed_steering * 100)
            cv2.putText(image, f"Steering: {steer_percent}%", (center_x - 50, center_y - radius - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            gamepad_ref.update()
        else:
            smoothed_steering = (smoothed_steering * (1.0 - smoothing_factor))
            gamepad_ref.left_joystick_float(x_value_float=smoothed_steering, y_value_float=0.0)
            gamepad_ref.update()
            cv2.putText(image, "Show both hands to steer", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        cv2.imshow('Virtual Steering Wheel', image)
        if cv2.waitKey(5) & 0xFF == 27:
            break
            
    cap.release()
    cv2.destroyAllWindows()
    WEBCAM_STEERING_ACTIVE = False


if __name__ == '__main__':
    # Wrap SSL manually since eventlet does not support ssl_context in `socketio.run()`
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

    socket = eventlet.listen(('0.0.0.0', 9080))
    secure_socket = eventlet.wrap_ssl(socket, certfile="cert.pem", keyfile="key.pem", server_side=True)

    print("🚀 Running secure WebSocket server on https://0.0.0.0:9080")
    
    # Run the webcam steering in a separate background thread
    threading.Thread(target=webcam_steering_loop, args=(gamepad,), daemon=True).start()
    
    eventlet.wsgi.server(secure_socket, app)