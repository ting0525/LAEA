
#include "RTPSession.h"
#include "base64.hpp"
#include "json.hpp"
#include <algorithm>
#include "RequestUtil.h"
#include <curl/curl.h>
#include <string>
#include <iostream>

// AI model URL
std::string model_url = "http://172.17.0.1:5000/detect/image";

std::string urlEncode(const std::string& value){
    CURL *curl = curl_easy_init();
    if(curl){
        char *encoded = curl_easy_escape(curl, value.c_str(), value.length());
        std::string result(encoded);
        curl_free(encoded);
        curl_easy_cleanup(curl);
        return result;
    }
    return value;
}

int main(int argc, char **argv){
    
    sua_session = new RTPSession();
    aua_session = new RTPSession();

    ret = sua_session->create_session("127.0.0.1", "127.0.0.1");
    ret = aua_session->create_session("127.0.0.1", "127.0.0.1");

    //rgb image stream
    std::map<std::string, int> rgb_image_codec_format = {
        {"H264", 96}
    };

    std::map<std::string, std::string> rgb_image_codec_params = {
        {"resolution", "640*480"}
    };

    ret = sua_session->create_stream(
        0, 14000, 13000,
        "RGB image stream",
        "recvonly",
        "video",
        rgb_image_codec_format,
        rgb_image_codec_params
    );
    if(ret != 0){ exit(0); }

    while(true){
        std::vector<Datatype> data;
        data = sua_session->get_data(0, true);
        for(auto &_data:data){
            if(std::holds_alternative<cv::Mat>(_data)){
                auto rgb_image = std::get<cv::Mat>(_data);
                std::vector<uchar> data_encode;
                std::vector<int> params = std::vector<int>(2);
                param[0] = cv::IMWRITE_JPEG_QUALITY;
                param[1] = 95;
                cv::imencode(".jpg", src, data_encode, param);
                std::string encode_str(data_encode.begin(), data_encode.end());
                string b64_encode_str = base64::to_base64(encode_str);

                vector<std::string> headers = {"Content-Type: application/x-www-form-urlencoded"};
                std::string request_body = "robot_id="+urlEncode(std::to_string(1)) + "&image=" + urlEncode(b64_encode_str);
                std::string response = requests::post(
                    model_url,
                    headers,
                    request_body
                );
                std::cout << response << std::endl;
            }
        }
    }

    return 0;
    // cv::Mat src = cv::imread("/home/james/handover/AIoTtalk/AIoTtalk_Server/AIoTtalk_plus/RTPDevice/AI_RTPDevice/catkin_ws/build/rtp_device/dog.jpg");
    // std::cout << "width: " << src.cols << std::endl;
    // std::cout << "height: " << src.rows << std::endl;
    
    // std::vector<uchar> data_encode;
    // std::vector<int> param = std::vector<int>(2);
    // param[0] = cv::IMWRITE_JPEG_QUALITY;
    // param[1] = 95;
    // cv::imencode(".jpg", src, data_encode, param);
    // std::string encode_str(data_encode.begin(), data_encode.end());
    // string b64_encode_str = base64::to_base64(encode_str);
    
    //nlohmann::json params;
    //params["robot_id"] = 1;
    //params["image"] = b64_encode_str;
    //vector<std::string> headers = {"Content-Type: application/json"};
    // the jbtfd23/darknet image model default content-type
    // vector<std::string> headers = {"Content-Type: application/x-www-form-urlencoded"};
    // nlohmann::json payload = {
    //     {"robot_id", 1},
    //     {"image", b64_encode_str}
    // };
    // std::string request_body = payload.dump();
    //std::cout << request_body << std::endl;
    // std::string request_body = "robot_id="+urlEncode(std::to_string(1)) + "&image=" + urlEncode(b64_encode_str);
    // std::string response = requests::post(
    //     model_url,
    //     headers,
    //     request_body
    // );
    // std::cout << response << std::endl;

}

// testing codes
