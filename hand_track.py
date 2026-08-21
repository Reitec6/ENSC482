import bpy
import socket
import json
import mathutils
import math

# --- CONFIGURATION ---
UDP_IP = "127.0.0.1"
UDP_PORT = 5005
ARMATURE_NAME = "Armature"  # Ensure this matches your Armature name

# EXACT BONE MAPPING (Start ID, End ID)
BONE_MAPPING = {
    "Hand": (0, 9),          # Wrist to Middle Knuckle
    "Hand.001": (5, 6),      # Index Base -> Mid
    "Hand.002": (6, 7),      # Index Mid -> Top
    "Hand.003": (7, 8),      # Index Top -> Tip
    "Hand.004": (9, 10),     # Middle Base -> Mid
    "Hand.005": (10, 11),    # Middle Mid -> Top
    "Hand.006": (11, 12),    # Middle Top -> Tip
    "Hand.007": (13, 14),    # Ring Base -> Mid
    "Hand.008": (14, 15),    # Ring Mid -> Top
    "Hand.009": (15, 16),    # Ring Top -> Tip
    "Hand.010": (17, 18),    # Pinky Base -> Mid
    "Hand.011": (18, 19),    # Pinky Mid -> Top
    "Hand.012": (19, 20),    # Pinky Top -> Tip
    "Hand.013": (1, 2),      # Thumb Base -> Mid
    "Hand.014": (2, 3),      # Thumb Mid -> Top
    "Hand.015": (3, 4),      # Thumb Top -> Tip
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

# --- AUTO-APPLY CONSTRAINTS TO ALL BONES ---
armature = bpy.data.objects.get(ARMATURE_NAME)
if armature and armature.type == 'ARMATURE':
    
    # 1. Unconnect bones in Edit Mode so Stretch To doesn't fail
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='EDIT')
    for edit_bone in armature.data.edit_bones:
        if edit_bone.parent:
            edit_bone.use_connect = False
    bpy.ops.object.mode_set(mode='POSE')
    
    # 2. Apply Constraints
    for bone_name, (start_id, end_id) in BONE_MAPPING.items():
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone:
            # Clear old constraints
            for c in pose_bone.constraints:
                pose_bone.constraints.remove(c)
            
            # Constraint 1: Copy Location (Snaps Head to Start Point)
            loc_c = pose_bone.constraints.new('COPY_LOCATION')
            loc_c.target = bpy.data.objects.get(f"MP_{start_id}")
            
            # Constraint 2: Stretch To (Aims Tail at End Point)
            str_c = pose_bone.constraints.new('STRETCH_TO')
            str_c.target = bpy.data.objects.get(f"MP_{end_id}")
            str_c.volume = 'NO_VOLUME'
            str_c.rest_length = pose_bone.length
            
            # Constraint 3: Locked Track (WRIST ROLL FIX)
            # We use the Index Knuckle (MP_5) as a 3rd point to lock the roll axis
            if bone_name == "Hand": 
                lock_c = pose_bone.constraints.new('LOCKED_TRACK')
                lock_c.target = bpy.data.objects.get("MP_5")
                lock_c.lock_axis = 'LOCK_Y'   # Y is the length of the bone
                lock_c.track_axis = 'TRACK_X' # X points sideways

def update_hand_pose():
    try:
        data, addr = globals()["my_udp_sock"].recvfrom(65535)
        packet = json.loads(data.decode('utf-8'))
        
        # 1. Handle Stop Signal
        if packet.get("stop"):
            print("Received stop signal. Closing socket.")
            globals()["my_udp_sock"].close()
            return None  # Unregisters the Blender timer
            
        # 2. Handle Lost Hand (Reset)
        landmarks = packet.get("landmarks")
        if not landmarks:
            return 0.033 # Skip this frame but keep listening
            
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

    except BlockingIOError:
        pass
    except Exception as e:
        print(f"Error: {e}")
        
    return 0.033 

if bpy.app.timers.is_registered(update_hand_pose):
    bpy.app.timers.unregister(update_hand_pose)
bpy.app.timers.register(update_hand_pose)