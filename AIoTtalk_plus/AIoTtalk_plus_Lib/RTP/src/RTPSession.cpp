#include "RTPSession.h"
#include <atomic>

RTPSession::RTPSession(){};
RTPSession::~RTPSession(){};

int RTPSession::stream_id_count = 0;

int RTPSession::read_json_input_and_init(){
    std::string json_data;
    std::cout << "C++ process started" << std::endl;
    std::cout.flush();

    if(std::getline(std::cin, json_data)){
        std::cout << "Receive json data from Python RTPDevice" << std::endl;
        std::cout.flush();
    }

    int ret = init(json_data);
    if(ret != 0){
        std::cout << "Initialize rtp steams failed" << std::endl;
        std::cerr << "CREATE_FAILED" << std::endl;
        std::cerr.flush();
        return -1;
    }
    std::cerr << "CREATE_SUCCESS" << std::endl;
    std::cerr.flush();
    return 0;
}

int RTPSession::init(std::string &json_data){
    
    nlohmann::json parsed_json = nlohmann::json::parse(json_data);
    std::cout << "Parsed json data" << std::endl;

    std::string session_name = parsed_json["session_name"];
    std::string remote_ip = parsed_json["ip_address"]["remote_ip"];
    std::string local_ip = parsed_json["ip_address"]["local_ip"];

    std::cout << "Session Name: " << session_name << std::endl;
    std::cout << "Remote IP Address: " << remote_ip << std::endl;
    std::cout << "Local IP Address: " << local_ip << std::endl;
    
    int ret;
    ret = create_session(local_ip, remote_ip);
    if(ret != 0) return -1;

    for(const auto& media : parsed_json["media"]){
        std::string media_type = media["media_type"];
        std::string direction = media["direction"];
        std::string stream_name = media["stream_name"];
        uint16_t remote_port = media["port"]["remote_port"];
        uint16_t local_port = media["port"]["local_port"];

        // std::map<std::string, int> format_list;
        // std::map<std::string, std::string> params;
        std::vector<struct CodecParam> codec_params;
        
        if(media.contains("payload_type")){
            for(auto &payload : media["payload_type"].items()){
                struct CodecParam _codec_param;

                _codec_param.payload_type_id = std::stoi(payload.key());
                _codec_param.codec = payload.value()["codec"];

                if(payload.value().contains("params")){
                    for(auto &param : payload.value()["params"].items()){
                        _codec_param.format_params[param.key()] = param.value();
                    }
                }
                codec_params.push_back(_codec_param);
            }
        }else{
            std::cout << "Missing payload type!" << std::endl;
            return -1;
        }

        ret = create_stream(
            stream_id_count, local_port, remote_port,
            stream_name, 
            direction,
            media_type,
            codec_params
        );

        if(ret != 0) return -1;
    }

    return 0;
}

void RTPSession::copy_frame(uvg_rtp::frame::rtp_frame *frame){
    //std::cout << "Payload type: " << (int)(frame->header).payload<< std::endl;
    size_t size = frame->payload_len;
    int payload_type_id = (int)(frame->header).payload;
    std::map<int, Stream *>::iterator it;
    
    // stream 過多不確定會不會執行太慢
    for(it = streams.begin(); it != streams.end(); it++){
        Stream *stream = it->second;
        if (stream->payload_type_id == payload_type_id){

            Binary_Data *binary_data = new Binary_Data();
            binary_data->buffer = new uint8_t[size];
            binary_data->size = size;
            memcpy(binary_data->buffer, frame->payload, size);
            stream->stream_buffer.put(binary_data);
            return;
        }
    }
    std::cout << "Unknown payload type: " << payload_type_id << ", discard frame" << std::endl;
};

int RTPSession::process_frame(){
    return 0;
};

// Session Function
int RTPSession::create_session(std::string local_ip, std::string remote_ip){
    std::pair<std::string, std::string> bind_addresses(local_ip, remote_ip);
    std::cout << "Create session!" << std::endl;
    session = context.create_session(bind_addresses);
    
    return session ? 0 : -1;
};

int RTPSession::destroy_session(){
    int ret;
    for (std::map<int, Stream*>::iterator iter = streams.begin(); iter!=streams.end();){
        std::cout << "Destroy stream id: " << (*iter).first << std::endl;
        ret = ((*iter).second)->terminate(this);
        iter = streams.erase(iter);
    }

    context.destroy_session(session);
    std::cout << "Destroy session!" << std::endl;
    return 0;
};



// Stream Function
int RTPSession::create_stream(
        int _id, uint16_t _local_port, uint16_t _remote_port,
        std::string _name, 
        std::string _direction,
        std::string _media_type, 
        std::vector<CodecParam> &_codec_params
    )
{   
    if(session == NULL){
        std::cout << "Session not initialized!" << std::endl;
        return -1;
    }
    
    // create stream
    int ret;
    Stream *stream = new Stream();
    ret = stream->init(
        this, _id, _local_port, _remote_port, 
        _name, 
        _direction,
        _media_type,
        _codec_params
    );
    
    if (ret < 0){
        std::cout << "Create stream failed!" << std::endl;
        delete(stream);
    }else{
        streams.insert(std::pair<int, Stream*>(_id, stream));
    }
    return 0;
};

int RTPSession::destroy_stream(int _id){
    int ret;
    std::map <int, Stream*>::iterator iter;
    
    iter = streams.find(_id);
    if(iter != streams.end()){
        std::cout << "Destroy stream id: " << (*iter).first << std::endl;
        ret = ((*iter).second)->terminate(this);
        iter = streams.erase(iter);
    }else{
        std::cout << "Can not find stream id: " << _id << std::endl;
    }
    return 0;
}

int RTPSession::send_data(int _stream_id, Datatype &_raw_data, bool _encode=true){
    return streams[_stream_id]->send_data(_raw_data, _encode);
}

int RTPSession::send_data2(int _stream_id, Data_Wrapper &_data_wrapper, bool _encode=true){
    return streams[_stream_id]->send_data(_data_wrapper.data, _encode);
};

std::vector<Datatype> RTPSession::get_data(int _stream_id, bool _decode){

    int ret;
    std::vector<Datatype> decode_data;

    ret = streams[_stream_id]->get_data(decode_data, _decode);
    if(ret != 0){
        std::cout << "No data received" << std::endl;
    }

    return std::move(decode_data);
}

std::vector<Data_Wrapper> RTPSession::get_data2(int _stream_id, bool _decode){
    
    int ret;
    auto decode_data = std::vector<Datatype>();
    auto wrapper_vector = std::vector<Data_Wrapper>();

    ret = streams[_stream_id]->get_data(decode_data, _decode);
    
    for(auto &data : (decode_data)){
        Data_Wrapper wrapper;
        wrapper.data = data;
        wrapper_vector.emplace_back(std::move(wrapper));
    }

    return std::move(wrapper_vector);
};
