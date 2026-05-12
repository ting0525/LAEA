from sipsimple.core import SDPMediaStream, SDPAttribute, SDPSession, SDPConnection
import re

regex_pattern = {
        
}

def parse_sdp(sdp):
    # print(sdp)
    blocks = re.split(r"(?=^m=)", sdp.strip(), flags=re.MULTILINE)
    # #print(stream_blocks)
    # exit(0)
    # blocks = sdp.split("m=")
    sdp_description = blocks[0].splitlines()
    media_list = [blocks[index] for index in range(1, len(blocks))]
    # print(media_list)
    # exit(0)
    control_request = {}

    for line in sdp_description:
        param, value = line.split("=")
        if param == "v":
            sdp_version = value
            control_request['sdp_version'] = sdp_version
        elif param == "o":
            origin_identifier = value
            control_request["origin_identifier"] = origin_identifier
            #sdp_name = value.split(' ')[0]
            sdp_remote_ip = value.split(' ')[5]
            control_request["origin_ip_address"] = sdp_remote_ip
        elif param == "s":
            session_name = value
            control_request['session_name'] = session_name
        elif param == "t":
            session_time = value
            control_request['session_time'] = session_time
        elif param == "c":
            sdp_conn = value
            control_request["session_connection"] = sdp_conn

    # sdp_obj = SDPSession(sdp_local_ip.encode(), name=session_name.encode())
    sdp_obj = SDPSession(sdp_remote_ip.encode(), name=session_name.encode())
    # append the global ip address and session name
    #control_request = {}
    #print(origin_identifier)

    #control_request['ip_address'] = {}
    #control_request['ip_address']['remote_ip'] = sdp_remote_ip
    #control_request['ip_address']['local_ip'] = "127.0.0.1"
    control_request['media'] = []

    for media in media_list:
        regex_pattern = r"([a-zA-Z0-9\-:]+)=(.*)"
        try:
            media_info = {}
            match_fields = re.findall(regex_pattern, media)
            media_attribute_list = []
            rtpmap_list = []
            for field, value in match_fields:
                if field == 'm':
                    parts = value.split()
                    media_type = parts[0]
                    port = int(parts[1])
                    protocol = parts[2]
                    payload_types = parts[3:]
                    # print(media_type, port, protocol, payload_types)
                    media_info["media_type"] = media_type
                    media_info["port"] = port
                    media_info["protocol"] = protocol
                    #media_info["port"] = {}
                   # media_info["port"]["remote_port"] = port
                    #media_info["port"]["local_port"] = port + 2  # create the local port number is remote port + 2
                    #media_info["port"] = port # create the new port number is origin + 2
                    media_info["payload_type"] = {
                        int(payload_type): {
                            "codec": None,
                            "params": {}
                        } for payload_type in payload_types
                    }
                    
                    sdp_media_stream = SDPMediaStream(media_type.encode(), int(port), protocol.encode())
                    sdp_media_stream.formats = [payload_type.encode() for payload_type in payload_types]
                    #connection = SDPConnection(control_request["ip_address"]["remote_ip"].encode())
                    
                    print(sdp_media_stream)
                if field == 'i':
                    media_info["stream_name"] = value
                    # print(media_info)
                if field == 'c':
                    ip_addr = value.split()[-1]
                    media_info["ip_address"] = ip_addr
                    connection = SDPConnection(ip_addr.encode())
                    sdp_media_stream.connection = connection
                    # print("media_info_ip_address: " + value)
                if field == 'a':
                    attr_a = value.split(':')
                    # print(attr_a)
                    if len(attr_a) == 1:
                        # print(attr_a[0])
                        # print("len one")
                        param, value = attr_a[0].strip(), ''
                        
                        if param in ("sendonly", "recvonly", "sendrecv"):
                            media_info["direction"] = param
                            # print(media_info)
                    else:
                        param, value = attr_a[0], attr_a[1]
                        # media_attribute_list.append(SDPAttribute(param.encode(), value.encode()))
                        if param == "rtpmap":     
                            parts = value.split()
                            payload_type = int(parts[0])
                            #codec = parts[1].split('/')[0]
                            codec = parts[1]
                            if payload_type in media_info["payload_type"]:
                                media_info["payload_type"][payload_type]["codec"] = codec
                        elif param == "fmtp":
                            parts = value.split(None, 1)
                            payload_type = int(parts[0])
                            param_blob = parts[1] if len(parts) > 1 else ""
                            if payload_type in media_info["payload_type"]:
                                for chunk in param_blob.split(';'):
                                    chunk = chunk.strip()
                                    if not chunk or '=' not in chunk:
                                        continue
                                    _field, _value = chunk.split('=', 1)
                                    media_info["payload_type"][payload_type]["params"][_field.strip()] = _value.strip()

                                print(media_info)
                    media_attribute_list.append(SDPAttribute(param.encode(), value.encode()))
            sdp_media_stream.attributes = media_attribute_list
            sdp_obj.media.append(sdp_media_stream)
            
            control_request["media"].append(media_info)
            # print(control_request)
            # print(sdp_obj)

        except Exception as e:
            print("Got Exception in parsing SDP, {}".format(e))
        
        # print("-------- Control Request --------")
        # print(control_request)
        # print("-------- Control Request --------")

        # print("-------- SDP Object --------")
        # print(sdp_obj)
        # print("-------- SDP Object --------")

    return control_request, sdp_obj

def generate_sdp(params):
    ip_address = params["origin_identifier"].split(' ')[5]
    session_name = params["session_name"]
    sdp = SDPSession(ip_address.encode(), name=session_name.encode())
    if "session_connection" in params:
        ip_addr = params["session_connection"]
        conn = SDPConnection(ip_addr.encode())

    media_list = params["media"]
    for media in media_list:
        media_type = media["media_type"]
        port = media["port"]
        protocol = media["protocol"]
        direction = media["direction"]
        ip_address = media["ip_address"]
        payload_type = media["payload_type"]

        sdp_media = SDPMediaStream(media_type.encode(), int(port), protocol.encode())
        conn = SDPConnection(ip_address.encode())
        sdp_media.connection = conn
        
        # print(sdp_media)
        # exit()
        for ptype_num, values in payload_type.items():
            codec = values["codec"]
            fmtp_params = values["params"]

            sdp_media.formats = [str(ptype_num).encode()]
            sdp_media.attributes.append(SDPAttribute("rtpmap".encode(), str(str(ptype_num) + " " + codec).encode()))
            if fmtp_params:
                fmtp_blob = "; ".join(f"{name}={value}" for name, value in fmtp_params.items())
                sdp_media.attributes.append(SDPAttribute("fmtp".encode(), str(str(ptype_num) + " " + fmtp_blob).encode()))
        sdp_media.attributes.append(SDPAttribute(direction.encode(), "".encode()))
        sdp.media.append(sdp_media)

    return sdp 

if __name__ == "__main__":
    pass
#     test = "v=0\n"\
# "o=- 3949256544 3949256544 IN IP4 127.0.0.1\n"\
# "s=SLAMDevice\n"\
# "t=0 0\n"\
# "m=pointcloud 10000 RTP/AVP 98\n"\
# "i=pointcloud_stream name\n"\
# "c=IN IP4 127.0.0.1\n"\
# "a=rtpmap:98 PCL/90000\n"\
# "a=fmtp:98 fields=xyz\n"\
# "a=sendonly\n"\


# s_t = "{'sdp_version': '0', 'origin_identifier': '- 3949256544 3949256544 IN IP4 127.0.0.1', 'session_name': 'SLAMDevice', 'session_time': '0 0', 'media': [{'media_type': 'pointcloud', 'port': 10000, 'protocol': 'RTP/AVP', 'payload_type': {98: {'codec': 'PCL', 'params': {'fields': 'xyz'}}}, 'stream_name': 'pointcloud_stream name', 'ip_address': '127.0.0.1', 'direction': 'sendonly'}]}"

#x = generate_sdp(s_t)
# "m=audio 11000 RTP/AVP 111\n"\
# "c=IN IP4 127.0.0.1\n"\
# "a=rtpmap:111 opus/48000\n"\
# "a=sendonly\n"\
# "m=pointcloud 12000 RTP/AVP 98\n"\
# "c=IN IP4 127.0.0.1\n"\
# "a=rtpmap:98 octree_compression\n"\
# "a=sendonly\n"\

#print(test)



# control_request,y = parse_sdp(test)

# rtp_session = subprocess.Popen(
#     "/ROS_RTPDevice/LidarSLAM/catkin_ws/build/rtp_device/MAIN", 
#     stdin=subprocess.PIPE,
#     stdout=subprocess.PIPE, 
#     stderr=subprocess.PIPE,
#     text=True
# )

# json_data = json.dumps(control_request)
# rtp_session.
# time.sleep(2)
# with open(FIFO_PATH)
