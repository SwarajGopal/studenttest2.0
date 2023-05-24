from flask import Flask, render_template, redirect, url_for, Response, request, jsonify
import cv2
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import socket
import struct
import pickle
import threading
import pyautogui
import numpy as np
import platform
import time
import datetime
import win32api
import win32con
import win32file
import time
import datetime
import os

app = Flask(__name__)
camera = cv2.VideoCapture(0)

student_name = None
client_socket = None
encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]


HOST = '192.168.192.54'
PORT = 63333

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/studentlogin', methods=['GET', 'POST'])
def studentlogin():
    global student_name
    if request.method == 'POST':
        student_name = request.form['student_name']
        return redirect(url_for('student', name=student_name))

    return render_template('studentlogin.html')


@app.route('/studentsignup')
def studentsignup():
    return render_template('studentsignup.html')


# Constants for defining the movement threshold and counter
MOVEMENT_THRESHOLD = 85
MOVEMENT_COUNTER_THRESHOLD = 5

# Initialize Firebase app
cred = credentials.Certificate('proctor-watch-firebase-adminsdk-r9fpf-a0c5e8e767.json')
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://proctor-watch-default-rtdb.firebaseio.com'
})

# Get a reference to the Firebase Realtime Database
db_ref = db.reference()


def send_warning_message(student_name):
    try:
        pc_name = os.environ['COMPUTERNAME']
        warning_data = {
            'message': f'{student_name} on PC is looking away from the screen',
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        db_ref.child('warnings').push(warning_data)
    except Exception as e:
        print('Error sending warning message:', str(e))


def gen_frames(student_name):
    prev_face_center = None
    movement_counter = 0

    while True:
        success, frame = camera.read()  # read the camera frame
        if not success:
            break
        else:
            detector = cv2.CascadeClassifier('Haarcascades/haarcascade_frontalface_default.xml')
            faces = detector.detectMultiScale(frame, 1.1, 7)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if len(faces) > 0:
                (x, y, w, h) = faces[0]
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                roi_gray = gray[y:y + h, x:x + w]
                roi_color = frame[y:y + h, x:x + w]

                # Calculate the center of the face
                face_center = (x + w // 2, y + h // 2)

                if prev_face_center is not None:
                    # Calculate the horizontal distance moved by the face
                    movement_distance = face_center[0] - prev_face_center[0]

                    if abs(movement_distance) > MOVEMENT_THRESHOLD:
                        if movement_distance > 0:
                            movement_counter += 1
                            if movement_counter >= MOVEMENT_COUNTER_THRESHOLD:
                                send_warning_message(student_name)
                                movement_counter = 0
                        else:
                            movement_counter += 1
                            if movement_counter >= MOVEMENT_COUNTER_THRESHOLD:
                                send_warning_message(student_name)
                                movement_counter = 0

                # Update the previous face center
                prev_face_center = face_center

            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@app.route('/student')
def student():
    student_name = request.args.get('name')
    if student_name:
        # Send warning message to Firebase
        send_warning_message(student_name)
        return render_template('student.html', name=student_name)


@app.route('/video_feed')
def video_feed():
    student_name = request.args.get('name')  # Get the student name from the query parameters
    return Response(gen_frames(student_name), mimetype='multipart/x-mixed-replace; boundary=frame')


# Check the system platform
system_platform = platform.system()

if system_platform == 'Windows':
    # Define a set to store the detected USB devices
    detected_devices = set()

    # Define a dictionary to store the last detection time for each USB device
    last_detection_times = {}

    # Define a function that checks for the insertion of USB devices and sends a warning message to Firebase
    def check_usb_insertion(student_name):
        
        drives = win32api.GetLogicalDriveStrings()
        drives = drives.split('\000')[:-1]
        for drive in drives:
            drive_type = win32file.GetDriveType(drive)
            if drive_type == win32con.DRIVE_REMOVABLE:
                if drive not in detected_devices:
                    print(f"USB device inserted: {drive}")
                    detected_devices.add(drive)
                    last_detection_times[drive] = datetime.datetime.now()  # Store the current time of detection
                    send_usb_warning_message(student_name, drive)
                    return jsonify({"message": "USB detected"})
                else:
                    last_detection_time = last_detection_times.get(drive)
                    if last_detection_time and (datetime.datetime.now() - last_detection_time).total_seconds() >= 60:
                        print(f"USB device reinserted after 1 minute: {drive}")
                        last_detection_times[drive] = datetime.datetime.now()  # Update the last detection time
                        send_usb_warning_message(student_name, drive)
                        return jsonify({"message": "USB detected"})
        return jsonify({"message": "No USB detected"})

    def send_usb_warning_message(student_name, device_path):
        try:
            pc_name = os.environ['COMPUTERNAME']
            warning_data = {
                'message': f'User has inserted a USB device on PC :{pc_name} ',
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            db_ref.child('warnings').push(warning_data)
        except Exception as e:
            print('Error sending USB warning message:', str(e))

    @app.route('/check_usb/<student_name>')
    def check_usb(student_name):

        student_name = request.args.get('name')
        result = check_usb_insertion(student_name)
        return result if result else ""

elif system_platform == 'Linux':
    import pyudev
    # Define a set to store the detected USB devices
    detected_devices = set()

    # Define a dictionary to store the last detection time for each USB device
    last_detection_times = {}

    # Create a context and monitor for USB devices
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='usb')

    def send_usb_warning_message(student_name, device_path):
        try:
            pc_name = os.environ['COMPUTERNAME']
            warning_data = {
                'message': f'User has inserted a USB device on PC :{pc_name} ',
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            db_ref.child('warnings').push(warning_data)
        except Exception as e:
            print('Error sending USB warning message:', str(e))

    @app.route('/check_usb/<student_name>')
    def check_usb(student_name):
        
        for device in iter(monitor.poll, None):
            if device.action == 'add':
                device_path = device.device_path
                if device_path not in detected_devices:
                    print('{} connected'.format(device))
                    detected_devices.add(device_path)
                    last_detection_times[device_path] = datetime.datetime.now()  # Store the current time of detection
                    send_usb_warning_message(student_name, device_path)
                    return jsonify({"message": "USB detected"})
                else:
                    last_detection_time = last_detection_times.get(device_path)
                    if last_detection_time and (datetime.datetime.now() - last_detection_time).total_seconds() >= 60:
                        print('{} reinserted after 1 minute'.format(device))
                        last_detection_times[device_path] = datetime.datetime.now()  # Update the last detection time
                        send_usb_warning_message(student_name, device_path)
                        return jsonify({"message": "USB detected"})
            time.sleep(1)
        return jsonify({"message": "No USB detected"})

else:
    print("Unsupported platform: {}".format(system_platform))
    result = None


def connect_to_server():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        client_socket.connect(('192.168.192.54', 63333))
        return client_socket
    except ConnectionRefusedError:
        print("Error: Connection refused. Retrying in 5 seconds...")
        time.sleep(5)
        return connect_to_server()
    except Exception as e:
        print(f"Error occurred while connecting: {str(e)}")
        exit(1)

def send_frame(client_socket):
    connection = client_socket.makefile('wb')

    screen_width, screen_height = pyautogui.size()
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]

    while True:
        # Capture the screen
        screen = pyautogui.screenshot()
        frame = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

        # Resize the frame if needed
        frame = cv2.resize(frame, (320, 240))

        # Encode and send the frame
        result, frame = cv2.imencode('.jpg', frame, encode_param)
        data = pickle.dumps(frame, 0)
        size = len(data)

        try:
            client_socket.sendall(struct.pack(">L", size) + data)
        except Exception as e:
            print(f"Error occurred while sending frame: {str(e)}")
            break

        time.sleep(0.1)  # Add a delay of 0.1 seconds between frames

    client_socket.close()

def run_client():
    while True:
        client_socket = connect_to_server()
        send_frame(client_socket)

# Create a thread for the client code
client_thread = threading.Thread(target=run_client)

# Start the client thread
client_thread.start()


if __name__ == '__main__':
    app.run(debug=True)
