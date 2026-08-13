Based on: https://github.com/n1xsoph1c/virtual-steering-wheel

## Virtual Steering Wheel

This project provides two ways to emulate a steering wheel using your PC:
1. **Webcam (Recommended for PC gaming):** Detects your hands via your webcam and "imagines" a steering wheel, translating your hand movements to virtual gamepad inputs.
2. **Smartphone:** Connect to a local web server using your phone and use its gyroscope.

### Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Make sure you have [ViGEmBus](https://github.com/nefarius/ViGEmBus/releases) installed.

### Running Webcam Steering Wheel
Run the new MediaPipe-based script:
```bash
python webcam_wheel.py
```
Show both hands to your webcam. The app will draw a steering wheel between your hands and steer based on the angle!

### Running Smartphone Server
```bash
python server.py
```
And access the web interface on your phone.

## TO DO:
- remove latency
- Add vibrartion
- Smoothen Input 
- Figure out another way to fix input lag
- Setup deadzone settings and a sweet spot for steering 