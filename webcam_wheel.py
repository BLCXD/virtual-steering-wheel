import cv2
import mediapipe as mp
import math
import vgamepad as vg
import time
import numpy as np

def create_gamepad():
    """ Create the virtual Xbox 360 gamepad with retries. """
    for attempt in range(1, 11):
        try:
            gp = vg.VX360Gamepad()
            print(f"✅ Virtual Xbox 360 gamepad created (attempt {attempt})")
            return gp
        except AssertionError as e:
            print(f"! Gamepad creation failed (attempt {attempt}/10): {e}")
            time.sleep(0.5)
    raise RuntimeError("Could not create virtual Xbox 360 gamepad. Is ViGEmBus installed?")

def main():
    # Initialize MediaPipe Hands
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        min_detection_confidence=0.7, 
        min_tracking_confidence=0.7, 
        max_num_hands=2
    )
    
    gamepad = create_gamepad()
    
    # Try different camera indices and backends if default fails
    cap = None
    for index in [0, 1, 2]:
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            print(f"✅ Camera found at index {index}")
            break
        cap.release()
        
        # Try DirectShow backend on Windows
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            print(f"✅ Camera found at index {index} (DirectShow)")
            break
        cap.release()
    
    if cap is None or not cap.isOpened():
        print("❌ Error: Could not open any webcam. Please ensure a webcam is connected, enabled, and not in use by another app.")
        return
    
    print("🚗 Virtual Steering Wheel Started!")
    print("Show both hands to the camera to steer.")
    print("Press 'ESC' to exit.")

    # Smoothing variables
    smoothed_steering = 0.0
    smoothing_factor = 0.2

    while cap.isOpened():
        success, image = cap.read()
        if not success:
            print("Ignoring empty camera frame.")
            continue

        # Flip the image horizontally for a later selfie-view display
        image = cv2.flip(image, 1)
        h, w, c = image.shape

        # Convert the BGR image to RGB
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        # Process the image and find hands
        results = hands.process(image_rgb)
        
        if results.multi_hand_landmarks and len(results.multi_hand_landmarks) == 2:
            # We need to distinguish left and right hand based on x-coordinate
            hand1 = results.multi_hand_landmarks[0].landmark[mp_hands.HandLandmark.MIDDLE_FINGER_MCP]
            hand2 = results.multi_hand_landmarks[1].landmark[mp_hands.HandLandmark.MIDDLE_FINGER_MCP]
            
            x1, y1 = int(hand1.x * w), int(hand1.y * h)
            x2, y2 = int(hand2.x * w), int(hand2.y * h)
            
            # Ensure x1, y1 is the left hand (smaller x)
            if x1 > x2:
                x1, y1, x2, y2 = x2, y2, x1, y1
                
            dx = x2 - x1
            dy = y2 - y1
            
            # Calculate angle in degrees
            angle = math.degrees(math.atan2(dy, dx))
            
            # Map angle to steering value (-1.0 to 1.0)
            # -45 degrees -> -1.0 (left), 45 degrees -> 1.0 (right)
            max_angle = 45.0
            raw_steering = angle / max_angle
            
            # Clamp between -1.0 and 1.0
            raw_steering = max(min(raw_steering, 1.0), -1.0)
            
            # Apply smoothing
            smoothed_steering = (smoothed_steering * (1.0 - smoothing_factor)) + (raw_steering * smoothing_factor)
            
            # Apply to gamepad
            gamepad.left_joystick_float(x_value_float=smoothed_steering, y_value_float=0.0)
            
            # --- Draw the "Imagined" Steering Wheel ---
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            radius = int(math.hypot(dx, dy) / 2)
            
            # Draw the wheel circle
            cv2.circle(image, (center_x, center_y), radius, (0, 255, 255), 4)
            
            # Draw the steering column / spokes
            cv2.line(image, (x1, y1), (x2, y2), (0, 255, 255), 4)
            cv2.circle(image, (center_x, center_y), 10, (0, 0, 255), -1)
            
            # Display steering percentage
            steer_percent = int(smoothed_steering * 100)
            cv2.putText(image, f"Steering: {steer_percent}%", (center_x - 50, center_y - radius - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            gamepad.update()
        else:
            # If no hands, return to center
            smoothed_steering = (smoothed_steering * (1.0 - smoothing_factor))
            gamepad.left_joystick_float(x_value_float=smoothed_steering, y_value_float=0.0)
            gamepad.update()
            
            cv2.putText(image, "Show both hands to steer", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        # Show the image
        cv2.imshow('Virtual Steering Wheel', image)
        
        # Exit on ESC
        if cv2.waitKey(5) & 0xFF == 27:
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
