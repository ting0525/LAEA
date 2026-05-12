#ifndef _Codec_H_
#define _Codec_H_
#include "Common.h"
#include "DataWrapper.h"

struct CodecParam{
    int payload_type_id;
    std::string codec;
    std::map<std::string, std::string> format_params;

    CodecParam() = default;
    CodecParam(
        int _payload_type_id, 
        std::string _codec,
        std::map<std::string, std::string> &_format_params
    ):payload_type_id(_payload_type_id),  
    codec(_codec), 
    format_params(_format_params) {};
};

class Codec{
    public:
        Codec(){};
        ~Codec(){};
    public:
        virtual int encode(Datatype &_raw_data, Binary_Data *_encode_data) = 0;
        virtual int decode(Binary_Data *_encode_data, std::vector<Datatype> &_decode_data) = 0;
};

#endif