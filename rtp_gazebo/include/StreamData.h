#include <string>
struct StreamData{
    int stream_id;
    int local_port;
    int remote_port;
    std::string stream_name;
    std::string media_type;
    int payload_id;
    std::string direction;
};