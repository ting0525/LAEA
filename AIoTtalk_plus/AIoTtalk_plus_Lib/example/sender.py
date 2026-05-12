import sys
import cv2 as cv
import numpy as np
import airsim
import threading
import json
import os

# 建置完的 python module 存放在 RTP/build 下
# MyTool_pybind11.cpython-38-x86_64-linux-gnu.so 檔
# add python library path
current_dir = os.path.dirname(os.path.abspath(__file__))
rtp_build_path = os.path.join(current_dir, '../RTP/build')
sys.path.append(os.path.abspath(rtp_build_path))

from MyTool_pybind11 import RTPSession, Data_Wrapper, CodecParam



def run_in_thread(function):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=function, args=args)
        thread.start()
    return wrapper

if __name__ == "__main__":
    local_device_params = json.loads(sys.argv[1])
    remote_device_params = json.loads(sys.argv[2])
    
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

    # rtp_session = RTPSession()
    # ret = rtp_session.create_session("127.0.0.1", "127.0.0.1")
    # if(ret != 0):
    #     exit()
    
    # codec_param = CodecParam(96, "H264", {"resolution": "640*480"})
    # ret = rtp_session.create_stream(
    #     0, 12000, 13000, 
    #     "rgb_stream", 
    #     "sendonly",
    #     "video",
    #     [codec_param] 
    # )

    # codec_param = CodecParam(97, "Zdepth", {"resolution": "640*480"})
    # ret = rtp_session.create_stream(
    #     1, 21000, 20000, 
    #     "depth_stream", 
    #     "sendonly",
    #     "depth_image",
    #     [codec_param] 
    # )

    # codec_param = CodecParam(100, "raw_bytes", {})
    # ret = rtp_session.create_stream(
    #     2, 9000, 8000, 
    #     "raw_stream", 
    #     "sendonly",
    #     "raw_bytes",
    #     [codec_param]
    # )



    # ret = rtp_session.create_stream(
    #     1, 21000, 20000,
    #     "depth_stream",
    #     "sendonly",
    #     "depth_image", {"Zdepth": 97},    
    #     {"resolution": "640*480"}
    # )

    # ret = rtp_session.create_stream(
    #     2, 9000, 8000, 
    #     "raw_stream", 
    #     "sendonly",
    #     "raw_bytes", {"raw_bytes": 100}, 
    # {})
    
    # send_bytes = "Hello this is bytes data"
    client = airsim.MultirotorClient()
    client.confirmConnection()
    client.armDisarm(True)
    
    for i in range(1000):
        # responses = client.simGetImages([
        #     airsim.ImageRequest("DepthPlanar", airsim.ImageType.DepthPlanar, True, False),
        #     airsim.ImageRequest("RGB", airsim.ImageType.Scene, False, False)
        # ])
        responses = client.simGetImages([
            airsim.ImageRequest("front_center_custom", airsim.ImageType.DepthPlanar, True, False),
            airsim.ImageRequest("front_center_custom", airsim.ImageType.Scene, False, False)
        ], vehicle_name="drone_1")

        # depth_image = np.array(responses[0].image_data_float, dtype=np.float32)
        # depth_image = depth_image.reshape(responses[0].height, responses[0].width)
        # print(depth_image)

        rgb_image = np.frombuffer(responses[1].image_data_uint8, dtype=np.uint8)
        rgb_image = rgb_image.reshape(responses[1].height, responses[1].width, 3)
        rgb_image = rgb_image[..., :3][..., ::-1]

        # 只接受 continuous numpy array
        # depth_image = np.ascontiguousarray(depth_image, dtype=np.float32)
        rgb_image = np.ascontiguousarray(rgb_image, dtype=np.uint8)
        
        # depth_image_data = Data_Wrapper(depth_image)
        rgb_image_data = Data_Wrapper(rgb_image)
        # bytes_data = Data_Wrapper(send_bytes)
        
        rtp_session.send_data(0, rgb_image_data, True)
        # rtp_session.send_data(1, depth_image_data, True)
        # rtp_session.send_data(2, bytes_data, False)

        print("======= Number: {} =======".format(i))