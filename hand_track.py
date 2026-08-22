import bpy
import socket
import json
import mathutils
import math

# --- CONFIGURATION ---
UDP_IP = "127.0.0.1"
UDP_PORT = 5005
UPDATE_INTERVAL = 1.0 / 30.0
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
            # We use the Index Knuckle (MP_5) as a 3rd point to lock the roll axis
            if bone_name == "Hand": 
                lock_c = pose_bone.constraints.new('LOCKED_TRACK')
                lock_c.target = bpy.data.objects.get("MP_5")
                lock_c.lock_axis = 'LOCK_Y'   # Y is the length of the bone
                lock_c.track_axis = 'TRACK_Z' # Z points sideways


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
    
# --- SIMPLE OBJECT INTERACTION ---

FLOOR_Z = -2.2  # Temporary value; replaced once the hand is tracked.
FLOOR_SIZE = 10.0
FLOOR_DROP_FROM_PALM = 1.05
HAND_FLOOR_CLEARANCE = 0.04
INTERACTION_DEPTH_Y = 0.0

PALM_HIT_RADIUS = 0.42
PUSH_BOX_RADIUS = 0.80
BALL_RADIUS = 0.60
GRAB_ASSIST_RADIUS = 1.20

GRAVITY = mathutils.Vector((0.0, 0.0, -7.0))
PUSH_STRENGTH = 0.60
THROW_STRENGTH = 2.00
MAX_THROW_SPEED = 8.0

if "object_velocities" not in globals():
    globals()["object_velocities"] = {}

if "previous_palm_position" not in globals():
    globals()["previous_palm_position"] = None

if "smoothed_palm_velocity" not in globals():
    globals()["smoothed_palm_velocity"] = mathutils.Vector((0, 0, 0))

if "grabbed_ball" not in globals():
    globals()["grabbed_ball"] = False

if "ball_grab_offset" not in globals():
    globals()["ball_grab_offset"] = mathutils.Vector((0, 0, 0))

if "ball_release_frames" not in globals():
    globals()["ball_release_frames"] = 0
    
if "palm_velocity_history" not in globals():
    globals()["palm_velocity_history"] = []

globals()["floor_aligned_to_hand"] = False


def set_colour(obj, colour):
    if not obj.active_material:
        material = bpy.data.materials.new(f"{obj.name}_Material")
        obj.data.materials.append(material)

    obj.active_material.diffuse_color = colour


def create_scene_object(name, object_type, location, radius, colour):
    obj = bpy.data.objects.get(name)

    if not obj:
        if object_type == "CUBE":
            bpy.ops.mesh.primitive_cube_add(size=1, location=location)
            obj = bpy.context.active_object
            obj.scale = (0.70, 0.70, 0.70)

        elif object_type == "SPHERE":
            bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=location)
            obj = bpy.context.active_object

        obj.name = name

    obj["hitbox_radius"] = radius
    set_colour(obj, colour)
    return obj


def create_interaction_scene():
    # Switch from Pose Mode before adding mesh objects.
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    floor = bpy.data.objects.get("InteractionFloor")
    if not floor:
        bpy.ops.mesh.primitive_cube_add(
            size=1,
            location=(0, 0, FLOOR_Z - 0.10),
        )
        floor = bpy.context.active_object
        floor.name = "InteractionFloor"
        floor.scale = (FLOOR_SIZE, FLOOR_SIZE, 0.15)
        set_colour(floor, (0.06, 0.24, 0.42, 1.0))

    # Blue cube: push only.
    create_scene_object(
        "PushBox",
        "CUBE",
        (-1.7, INTERACTION_DEPTH_Y, FLOOR_Z + PUSH_BOX_RADIUS),
        PUSH_BOX_RADIUS,
        (0.12, 0.42, 0.95, 1.0),
    )

    # Orange ball: grab and throw.
    create_scene_object(
        "ThrowBall",
        "SPHERE",
        (1.7, INTERACTION_DEPTH_Y, FLOOR_Z + BALL_RADIUS),
        BALL_RADIUS,
        (0.95, 0.28, 0.10, 1.0),
    )


def xz_distance(a, b):
    """Camera-facing interaction plane; ignores unreliable depth Y."""
    return mathutils.Vector((
        a.x - b.x,
        0.0,
        a.z - b.z,
    ))


def update_palm_velocity():
    palm = bpy.data.objects.get("MP_0")
    if not palm:
        return mathutils.Vector((0, 0, 0))

    current = palm.location.copy()
    previous = globals()["previous_palm_position"]

    if previous is None:
        raw_velocity = mathutils.Vector((0, 0, 0))
    else:
        raw_velocity = (current - previous) / UPDATE_INTERVAL

    # Smooth webcam noise before using movement for physics.
    raw_velocity.y = 0.0
    smoothed = globals()["smoothed_palm_velocity"].lerp(raw_velocity, 0.25)

    globals()["previous_palm_position"] = current
    globals()["smoothed_palm_velocity"] = smoothed

    # Keep recent motion so a throw uses the movement before the hand opens.
    history = globals()["palm_velocity_history"]
    history.append(smoothed.copy())

    if len(history) > 6:
        history.pop(0)

    return smoothed

def get_throw_velocity():
    history = globals().get("palm_velocity_history", [])

    if not history:
        return mathutils.Vector((0, 0, 0))

    average = mathutils.Vector((0, 0, 0))

    for velocity in history:
        average += velocity

    average /= len(history)
    average.y = 0.0  # Keep throws on the X/Y/Z interaction plane.
    return average

def clamp_speed(velocity, maximum):
    if velocity.length > maximum:
        velocity.normalize()
        velocity *= maximum
    return velocity


def update_simple_interaction(gesture, raw_gesture):
    push_box = bpy.data.objects.get("PushBox")
    ball = bpy.data.objects.get("ThrowBall")
    palm = bpy.data.objects.get("MP_0")

    if not push_box or not ball or not palm:
        return

    palm_velocity = update_palm_velocity()
    velocities = globals()["object_velocities"]

    # ------------------------------------------------------------------
    # PUSH BOX: use palm overlap and momentum only in the contact direction.
    # ------------------------------------------------------------------
    push_delta = xz_distance(push_box.location, palm.location)
    push_distance = push_delta.length
    push_limit = PUSH_BOX_RADIUS + PALM_HIT_RADIUS

    push_velocity = velocities.get("PushBox", mathutils.Vector((0, 0, 0)))

    if push_distance < push_limit:
        normal = (
            push_delta.normalized()
            if push_distance > 0.001
            else mathutils.Vector((0, 0, 1))
        )

        overlap = push_limit - push_distance
        push_box.location += normal * overlap

        toward_box = max(palm_velocity.dot(normal), 0.0)
        push_velocity += normal * toward_box * PUSH_STRENGTH
        # Green while the palm is inside the PushBox hitbox.
        set_colour(push_box, (0.12, 0.95, 0.25, 1.0))
    else:
        set_colour(push_box, (0.12, 0.42, 0.95, 1.0))
        # This was missing: save the push force so the box continues moving.
        
    velocities["PushBox"] = clamp_speed(push_velocity, MAX_THROW_SPEED)
    # ------------------------------------------------------------------
    # GRAB / THROW BALL: a larger magnetic range makes grabbing forgiving.
    # ------------------------------------------------------------------
    ball_delta = xz_distance(ball.location, palm.location)
    ball_distance = ball_delta.length
    grab_range = BALL_RADIUS + GRAB_ASSIST_RADIUS

    if not globals()["grabbed_ball"]:
        if gesture == "CLOSED_FIST" and ball_distance < grab_range:
            globals()["grabbed_ball"] = True

            offset = ball.location - palm.location
            offset.y = 0.0
            globals()["ball_grab_offset"] = offset

            velocities["ThrowBall"] = mathutils.Vector((0, 0, 0))
            globals()["ball_release_frames"] = 0
            print("Grabbed ThrowBall")

    if globals()["grabbed_ball"]:
        # Keep holding unless two raw frames show that the fist opened.
        if raw_gesture == "CLOSED_FIST":
            globals()["ball_release_frames"] = 0
        else:
            globals()["ball_release_frames"] += 1

        if globals()["ball_release_frames"] < 2:
            target = palm.location + globals()["ball_grab_offset"]
            target.y = INTERACTION_DEPTH_Y

            ball.location = ball.location.lerp(target, 0.45)
            set_colour(ball, (0.12, 0.95, 0.25, 1.0))

        else:
            throw_velocity = get_throw_velocity() * THROW_STRENGTH
            throw_velocity.y = 0.0
            velocities["ThrowBall"] = clamp_speed(
                throw_velocity,
                MAX_THROW_SPEED,
            )

            globals()["grabbed_ball"] = False
            globals()["ball_release_frames"] = 0
            set_colour(ball, (0.95, 0.28, 0.10, 1.0))
            print("Thrown ThrowBall")

    # ------------------------------------------------------------------
    # Simple gravity, bounce, and damping for both objects.
    # ------------------------------------------------------------------
    for obj, radius in (
        (push_box, PUSH_BOX_RADIUS),
        (ball, BALL_RADIUS),
    ):
        if obj == ball and globals()["grabbed_ball"]:
            continue

        velocity = velocities.get(obj.name, mathutils.Vector((0, 0, 0)))
        velocity += GRAVITY * UPDATE_INTERVAL
        velocity *= 0.985
        obj.location += velocity * UPDATE_INTERVAL

        # Keep objects on the interaction plane.
        obj.location.y = INTERACTION_DEPTH_Y

        # Floor collision.
        if obj.location.z - radius < FLOOR_Z:
            obj.location.z = FLOOR_Z + radius

            if velocity.z < 0:
                velocity.z *= -0.38

            velocity.x *= 0.82
            velocity.y *= 0.82

        velocities[obj.name] = clamp_speed(velocity, MAX_THROW_SPEED)
create_interaction_scene()


def align_floor_and_objects_to_hand(palm_position):
    global FLOOR_Z

    if globals().get("floor_aligned_to_hand"):
        return

    floor = bpy.data.objects.get("InteractionFloor")
    push_box = bpy.data.objects.get("PushBox")
    ball = bpy.data.objects.get("ThrowBall")

    if not floor or not push_box or not ball:
        return

    # Create a reachable table height below the initial virtual palm.
    FLOOR_Z = palm_position.z - FLOOR_DROP_FROM_PALM

    floor.location = mathutils.Vector((0, 0, FLOOR_Z - 0.15))
    floor.scale = (FLOOR_SIZE, FLOOR_SIZE, 0.15)
    set_colour(floor, (0.06, 0.24, 0.42, 1.0))

    # Put both objects on top of the newly aligned floor.
    push_box.location = mathutils.Vector((
        palm_position.x - 1.1,
        INTERACTION_DEPTH_Y,
        FLOOR_Z + PUSH_BOX_RADIUS,
    ))

    ball.location = mathutils.Vector((
        palm_position.x + 1.1,
        INTERACTION_DEPTH_Y,
        FLOOR_Z + BALL_RADIUS,
    ))

    globals()["object_velocities"]["PushBox"] = mathutils.Vector((0, 0, 0))
    globals()["object_velocities"]["ThrowBall"] = mathutils.Vector((0, 0, 0))
    globals()["floor_aligned_to_hand"] = True

    print("Floor and interaction objects aligned to the virtual hand.")




def update_hand_pose():
    try:
        # Empty the UDP queue and use only the newest camera packet.
        # This prevents Blender from slowly falling behind the webcam.
        latest_packet = None

        while True:
            try:
                data, addr = globals()["my_udp_sock"].recvfrom(65535)
                latest_packet = json.loads(data.decode("utf-8"))
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
            "POINT": "Point",
            "OPEN_PALM": "Open Palm",
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
            # Webcam left/right -> Blender X
            # MediaPipe depth -> Blender Y
            # Webcam up/down -> Blender Z
            pts[idx] = mathutils.Vector((
                (lm[0] - 0.5) * 10.0,
                lm[2] * 15.0,
                -(lm[1] - 0.5) * 10.0,
            ))
        # Position the floor and objects relative to the first tracked palm.
        align_floor_and_objects_to_hand(pts[0])

        # Keep all virtual hand landmarks above the floor.
        lowest_hand_z = min(point.z for point in pts.values())
        minimum_z = FLOOR_Z + HAND_FLOOR_CLEARANCE

        if lowest_hand_z < minimum_z:
            lift_amount = minimum_z - lowest_hand_z

            for point in pts.values():
                point.z += lift_amount
                
        # Update empty locations
        for idx, vec in pts.items():
            empty = bpy.data.objects.get(f"MP_{idx}")
            if empty:
                empty.location = vec

        # Run object interaction once, after all hand landmarks update.
        update_simple_interaction(gesture, raw_gesture)

    except BlockingIOError:
        pass
    except Exception as e:
        print(f"Error: {e}")
        
    return UPDATE_INTERVAL

if bpy.app.timers.is_registered(update_hand_pose):
    bpy.app.timers.unregister(update_hand_pose)
bpy.app.timers.register(update_hand_pose)
