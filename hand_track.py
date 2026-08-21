import bpy
import socket
import json
import mathutils
import math

# --- CONFIGURATION ---
UDP_IP = "127.0.0.1"
UDP_PORT = 5005
UPDATE_INTERVAL = 1.0 / 60.0 # Update Blender at up to 30 times per second.
ARMATURE_NAME = "Armature"  # Ensure this matches your Armature name

# EXACT BONE MAPPING (Start ID, End ID)
BONE_MAPPING = {
    "Hand": (0, 9),          
    "Hand.001": (5, 6),      
    "Hand.002": (6, 7),      
    "Hand.003": (7, 8),      
    "Hand.004": (9, 10),     
    "Hand.005": (10, 11),    
    "Hand.006": (11, 12),    
    "Hand.007": (13, 14),    
    "Hand.008": (14, 15),    
    "Hand.009": (15, 16),    
    "Hand.010": (17, 18),    
    "Hand.011": (18, 19),    
    "Hand.012": (19, 20),    
    "Hand.013": (1, 2),      
    "Hand.014": (2, 3),      
    "Hand.015": (3, 4),      
}

# --- PLANE ALIGNMENT ROTATION ---
ROTATION_MATRIX = mathutils.Euler((math.radians(90), 0, math.radians(-90)), 'XYZ').to_matrix()

# --- SOCKET SETUP ---
if "my_udp_sock" in globals():
    try: globals()["my_udp_sock"].close()
    except: pass

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(False)
globals()["my_udp_sock"] = sock

# --- AUTO-CREATE TARGET EMPTIES ---
for i in range(21):
    empty_name = f"MP_{i}"
    if empty_name not in bpy.data.objects:
        empty_obj = bpy.data.objects.new(empty_name, None)
        empty_obj.empty_display_type = 'SPHERE'
        empty_obj.empty_display_size = 0.05
        bpy.context.collection.objects.link(empty_obj)

# --- AUTO-APPLY CONSTRAINTS (SAFE MODE) ---
armature = bpy.data.objects.get(ARMATURE_NAME)
if armature and armature.type == 'ARMATURE':
    
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='POSE')
    
    for bone_name, (start_id, end_id) in BONE_MAPPING.items():
        pose_bone = armature.pose.bones.get(bone_name)
        
        # ONLY apply constraints if the bone doesn't already have them!
        if pose_bone and len(pose_bone.constraints) == 0:
            
            # Constraint 1: Copy Location (Snaps Head to Start Point)
            loc_c = pose_bone.constraints.new('COPY_LOCATION')
            loc_c.target = bpy.data.objects.get(f"MP_{start_id}")
            
            # Constraint 2: Stretch To (Aims Tail at End Point)
            str_c = pose_bone.constraints.new('STRETCH_TO')
            str_c.target = bpy.data.objects.get(f"MP_{end_id}")
            str_c.volume = 'NO_VOLUME'
            str_c.rest_length = pose_bone.length
            
            # Constraint 3: Locked Track (WRIST ROLL FIX)
            if bone_name == "Hand": 
                lock_c = pose_bone.constraints.new('LOCKED_TRACK')
                lock_c.target = bpy.data.objects.get("MP_5")
                lock_c.lock_axis = 'LOCK_Y'   
                lock_c.track_axis = 'TRACK_Z'

# Gesture stability settings
GESTURE_CONFIRM_FRAMES = 4
GESTURE_RELEASE_FRAMES = 8

if "last_gesture" not in globals():
    globals()["last_gesture"] = "NONE"
if "candidate_gesture" not in globals():
    globals()["candidate_gesture"] = "NONE"
if "candidate_frames" not in globals():
    globals()["candidate_frames"] = 0
if "none_frames" not in globals():
    globals()["none_frames"] = 0

def update_hand_pose():
    # Drain socket buffer to prevent lag, keeping only the most recent frame
    latest_packet = None
    while True:
        try:
            data, addr = globals()["my_udp_sock"].recvfrom(65535)
            # FIX: Properly assign the parsed JSON to latest_packet
            latest_packet = json.loads(data.decode('utf-8'))
        except BlockingIOError:
            break
            
    # No new camera frame this Blender update.
    if latest_packet is None:
        return UPDATE_INTERVAL
            
    packet = latest_packet    
        
    # 1. Handle Stop Signal
    if packet.get("stop"):
        print("Received stop signal. Closing socket.")
        globals()["my_udp_sock"].close()
        return None  # Unregisters the Blender timer
            
    # ==============================================================================
    # GESTURE STABILITY FILTER
    # ==============================================================================
    raw_gesture = packet.get("gesture", "NONE")
    stable_gesture = globals().get("last_gesture", "NONE")
    candidate_gesture = globals().get("candidate_gesture", "NONE")
    candidate_frames = globals().get("candidate_frames", 0)
    none_frames = globals().get("none_frames", 0)
            
    # Keep an active gesture during a few accidental NONE frames.
    if raw_gesture == "NONE" and stable_gesture != "NONE":
        none_frames += 1
        globals()["none_frames"] = none_frames

        if none_frames < GESTURE_RELEASE_FRAMES:
            gesture = stable_gesture       # Keep the old detected gesture.
        else:
            gesture = "NONE"               # Release only after sustained absence.
            globals()["none_frames"] = 0
            globals()["candidate_frames"] = 0

    else: 
        globals()["none_frames"] = 0

        # If the current raw gesture is already active, keep it immediately.
        if raw_gesture == stable_gesture:
            gesture = stable_gesture
            globals()["candidate_gesture"] = raw_gesture
            globals()["candidate_frames"] = 0

        # Otherwise, require the new gesture to be repeated for several frames.
        else:
            if raw_gesture == candidate_gesture:
                candidate_frames += 1
            else:
                candidate_gesture = raw_gesture
                candidate_frames = 1

            globals()["candidate_gesture"] = candidate_gesture
            globals()["candidate_frames"] = candidate_frames

            if candidate_frames >= GESTURE_CONFIRM_FRAMES:
                gesture = raw_gesture
                globals()["candidate_frames"] = 0
            else:
                gesture = stable_gesture   # Ignore a short, noisy change.

    # ==============================================================================
    # PRINT ONLY WHEN THE STABLE GESTURE CHANGES
    # ==============================================================================
    if gesture != stable_gesture:
        gesture_labels = {
            "PEACE": "Peace Sign",
            "CLOSED_FIST": "Closed Fist",
            "THUMBS_UP": "Thumbs Up",
        }

        if stable_gesture != "NONE":
            print(f"<< [GESTURE END] {gesture_labels.get(stable_gesture, stable_gesture)} released")

        if gesture != "NONE":
            print(f">> [GESTURE START] {gesture_labels.get(gesture, gesture)} detected")

        globals()["last_gesture"] = gesture

    if armature:
        armature["gesture"] = gesture
        armature["gesture_confidence"] = packet.get("confidence", 0.0)
                
    # 2. Handle Lost Hand (Reset)
    landmarks = packet.get("landmarks")
    if not landmarks:
        return UPDATE_INTERVAL # Skip this frame but keep listening
            
    # 3. Parse the new list of lists format
    pts = {}
    for idx, lm in enumerate(landmarks):
        # lm is [x, y, z]
        raw_vec = mathutils.Vector((lm[0] - 0.5, lm[2], -(lm[1] - 0.5)))
        rotated_vec = ROTATION_MATRIX @ raw_vec
        pts[idx] = rotated_vec * 10.0  # Scale factor

    # Update empty locations
    for idx, vec in pts.items():
        empty = bpy.data.objects.get(f"MP_{idx}")
        if empty:
            empty.location = vec
            
    return UPDATE_INTERVAL 

if bpy.app.timers.is_registered(update_hand_pose):
    bpy.app.timers.unregister(update_hand_pose)
bpy.app.timers.register(update_hand_pose)
