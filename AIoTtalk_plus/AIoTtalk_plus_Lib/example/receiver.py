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

# 建置完的 python module 存放在 RTP/build 下
# MyTool_pybind11.cpython-38-x86_64-linux-gnu.so 檔
# add python library path
current_dir = os.path.dirname(os.path.abspath(__file__))
rtp_build_path = os.path.join(current_dir, '../RTP/build')
sys.path.append(os.path.abspath(rtp_build_path))

from MyTool_pybind11 import RTPSession, Data_Wrapper, CodecParam

# rtp_session = RTPSession()

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

    while(True):
        rgb_image_list = rtp_session.get_data(0, True)
        print("======== rgb_images: {} ========".format(len(rgb_image_list)))
        
        for rgb_image in rgb_image_list:
            rgb_image = rgb_image.convert_cv_mat()
            if cv is not None:
                cv.imwrite('./output.jpg', cv.cvtColor(rgb_image, cv.COLOR_RGB2BGR))

        del rgb_image_list

        
    # for local_device_media, remote_device_media in zip(local_device_params["media"], remote_device_params["media"]):
    #     media_type = remote_device_media["media_type"]
    #     remote_ip = local_device_media["ip_address"]
    #     local_ip = remote_device_media["ip_address"]
    #     remote_port = local_device_media["port"]
    #     local_port = remote_device_media["port"]



    # local_device_ip = local_device_params["origin_ip_address"]
    # remote_device_ip = remote_device_params[""]
    # rtp_session = RTPSession()
    # ret = rtp_session.create_session("127.0.0.1", "127.0.0.1")
    # if(ret != 0):
    #     exit()


    # codec_param = CodecParam(96, "H264", {"resolution": "640*480"})
    # ret = rtp_session.create_stream(
    #     0, 13000, 12000, 
    #     "rgb_stream", 
    #     "recvonly",
    #     "video",
    #     [codec_param] 
    # )

    # codec_param = CodecParam(97, "Zdepth", {"resolution": "640*480"})
    # ret = rtp_session.create_stream(
    #     1, 20000, 21000, 
    #     "depth_stream", 
    #     "recvonly",
    #     "depth_image",
    #     [codec_param] 
    # )

    # codec_param = CodecParam(100, "raw_bytes", {})
    # ret = rtp_session.create_stream(
    #     2, 8000, 9000, 
    #     "raw_stream", 
    #     "recvonly",
    #     "raw_bytes",
    #     [codec_param]
    # )

    # while(True):
    #     rgb_image_list = rtp_session.get_data(0, True)
    #     depth_image_list = rtp_session.get_data(1, True)
    #     bytes_data_list = rtp_session.get_data(2, False)

    #     print("======== rgb_images: {} ========".format(len(rgb_image_list)))
    #     print("======== depth_images: {} ========".format(len(depth_image_list)))
    #     print("======== bytes_data: {} ========".format(len(bytes_data_list)))

    #     for rgb_image in rgb_image_list:
    #         rgb_image = rgb_image.convert_cv_mat()
    #         #print(rgb_image)

    #     for depth_image in depth_image_list:
    #         depth_image = depth_image.convert_cv_mat()
    #     #     print(depth_image)
        
    #     for bytes_data in bytes_data_list:
    #         print(bytes_data.convert_raw_bytes().decode())

    #     del rgb_image_list
    #     del depth_image_list
    #     del bytes_data_list
