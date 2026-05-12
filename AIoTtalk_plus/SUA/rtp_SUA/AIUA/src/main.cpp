#include "RTPSession.h"
#include "AirsimClient.h"

int main(int argc, char **argv){
    RTPSession *session = new RTPSession();

    int ret;

    std::string local_ip = "127.0.0.1";
    std::string remote_ip = "127.0.0.1";

    ret = session->create_session(local_ip, remote_ip);
    if(ret != 0){ exit(0); }

    //rgb image stream
    std::map<std::string, int> rgb_image_codec_format = {
        {"H264", 96}
    };
    std::map<std::string, std::string> rgb_image_codec_params = {
        {"resolution", "640*480"}  
    };
    ret = session->create_stream(
        0, 13000, 14000,
        "RGB image stream",
        "sendonly",
        "video",
        rgb_image_codec_format,
        rgb_image_codec_params
    );
    if(ret != 0){ exit(0); }

    AirsimClient airsim_client;
    airsim_client.start();
    std::vector<ImageResponse> image_response;

    for(int i = 0; i < 100; i++){
        airsim_client.get_image_data(image_response);
        cv::Mat rgb_image(
            image_response.at(0).height, image_response.at(0).width, CV_8UC3,
            (void*) image_response.at(0).image_data_uint8.data()
        );

        Datatype data = rgb_image;
        session->send_data(stream_id, data, true);
        sleep(1);
        std::cout << "frame: " << i << std::endl;
    }

    return 0;
}