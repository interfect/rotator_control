#!/usr/bin/env python3

import random
import re
import socket
import threading
import urllib.request
from xml.etree import ElementTree

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 4533

MOTOR_URL="http://10.1.203.213"

# Is the elevation axis in the same (1) or opposite (-1) orientation from the
# tilt axis?
MOTOR_ELEVATION_DIRECTION = -1
# Is the azimuth axis in the same (1) or opposite (-1) orientation from the pan
# axis?
MOTOR_AZIMUTH_DIRETION = 1

# Tilt 0 might not be flat. What elevation is tilt 0?
MOTOR_ELEVATION_OFFSET = 0
# Pan 0 might not be due north. What azimuth is motor 0?
MOTOR_AZIMUTH_OFFSET = 90

def talk_to_motor(pan_change, tilt_change) -> tuple[float, float]:
    """
    Send pan and tilt force to the motor, and get back current pan and tilt.
    
    Forces are integers from -31 to 31.
    
    Current angles are floats in degrees.
    """
    
    # Clamp to range
    pan_change = min(max(pan_change, -31), 31)
    tilt_change = min(max(tilt_change, -31), 31)
    
    command_url = f"{MOTOR_URL}/CP_Update.xml?PCmd={pan_change}&TCmd={tilt_change}"
    
    with urllib.request.urlopen(command_url) as response:
        response_xml = response.read().decode('utf-8')
    # The response should look like:
    # <?xml version="1.0" encoding="utf-8"?>
    # <CP_Update>
    #     <PanPos>85.4</PanPos>
    #     <TiltPos>-57.0</TiltPos>
    #     ...
    #     <AutoPatrol>Off</AutoPatrol>
	#     <CPStatusMsg><Type>Info</Type><Text></Text></CPStatusMsg>
    # </CP_Update>
    
    # But sometimes it has invalid XML! If we hit the URL too fast we race and
    # the next to last line with the status is only partially there. So we
    # regex away anything we don't like.
    response_xml = re.sub("</AutoPatrol>.*</CP_Update>", "</AutoPatrol></CP_Update>", response_xml, flags=re.MULTILINE | re.DOTALL)
    root = ElementTree.fromstring(response_xml)
    pan_angle = float(root.find("PanPos").text)
    tilt_angle = float(root.find("TiltPos").text)
    return pan_angle, tilt_angle

def get_control_input(current, target, proportional_scale=1/0.35, limit=8, min_strength=1):
    """
    Get a move value between -31 and 31 to move current towards target.
    """
    # TODO: Be a real PID loop.
    
    # According to the JPTH-13M-PoE manual, each jog unit is 0.35 degrees
    
    difference = target - current
    
    # Get a change from the difference
    change = difference * proportional_scale
    
    # Clamp it
    change = min(max(-limit, change), limit)
    
    if change != 0 and abs(change) < min_strength:
        # Make sure to make the minimum jog that does anything
        change = min_strength if change > 0 else -min_strength
        
    return int(change)
    
def step_towards(target_pan, target_tilt) -> tuple[float, float]:
    """
    Servo the motor towards the given angles.
    
    Returns the current motor angle.
    """
    # TODO: Implement PID control
    start_pan, start_tilt = talk_to_motor(0, 0)
    
    # Round everybody to consistent precision so floats can be equal
    target_pan = round(target_pan, 1)
    target_tilt = round(target_tilt, 1)
    
    # TODO: These should already be rounded
    start_pan = round(start_pan, 1)
    start_tilt = round(start_tilt, 1)
   
    pan_change = get_control_input(start_pan, target_pan)
    tilt_change = get_control_input(start_tilt, target_tilt)
    
    print(f"At {(start_pan, start_tilt)}, want {(target_pan, target_tilt)}, pan by {pan_change}, tilt by {tilt_change}")
    
    # And send it
    return talk_to_motor(pan_change, tilt_change)

def position_keeper_task(mutable_target_pantilt: list[float], mutable_current_pantilt: list[float]):
    """
    Run forever, seeking the target position and updating the current position in place.
    
    Positions are in pan and tilt.
    """
    
    while True:
        # Read out of the mutable target list
        current = step_towards(mutable_target_pantilt[0], mutable_target_pantilt[1])
        # Assign into the mutable current list
        mutable_current_pantilt[0] = current[0]
        mutable_current_pantilt[1] = current[1]

def send_all(data: bytes, send_socket):
    """
    Send all the given bytes over the given socket.
    
    Will retry until all bytes are sent, or the socket is closed.
    
    May deadlock if the other side is waiting for us to read.
    """
    
    while len(data) > 0:
        sent = send_socket.send(data)
        if sent == 0:
            # Socket is closed.
            return
        # Discard data sent already
        data = data[sent:]

def pantilt_to_azel(pantilt: tuple[float, float]) -> tuple[float, float]:
    """
    Convert a motor pan and tilt into an azimuth and elevation.
    """
    
    pan, tilt = pantilt
    
    az = pan * MOTOR_AZIMUTH_DIRETION + MOTOR_AZIMUTH_OFFSET
    el = tilt * MOTOR_ELEVATION_DIRECTION + MOTOR_ELEVATION_OFFSET
    
    # Keep in the 0-360 azimuth range
    if az < 0:
        az += 360
    if az > 360:
        az -= 360
        
    # TODO: Wrap el
    
    return az, el
    
def azel_to_pantilt(azel: tuple[float, float]) -> tuple[float, float]:
    """
    Convert an azimuth and elevation into a motor pan and tilt.
    """
    az, el = azel
    
    pan = (az - MOTOR_AZIMUTH_OFFSET) / MOTOR_AZIMUTH_DIRETION
    tilt = (el - MOTOR_ELEVATION_OFFSET) / MOTOR_ELEVATION_DIRECTION
    
    # Keep in the 
    if pan < 0:
        pan += 360
    if pan > 360:
        pan -= 360
        
    # TODO: Wrap tilt
    
    return pan, tilt
    
    

def handle_command(command_bytes: bytes, client_socket, mutable_target_pantilt: list[int], mutable_current_pantilt: list[int]):
    """
    Handle a rotctld protocol command with its trailing newline.
    
    Send any response over the given socket.
    
    See the PROTOCOL section of https://hamlib.sourceforge.net/html/rotctld.1.html.
    """
    
    command_line = command_bytes.decode('utf-8')
    command_line.strip()
    
    #print(f"Handle command: {command_line}")
    
    parts = command_line.split()
    
    if len(parts) == 0:
        # Nothing was sent.
        return
    
    #print(f"Got command: {parts}")
    
    match parts:
        case ["p" | "\\get_pos"]:
            az, el = pantilt_to_azel(tuple(mutable_current_pantilt))
            response_parts = [az, el]
        case [("P" | "\\set_pos"), az_str, el_str]:
            az = float(az_str)
            el = float(el_str)
            pan, tilt = azel_to_pantilt((az, el))
            mutable_target_pantilt[0] = pan
            mutable_target_pantilt[1] = tilt
            response_parts = ["RPRT 0"]
        case [("S" | "\\stop")]:
            # Declare here to be the target
            mutable_target_pantilt[0] = mutable_current_pantilt[0]
            mutable_target_pantilt[1] = mutable_current_pantilt[1]
            response_parts = ["RPRT 0"]
        case [("K" | "\\park")]:
            # Go to parking location
            mutable_target_pantilt[0] = 0
            mutable_target_pantilt[1] = 0
            response_parts = ["RPRT 0"]
        case _:
            # No other commands supported
            response_parts = ["RPRT -1"]
            
    #print(f"Sending reply: {response_parts}")
        
    # Send our reply
    send_all(('\n'.join([str(p) for p in response_parts]) + "\n").encode('utf-8'), client_socket)
    
    
    

if __name__ == "__main__":
    
    # Define shared state with the background thread
    mutable_target_pantilt = [0.0, 0.0]
    mutable_current_pantilt = [0.0, 0.0]
    
    # Start the background keeper thread to actually aim the motor
    bg_thread = threading.Thread(target=position_keeper_task, args=(mutable_target_pantilt, mutable_current_pantilt), daemon=True)
    
    bg_thread.start()
    print("Started background position keeping thread")
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((LISTEN_HOST, LISTEN_PORT))
    
    # We can only take 1 connection at a time
    server_socket.listen(1)
    
    print(f"Listening on {LISTEN_HOST}:{LISTEN_PORT}...")
    
    while True:
        (client_socket, address) = server_socket.accept()
        
        # Handle client blockingly until they leave
        print(f"Handling connection from {address}")
        buffer = bytes()
        while True:
            data = client_socket.recv(1024)
            if not data:
                print("Client disconnected")
                break
            buffer += data
            
            while b"\n" in buffer:
                # We have a complete command
                delimiter_pos = buffer.index(b"\n")
                # Split buffer at the delimiter, keeping it
                command_bytes = buffer[0:delimiter_pos]
                buffer = buffer[delimiter_pos + 1:]
                
                # Run the command and possibly reply
                handle_command(command_bytes, client_socket, mutable_target_pantilt, mutable_current_pantilt)
                
        
        
    
