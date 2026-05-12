#include <iostream>
#include <string>
#include "json.hpp"
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>

using json = nlohmann::json;

int main(void)
{
    char host[256];
    
    std::string json_data;
    //std::getline(std::cin, json_data);
    //json sdp_info = json::parse(json_data);
    std::cout << "C++ process started" << std::endl;
    std::cout.flush();

    if(std::getline(std::cin, json_data)){
        std::cout << "Received from python: " << json_data << std::endl;
        std::cout.flush();

        // try{
            json parsed_json = json::parse(json_data);
            std::cout << "parse json" << std::endl;
            //std::cout << parsed_json.dump(4) << std::endl;
            std::cout.flush();
            std::cout << "session_name: " << parsed_json["session_name"] << std::endl;
            std::cout << "ip_address: " << parsed_json["ip_address"] << std::endl;
            for (const auto &media: parsed_json["media"]){
                std::cout << "Media Type: " << media["media_type"] << std::endl;
                std::cout << "Port: " << media["port"] << std::endl;
                std::cout << "Direction: " << media["direction"] << std::endl;

                if(media.contains("payload_type")){
                    for (auto& payload : media["payload_type"].items()) {
                        std::cout << "Payload Type: " << payload.key() << std::endl;
                        std::cout << "Codec: " << payload.value()["codec"] << std::endl;
                        std::cout << "Params: " << payload.value()["params"] << std::endl;
                    }
                }

            }
        // }
    }
    //std::cout << sdp_info.dump(4) << std::endl;
    //std::cout.flush();

    return 0;

}