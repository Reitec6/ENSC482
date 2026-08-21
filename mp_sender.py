import cv2
import socket
import json
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_PATH = "hand_landmarker.task"
HOST = "127.0.0.1"
PORT = 5005

# --- MediaPipe setup ---
base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
options = vision.HandLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    num_hands=1,
)
detector = vision.HandLandmarker.create_from_options(options)

# --- UDP socket setup ---
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Which landmark indices connect to which, to draw the "hand skeleton"
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (0, 9), (9, 10), (10, 11), (11, 12),     # middle
    (0, 13), (13, 14), (14, 15), (15, 16),   # ring
    (0, 17), (17, 18), (18, 19), (19, 20),   # pinky
    (5, 9), (9, 13), (13, 17),               # palm
]


def draw_landmarks(frame, landmarks):
    h, w, _ = frame.shape
    points = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]

    for start_idx, end_idx in HAND_CONNECTIONS:
        cv2.line(frame, points[start_idx], points[end_idx], (0, 255, 0), 2)

    for i, (x, y) in enumerate(points):
        cv2.circle(frame, (x, y), 5, (0, 0, 255), -1)
        cv2.putText(frame, str(i), (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

# --- GESTURE DETECTION ---

def landmark_distance(a, b):
    return (
        (a.x - b.x) ** 2 +
        (a.y - b.y) ** 2 +
        (a.z - b.z) ** 2
    ) ** 0.5

def finger_curl_ratio(landmarks, mcp, pip, dip, tip):
    """
    Near 1.0 = finger is straight.
    Near 0.0 = finger is curled back toward the palm.

    This is orientation-independent: it works for upright, sideways,
    and tilted hands.
    """
    bone_length = (
        landmark_distance(landmarks[mcp], landmarks[pip]) +
        landmark_distance(landmarks[pip], landmarks[dip]) +
        landmark_distance(landmarks[dip], landmarks[tip])
    )

    if bone_length == 0:
        return 0.0

    return landmark_distance(landmarks[mcp], landmarks[tip]) / bone_length

def detect_gesture(landmarks):
    index_ratio = finger_curl_ratio(landmarks, 5, 6, 7, 8)
    middle_ratio = finger_curl_ratio(landmarks, 9, 10, 11, 12)
    ring_ratio = finger_curl_ratio(landmarks, 13, 14, 15, 16)
    pinky_ratio = finger_curl_ratio(landmarks, 17, 18, 19, 20)

    # Straight fingers have ratios close to 1.0.
    index_extended = index_ratio > 0.78
    middle_extended = middle_ratio > 0.78
    ring_extended = ring_ratio > 0.78
    pinky_extended = pinky_ratio > 0.78

    # Curled fingers have lower ratios.
    index_folded = index_ratio < 0.72
    middle_folded = middle_ratio < 0.72
    ring_folded = ring_ratio < 0.72
    pinky_folded = pinky_ratio < 0.72

    # Detect whether the thumb is outside the palm area.
    palm_width = landmark_distance(landmarks[5], landmarks[17])

    palm_center_x = (
        landmarks[5].x + landmarks[9].x +
        landmarks[13].x + landmarks[17].x
    ) / 4.0

    palm_center_y = (
        landmarks[5].y + landmarks[9].y +
        landmarks[13].y + landmarks[17].y
    ) / 4.0

    palm_center_z = (
        landmarks[5].z + landmarks[9].z +
        landmarks[13].z + landmarks[17].z
    ) / 4.0

    thumb_to_palm_center = (
        (landmarks[4].x - palm_center_x) ** 2 +
        (landmarks[4].y - palm_center_y) ** 2 +
        (landmarks[4].z - palm_center_z) ** 2
    ) ** 0.5

    thumb_extended = thumb_to_palm_center > palm_width * 0.85

    # 1. Thumbs up: thumb out, other fingers curled.
    if (thumb_extended and index_folded and middle_folded
            and ring_folded and pinky_folded):
        return "THUMBS_UP"

    # 2. Peace: index and middle out; ring, pinky, and thumb tucked.
    if (index_extended and middle_extended and
            ring_folded and pinky_folded and
            not thumb_extended):
        return "PEACE"

    # 3. Point: index out; middle, ring, and pinky curled.
    if (index_extended and middle_folded and
            ring_folded and pinky_folded):
        return "POINT"

    # 4. Open palm: all fingers and thumb extended.
    if (thumb_extended and index_extended and middle_extended
            and ring_extended and pinky_extended):
        return "OPEN_PALM"

    # 5. Closed fist: all fingers curled and thumb not out.
    if (index_folded and middle_folded and
            ring_folded and pinky_folded and
            not thumb_extended):
        return "CLOSED_FIST"

    return "NONE"

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("ERROR: Could not open webcam.")
    exit(1)

print(f"Camera opened. Sending landmarks to {HOST}:{PORT}. Press 'q' in the preview window to quit.")

timestamp = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

    result = detector.detect_for_video(mp_image, timestamp)
    timestamp += 1

    if result.hand_landmarks:
        landmarks = result.hand_landmarks[0]
        draw_landmarks(frame, landmarks)

        detected_gesture = detect_gesture(landmarks)

        landmark_list = [[round(lm.x, 4), round(lm.y, 4), round(lm.z, 4)] for lm in landmarks]

        packet = {
            "landmarks": landmark_list,
            "gesture": detected_gesture, 
            "confidence": 0.0,       
        }

        message = json.dumps(packet).encode("utf-8")
        sock.sendto(message, (HOST, PORT))
        print(f"Sent landmarks, first point: {landmark_list[0]}")
    else:
        reset_packet = {
            "landmarks": None,
            "gesture": "NONE",
            "confidence": 0.0,
        }
        sock.sendto(json.dumps(reset_packet).encode("utf-8"), (HOST, PORT))

    cv2.imshow("Camera", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

# Tell Blender to stop listening and reset before we exit
stop_packet = {"stop": True}
sock.sendto(json.dumps(stop_packet).encode("utf-8"), (HOST, PORT))
print("Sent stop signal to Blender.")

sock.close()