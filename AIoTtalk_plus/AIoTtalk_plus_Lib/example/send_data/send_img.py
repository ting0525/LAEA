import sys
try:
    import cv2 as cv
except ImportError:
    cv = None
import numpy as np
# import airsim
import threading
import json
import os
import time
import random
import signal
from functools import partial

# 建置完的 python module 存放在 RTP/build 下
# MyTool_pybind11.cpython-38-x86_64-linux-gnu.so 檔
# add python library path
current_dir = os.path.dirname(os.path.abspath(__file__))
rtp_build_path = os.path.join(current_dir, '../../RTP/build')
sys.path.append(os.path.abspath(rtp_build_path))

from MyTool_pybind11 import RTPSession, Data_Wrapper, CodecParam

import signal
import sys

def handle_sigterm(signum, frame):
    print("Received SIGTERM, exiting gracefully...")
    sys.exit(0)

def run_in_thread(function):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=function, args=args)
        thread.start()
    return wrapper

def signal_handler(stop_event, thread, sig, frame):
    print(f"Received signal {sig}. Setting stop_event...")
    stop_event.set()
    thread.join()

def get_resolution_from_media(media):
    try:
        first_payload = next(iter(media["payload_type"].values()))
        resolution = first_payload.get("params", {}).get("resolution", "640*480")
        width, height = resolution.split("*")
        return int(width), int(height)
    except Exception:
        return 640, 480

def generate_synthetic_frame(index, width, height):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[..., 0] = (index * 17) % 255
    frame[..., 1] = (index * 31) % 255
    gradient = np.linspace(0, 255, width, dtype=np.uint8)
    frame[..., 2] = np.tile(gradient, (height, 1))
    return frame

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)

    local_device_params = json.loads(sys.argv[1])
    remote_device_params = json.loads(sys.argv[2])
    client_id = sys.argv[3] if len(sys.argv) > 3 else 'default_client'
    weight_file = sys.argv[4] if len(sys.argv) > 4 else '___.pt'
    data_src = sys.argv[5] if len(sys.argv) > 5 else '1400x788'
    
    print("Got Local device params: ")
    print(local_device_params)
    print("Got Remote device params: ")
    print(remote_device_params)
    
    local_device_media = local_device_params["media"]
    remote_device_media = remote_device_params["media"]
    rtp_session = RTPSession()
    
    local_ip = local_device_media[0]["ip_address"]
    remote_ip = remote_device_media[0]["ip_address"]
    
    ret = rtp_session.create_session(local_ip, remote_ip)
    media_stream_num = 0
    
    for l_m, r_m in zip(local_device_media, remote_device_media):
        media_type = l_m["media_type"]
        remote_port = r_m["port"]
        local_port = l_m["port"]
        direction = l_m["direction"]

        first_payload = next(iter(l_m["payload_type"].items()))
        payload_type_id, codec_params = first_payload
        
        codec = codec_params.get("codec", "").split("/")[0]
        params = codec_params.get("params", "")

        _codec_param = CodecParam(int(payload_type_id), str(codec), params)
        ret = rtp_session.create_stream(
            media_stream_num, local_port, remote_port,
            media_type + str("_stream"),
            direction,
            media_type,
            [_codec_param]
        )

    print(f"\n====================================\n[TIME] t6: {time.time()}\n====================================\n")

    directory = '/home/wmnet/chuchun/RTPyolo/datasets/' + data_src + '/images'
    synthetic_mode = cv is None or not os.path.isdir(directory)
    width, height = get_resolution_from_media(local_device_media[0])

    shared_img_list = []
    list_lock = threading.Lock()
    stop_event = threading.Event()
    inference_thread = None
    if not synthetic_mode:
        from inference import start_conn
        inference_thread = threading.Thread(
            target=start_conn,
            args=(client_id, weight_file, shared_img_list, list_lock, stop_event)
        )
        inference_thread.start()

    signal_handler_with_event = partial(signal_handler, stop_event, inference_thread) if inference_thread is not None else None

    if signal_handler_with_event is not None:
        signal.signal(signal.SIGTERM, signal_handler_with_event)
    # signal.signal(signal.SIGINT, signal_handler_with_event) # For Ctrl+C

    print("Main thread started. Press Ctrl+C to exit.")
    try:
        if synthetic_mode:
            print("Synthetic media mode enabled")
            for i in range(30):
                bgr_image = generate_synthetic_frame(i, width, height)
                image_data = Data_Wrapper(bgr_image)
                rtp_session.send_data(0, image_data, True)
                print(f"===== synthetic frame {i} =====")
                time.sleep(1)
        else:
            for i, filename in enumerate(os.listdir(directory)):
                file_path = os.path.join(directory, filename)

                bgr_image = cv.imread(file_path)
                if bgr_image is None:
                    continue
                image_data = Data_Wrapper(bgr_image)
                rtp_session.send_data(0, image_data, True)
                with list_lock:
                    shared_img_list.append(file_path)

                print("===== " + str(i) + " : " + filename + " =====")

                time.sleep(random.randint(1, 3))
    except KeyboardInterrupt:
        print("Main thread caught KeyboardInterrupt. Exiting...")
        stop_event.set()
    finally:
        if inference_thread is not None:
            inference_thread.join()
        print("Main thread finished.")
