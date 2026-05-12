from sipsimple.core import SDPMediaStream, SDPAttribute, SDPSession, SDPConnection
import sdp_transform

class SDPParser(object):
    pass

class SDPGenerator(object):
    pass
    
def parse_sdp(sdp):
    blocks = sdp.split("m=")
    sdp_description = blocks[0].splitlines()
    media_list = [blocks[index] for index in range(1, len(blocks))]
    
    for line in sdp_description:
        param, value = line.split("=")
        if param == "v":
            sdp_version = value
        elif param == "o":
            origin_identifier = value
            sdp_name = value.split(' ')[0]
            sdp_local_ip = value.split(' ')[5]
        elif param == "s":
            session_name = value
        elif param == "t":
            session_time = value
        elif param == "c":
            sdp_conn = value

    sdp_obj = SDPSession(sdp_local_ip.encode(), name=session_name.encode)
    
    control_request = []
    
    for media in media_list:
        try:
            media_info = media.splitlines()
            attr_m = media_info[0].split(' ')
            attr_c = media_info[1].split('c=')[1].split(' ')
            attr_a = [media_info[index].split('a=')[1].split(':') for index in range(2, len(media_info))]
            
            media_type, port, protocol = attr_m[:3]
            format_list = attr_m[3:]
            net_type, version, ip = attr_c

            media_stream = SDPMediaStream(media_type.encode(), int(port), protocol.encode())
            media_stream.formats = [fmat.encode() for fmat in format_list]
            connection = SDPConnection(ip.encode())
            media_stream.connection = connection

            media_attribute_list = []
            rtpmap_list = []
            direction = ""

            for attribute in attr_a:
                if len(attribute) == 1:
                    param, value = attribute[0], ''
                    if param == ("sendonly" or "recvonly" or "sendrecv"):
                        direction = param
                else:
                    param, value = attribute[0], attribute[1]
                    ''' get rtpmap format list'''
                    if param == "rtpmap":
                        rtpmap_list.append(value)
                        
            
                media_attribute_list.append(SDPAttribute(param.encode(), value.encode()))
            
            media_stream.attributes = media_attribute_list
            sdp_obj.media.append(media_stream)

            codecs = []
            for rtpmap in rtpmap_list:
                format_num, format_type = rtpmap.split()
                codecs.append([format_num, format_type])
            
            control_request.append(
                {
                    'media_type': media_type,
                    'ip_address': ip,
                    'port': port,
                    'protocol': protocol,
                    'direction': direction,
                    'codecs': codecs
                }
            )
    
        except:
            print("Error in parse sdp media description!")
    
    return control_request

def generate_sdp():
    pass