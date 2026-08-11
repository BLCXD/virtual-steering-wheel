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

    gamepad.left_joystick_float(x_value_float=TRIGGER, y_value_float=0)
    # gamepad.right_joystick_float(x_value_float=0, y_value_float=thrust)
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



if __name__ == '__main__':
    # Wrap SSL manually since eventlet does not support ssl_context in `socketio.run()`
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

    socket = eventlet.listen(('192.168.0.174', 9080))
    secure_socket = eventlet.wrap_ssl(socket, certfile="cert.pem", keyfile="key.pem", server_side=True)

    print("🚀 Running secure WebSocket server on https://0.0.0.0:9080")
    eventlet.wsgi.server(secure_socket, app)