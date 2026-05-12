#include "Stream.h"

    
// RCE_RTCP flag 為設定是否啟用 RTCP
// 目前 uvgrtp 在測試時似乎有 bug，RTP 與 RTCP 同時使用時 (設定 RCP_RTCP flag)，
// 利用 RCE_FRAGEMNT_GENERTIC 接收 frame，第一個 frame 會收不到
// 單獨使用 RTP (不設定 RCP_RTCP flag) 不會有此情況
// 相關討論 https://github.com/ultravideo/uvgRTP/issues/67

int no_flags = RCE_NO_FLAGS;
bool enable_RTCP = false;

int bidirection_flags = //RCE_RTCP |
                            //RCE_SYSTEM_CALL_CLUSTERING |
                            RCE_FRAGMENT_GENERIC;
                            
int send_flags = // RCE_RTCP |                      /* enable RTCP */
                    //RCE_SYSTEM_CALL_CLUSTERING |    /* Enable system call clustering (only Linux) */
                    RCE_SEND_ONLY |                 /* interpret address/port as destination address/port */
                    RCE_FRAGMENT_GENERIC;                  

int recv_flags = // RCE_RTCP |                      /* enable RTCP */
                    //RCE_SYSTEM_CALL_CLUSTERING |
                    RCE_RECEIVE_ONLY |           /* interpret address/port as binding interface */
                    RCE_FRAGMENT_GENERIC;  

// 正則表達式 parsing 函式
int regex_split(std::string _str, std::regex &_match_regex, std::regex &_split_regex, std::vector<std::string> &split_str){
    if(std::regex_match(_str, _match_regex)){
        std::sregex_token_iterator iter(_str.begin(), _str.end(), _split_regex);
        std::sregex_token_iterator end;
        for(iter; iter != end; ++iter){
            split_str.push_back(*iter);
        }
        return 0;
        
    }
    return -1;
}

Stream::Stream(){};
Stream::~Stream(){};

int Stream::init(
    RTPSession *_rtp_session,
    int _id, uint16_t _local_port, uint16_t _remote_port,
    std::string _name, 
    std::string _direction,
    std::string _media_type, 
    std::vector<CodecParam> &_codec_params
    //std::map <std::string, int> &_format_list,
    //std::map<string, string> &_params
){
    id = _id;
    local_port = _local_port;
    remote_port = _remote_port;
    name = _name;
    direction = _direction;
    media_type = _media_type;

    int ret;
    if ((ret = init_media_stream(_rtp_session, _local_port, _remote_port, _direction)) != 0){
        std::cout << "Init media stream failed" << std::endl;
        return -1;
    }

    if((ret = init_media_codec(_media_type, _codec_params)) != 0){
        std::cout << "Init media codec failed" << std::endl;
        return -1;
    }

    return 0;
}

int Stream::terminate(RTPSession *_rtp_session){
    
    (_rtp_session->session)->destroy_stream(media_stream);
    delete media_codec;

    return 0;
}

int Stream::init_media_stream(
    RTPSession *_rtp_session, 
    uint16_t _local_port,
    uint16_t _remote_port,
    std::string _direction
){
    int ret;
    // create uvgrtp media stream
    if(_direction.compare("recvonly") == 0){
        media_stream = (_rtp_session->session)->create_stream(_local_port, _remote_port, RTP_FORMAT_GENERIC, recv_flags);
        if (!media_stream || 
            //(stream->get_rtcp()->install_sender_hook(rtcp_send_callback)) != RTP_OK ||
            //(media_stream->install_receive_hook(this, rtp_frame_recv_callback)) != RTP_OK
            (media_stream->install_receive_hook(_rtp_session, rtp_frame_recv_callback)) != RTP_OK
        )   
        {
            std::cout << "Create stream failed: " << name << std::endl;
            return -1;
        }
        int BUFFER_SIZE_MB = 400 * 1000 * 1000;
        media_stream->configure_ctx(RCC_UDP_RCV_BUF_SIZE, BUFFER_SIZE_MB);
        //int MAX_PACKET_INTERVAL_MS = 2000;
        //stream->configure_ctx(RCC_PKT_MAX_DELAY, MAX_PACKET_INTERVAL_MS);
    }else if(_direction.compare("sendonly") == 0){
        media_stream = (_rtp_session->session)->create_stream(_local_port, _remote_port, RTP_FORMAT_GENERIC, send_flags);
        if (!media_stream  \
        //||(stream->get_rtcp()->install_receiver_hook(rtcp_recv_callback)) != RTP_OK
        )
        {
            std::cout << "Create stream failed: " << name << std::endl;
            return -1;
        }
        int BUFFER_SIZE_MB = 400 * 1000 * 1000;
        media_stream->configure_ctx(RCC_UDP_SND_BUF_SIZE, BUFFER_SIZE_MB);

    }else if(_direction.compare("sendrecv") == 0){
        media_stream = (_rtp_session->session)->create_stream(_local_port, _remote_port, RTP_FORMAT_GENERIC, bidirection_flags);
        if (!media_stream || 
            //(stream->get_rtcp()->install_sender_hook(rtcp_send_callback)) != RTP_OK
            //(media_stream->install_receive_hook(this, rtp_frame_recv_callback)) != RTP_OK 
            (media_stream->install_receive_hook(_rtp_session, rtp_frame_recv_callback)) != RTP_OK
        )
        {
            std::cout << "Create stream failed: " << name << std::endl;
            return -1;
        }
        
    }else{
        std::cout << "Not supported stream direction type: " << _direction << std::endl;
        return -1;
    }
    
    return 0;
}

int Stream::init_media_codec(
    std::string _media_type, 
    //std::map <std::string, int> &_format_list, 
    //std::map <std::string, string> &_param_list
    std::vector<CodecParam> &_codec_params
){
    //std::map<std::string, int>::iterator format_list_it;
    //std::map<std::string, std::string>::iterator param_list_it;
    std::cout << "media type: " << _media_type << std::endl;
    bool media_codec_supported = false;
    
    std::string format;
    int _payload_type_id;

    if(_media_type.compare("video") == 0){
        for(auto &codec_param : _codec_params){
        //for(format_list_it = _format_list.begin(); format_list_it != _format_list.end(); format_list_it++){
            format = codec_param.codec;
            _payload_type_id = codec_param.payload_type_id;

            if(format == "H264"){
                // check param list
                // currently only check the video resolution
                std::string param_name, param_value;
                int height = 0, width = 0;

                if(!codec_param.format_params.empty()){
                    for(const auto &param : codec_param.format_params){

                        param_name = param.first;
                        param_value = param.second;
                        
                        if(param_name.compare("resolution") == 0){
                            std::regex match_reg("^\\d+\\*{1}\\d+"), split_reg("\\d+");
                            std::vector<std::string> split_string;

                            if(regex_split(param_value, match_reg, split_reg, split_string) == 0){
                                width = stoi(split_string[0]);
                                height = stoi(split_string[1]);
                                std::cout << "Set resolution: " << param_value << std::endl;
                            }else{
                                std::cout << "Unknown resolution: " << param_value << std::endl;
                                std::cout << "Set default resolution: 640*480" << std::endl;
                                width = 640;
                                height = 480;
                            }
                        }else{
                            std::cout << "Unkown param: "  << param_name << std::endl;
                        }
                    }
                }else{
                    width = 640;
                    height = 480;
                    std::cout << "Set default resolution: 640*480" << std::endl;
                }

                VideoCodec *video_codec = new VideoCodec(width, height);
                video_codec->init();
                media_codec = video_codec;
                this->payload_type_id = _payload_type_id;
                media_codec_supported = true;
                std::cout << "Init H264 video codec finished!" << std::endl;
                break;
            }
        }

    }else if (_media_type.compare("depth_image") == 0){
        for(auto &codec_param : _codec_params){
            format = codec_param.codec;
            _payload_type_id = codec_param.payload_type_id;
            
            if(format == "Zdepth"){
                // check param list
                // currently only check the video resolution
                std::string param_name, param_value;
                int height = 0, width = 0;

                if(!codec_param.format_params.empty()){
                    for(const auto &param : codec_param.format_params){
                        param_name = param.first;
                        param_value = param.second;
                        
                        if(param_name.compare("resolution") == 0){
                            std::regex match_reg("^\\d+\\*{1}\\d+"), split_reg("\\d+");
                            std::vector<std::string> split_string;

                            if(regex_split(param_value, match_reg, split_reg, split_string) == 0){
                                width = stoi(split_string[0]);
                                height = stoi(split_string[1]);
                                std::cout << "Set resolution: " << param_value << std::endl;
                            }else{
                                std::cout << "Unknown resolution: " << param_value << std::endl;
                                std::cout << "Set default resolution: 640*480" << std::endl;
                                width = 640;
                                height = 480;
                            }
                        }else{
                            std::cout << "Unknown param: "  << param_name << std::endl;
                        }
                    }
                }else{
                    width = 640;
                    height = 480;
                    std::cout << "Set default resolution: 640*480" << std::endl;
                }

                DepthImageCodec *depth_codec = new DepthImageCodec(width, height);
                media_codec = depth_codec;
                this->payload_type_id = _payload_type_id;
                media_codec_supported = true;
                std::cout << "Init Zdepth video codec finished!" << std::endl;
                break;
            }
        }

    }else if(_media_type.compare("pointcloud") == 0){
        for(auto &codec_param : _codec_params){
            format = codec_param.codec;
            _payload_type_id = codec_param.payload_type_id;
            
            if(format == "PCL"){
                std::string param_name, param_value;
                bool correct_fields = false;
                bool is_rgb = false;
                
                if(!codec_param.format_params.empty()){
                    for(const auto &param : codec_param.format_params){
                        param_name = param.first;
                        param_value = param.second;

                        if(param_name.compare("fields") == 0){
                            if(param_value.compare("xyz") == 0){
                                std::cout << "Create xyz fields pointcloud codec!" << std::endl;
                                is_rgb = false;
                                correct_fields = true;
                            }else if(param_value.compare("xyzrgb") == 0){
                                std::cout << "Create xyzrgb fields pointcloud codec!" << std::endl;
                                is_rgb = true;
                                correct_fields = true;
                            }else{
                                std::cout << "Unsupported pointcloud fields " << param_value << ", the codec will not be iniitialized!" << std::endl;
                            }
                        }
                    }
                }
                
                if(correct_fields){
                    PointCloudCodec *pointcloud_codec = new PointCloudCodec(is_rgb);
                    media_codec = pointcloud_codec;
                    this->payload_type_id = _payload_type_id;
                    media_codec_supported = true;
                    std::cout << "Init PCL pointcloud codec finished!" << std::endl;
                }
                break;
            }
        }

    }else if(_media_type.compare("raw_bytes") == 0){
        for(auto &codec_param : _codec_params){
            format = codec_param.codec;
            _payload_type_id = codec_param.payload_type_id;

            if(format == "raw_bytes"){
                media_codec = nullptr;
                this->payload_type_id = _payload_type_id;
                std::cout << "Raw bytes datatype, no codec enabled" << std::endl;
                break;
            }
        }
        codec_enabled = false;

    }else{
        std::cout << "Unsupported media type: " << _media_type << std::endl;
        std::cout << "Supported media type: video, depth_image, pointcloud, raw_bytes" << std::endl;
        media_codec = nullptr;
        codec_enabled = false;
        return -1;
    }
    
    if (_media_type.compare("raw_bytes") != 0 && !media_codec_supported){
        std::cout << "Unsupported media codec: " << format << ", create raw bytes stream for transferring" << std::endl;
        std::cout << "Create raw bytes datatype, no codec enabled" << std::endl;
        codec_enabled = false;
    }else{
        codec_enabled = true;
    }

    media_stream->configure_ctx(RCC_DYN_PAYLOAD_TYPE, _payload_type_id);
    media_stream->configure_ctx(RCC_MTU_SIZE, 1300);
    std::cout << "Create stream payload type id: " << this->payload_type_id << std::endl;

    return 0;
}

int Stream::send_data(Datatype & _raw_data, bool _encode){
    int ret;
    if(_encode && codec_enabled){
        Binary_Data data;
        if ((ret = media_codec->encode(_raw_data, &data)) == 0){
            return _send_data(&data);
        }else{
            std::cout << "Encode error!" << std::endl;
            return -1;
        };
    }else{
        if(std::holds_alternative<Binary_Data *>(_raw_data)){
            return _send_data(std::get<Binary_Data *>(_raw_data));
        }else{
            std::cout << "The data should be Binary_Data * type for sending raw data!" << std::endl;
            return -1;
        }
    }
    return -1;
}

int Stream::get_data(std::vector<Datatype> &_decode_data, bool decode){

    int ret;
    Binary_Data *data;

    data = _get_data();
    if (decode && !codec_enabled){
        std::cout << "Warning: codec not enabled but decode" << std::endl;
    }

    if (decode && codec_enabled){
        if((ret = media_codec->decode(data, _decode_data)) == 0){
            return 0;
        }else{
            std::cout << "Decode error!" << std::endl;
            return -1;
        }
    }else{
        _decode_data.emplace_back(data);
        return 0;
    }

    std::cout << "No data received" << std::endl;
    return -1;
}

int Stream::_send_data(struct Binary_Data *_data){
    int ret = media_stream->push_frame(_data->buffer, _data->size, RTP_NO_FLAGS);
    //std::cout << "send_data" << std::endl;
    if (ret != RTP_OK){
        std::cout << "Media stream push_frame transmit failed" << std::endl;
        return -1;
    }
    return 0;
}

struct Binary_Data* Stream::_get_data(){
    struct Binary_Data *data = stream_buffer.get();
    return data;
}