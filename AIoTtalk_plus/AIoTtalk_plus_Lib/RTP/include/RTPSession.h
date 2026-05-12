#ifndef _RTPSession_H_
#define _RTPSession_H_

#include "Common.h"
#include "Codec.h"
#include "Stream.h"
#include "uvgrtp_callback.h"
#include "json.hpp"

class Stream;

class RTPSession{
    static int stream_id_count;

    public:
        RTPSession();
        ~RTPSession();
    
    public:
        uvg_rtp::context context;
        uvg_rtp::session *session;

    private:
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
    
    public:
        std::map<int, Stream*> streams;

    public:
        int send_data(int _stream_id, Datatype &_raw_data, bool _encode);
        int send_data2(int _stream_id, Data_Wrapper &_data_wrapper, bool _encode);
        std::vector<Datatype> get_data(int stream_id, bool decode);
        std::vector<Data_Wrapper> get_data2(int _stream_id, bool _decode);

    public:
        int read_json_input_and_init();
        int init(std::string &json_data);
        int create_session(std::string _local_ip, std::string _remote_ip);
        int destroy_session();
    
    public:
        int create_stream(
            int _id, uint16_t _local_port, uint16_t _remote_port,
            std::string _name, 
            std::string _direction,
            std::string _media_type,
            std::vector<CodecParam> &codec_params
        );
        
        int destroy_stream(int _id);
    
    public:
        void copy_frame(uvg_rtp::frame::rtp_frame *frame);
        int process_frame();

};

#endif