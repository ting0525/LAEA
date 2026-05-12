#include "RTPSession.h"
#include "AirsimClient.h"

std::queue<cv::Mat> rgb_images_queue, depth_images_queue;
std::mutex rgb_images_queue_lock, depth_images_queue_lock;

void send_rgb_image(int stream_id, RTPSession *session){
    while(true){
        if(rgb_images_queue.size() > 0){
            cv::Mat rgb_image;
            std::lock_guard<std::mutex> _lock_guard(rgb_images_queue_lock);
            {
                rgb_image = rgb_images_queue.front();
                rgb_images_queue.pop();
            }
            Datatype data = rgb_image;
            session->send_data(stream_id, data, true);
        }
    }
}

void send_depth_image(int stream_id, RTPSession *session){
    while(true){
        if(depth_images_queue.size() > 0){
            cv::Mat depth_image;
            std::lock_guard<std::mutex> _lock_guard(depth_images_queue_lock);
            {
                depth_image = depth_images_queue.front();
                depth_images_queue.pop();
            }
            Datatype data = depth_image;
            session->send_data(stream_id, data, true);
        }
    }
}

int main(int argc, char **argv){
    RTPSession *session = new RTPSession();

    int ret;

    std::string local_ip = "127.0.0.1";
    std::string remote_ip = "127.0.0.1";
    
    ret = session->create_session(local_ip, remote_ip);
    if(ret != 0){ exit(0); }
    
    // rgb image stream
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
    

    // depth image stream
    std::map<std::string, int> depth_image_codec_format = {
        {"Zdepth", 97}
    };
    std::map<std::string, std::string> depth_image_codec_params = {
        {"resolution", "640*480"}  
    };
    ret = session->create_stream(
        1, 15000, 16000,
        "Depth image stream",
        "sendonly",
        "depth_image",
        depth_image_codec_format,
        depth_image_codec_params
    );
    if(ret != 0){ exit(0); }
    
    std::thread rgb_image_thread = std::thread(send_rgb_image, 0, session);
    std::thread depth_image_thread = std::thread(send_depth_image, 1, session);

    AirsimClient airsim_client;
    airsim_client.start();
    std::vector<ImageResponse> image_response;

    for(int i = 0; i < 1200; i++){
        airsim_client.get_image_data(image_response);
        // cv::Mat *rgb_image = new cv::Mat(
        //     image_response.at(0).height, image_response.at(0).width, CV_8UC3,
        //     (void*) image_response.at(0).image_data_uint8.data()
        // );

        // cv::Mat *depth_image = new cv::Mat(
        //     image_response.at(1).height, image_response.at(1).width, CV_32FC1,
        //     (void*) image_response.at(1).image_data_float.data()
        // );
        
        cv::Mat rgb_image(
            image_response.at(0).height, image_response.at(0).width, CV_8UC3,
            (void*) image_response.at(0).image_data_uint8.data()
        );
        cv::Mat depth_image(
            image_response.at(1).height, image_response.at(1).width, CV_32FC1,
            (void*) image_response.at(1).image_data_float.data()
        );

        cv::Mat depth_image_uint16;
        airsim_client.process_depth_data(depth_image, depth_image_uint16);

        std::lock_guard<std::mutex> _lock_guard(rgb_images_queue_lock);
        {
            rgb_images_queue.push(std::move(rgb_image));
        }

        std::lock_guard<std::mutex> _lock_guard2(depth_images_queue_lock);
        {
            //depth_images_queue.push(depth_image);
            depth_images_queue.push(std::move(depth_image_uint16));
        }

        std::cout << "frame: " << i << std::endl;
    }

    return 0;
}