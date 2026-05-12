#ifndef _Stream_H_
#define _Stream_H_

#include "Common.h"
#include "Codec.h"
#include "VideoCodec.h"
#include "DepthImageCodec.h"
#include "PointCloudCodec.h"
#include "SharedQueue.h"
#include "RTPSession.h"
#include "uvgrtp_callback.h"


int regex_split(std::string _str, std::regex &_match_regex, std::regex &_split_regex, std::vector<std::string> &split_str);

class RTPSession;
class Stream{
    public:
        Stream();
        ~Stream();
    
    public:
        int id;
        uint16_t local_port;
        uint16_t remote_port;
        std::string name;
        std::string media_type;
        int payload_type_id;
        std::string direction;
        
        SharedQueue<struct Binary_Data *> stream_buffer;
    
    public:
        int init(
            RTPSession *_rtp_session,
            int _id, uint16_t _local_port, uint16_t _remote_port,
            std::string _name, 
            std::string _direction,
            std::string _media_type, 
            std::vector<CodecParam> &_codec_params
        );
        
        int terminate(
            RTPSession *_rtp_session
        );
        
    public:
        uvg_rtp::media_stream *media_stream;
        int init_media_stream(
            RTPSession *_rtp_session, 
            uint16_t _local_port,
            uint16_t _remote_port,
            std::string _direction
        );
    
    public:
        Codec *media_codec;
        bool codec_enabled = false;
        int init_media_codec(
            std::string _media_type, 
            std::vector<CodecParam> &_codec_params
        ); 

    public:
        int send_data(Datatype &_raw_data, bool _encode);
        int _send_data(struct Binary_Data *_data);

        int get_data(std::vector<Datatype> &_decode_data, bool _decode);
        struct Binary_Data* _get_data();
};

#endif