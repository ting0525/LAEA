#include "RTPSession.h"
#include "AirsimClient.h"
#include "PointCloudCodec.h"

#include <climits>
#include <map>

int main(void){
    
    RTPSession *session = new RTPSession();
    
    std::string local_ip = "127.0.0.1";
    std::string remote_ip = "127.0.0.1";
    uint16_t local_port = 10000;
    uint16_t remote_port = 12000;

    int ret;

    ret = session->create_session(local_ip, remote_ip);

    std::string stream_name = "Lidar point cloud stream";
    int stream_id = 0;
    std::string media_type = "pointcloud";
    int payload_type_id = 98;
    std::string direction = "sendonly";

    std::map <std::string, std::string> format_params = {
        {"fields", "xyz"}
    }; 
    CodecParam codec_param(98, "PCL", format_params);
    exit(0);


    std::map<std::string, int> codec_format = {
        {"PCL", payload_type_id}
    };
    
    std::map<std::string, std::string> params = {
        {"fields", "xyz"}
    };


    ret = session->create_stream(
        stream_id, local_port, remote_port,
        stream_name, 
        direction,
        media_type,
        codec_format,
        params
    );

    AirsimClient airsim_client = AirsimClient();
    airsim_client.start();

    std::vector<point_cloud> pcloud_data;
    msr::airlib::LidarData lidar_data;
    
    std::stringstream compressed_data;
    
    for (int i = 1; i < 4500; i++){
        airsim_client.get_lidar_data(lidar_data, pcloud_data);
        pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZ>());

        for(int index=0; index<pcloud_data.size(); index++){
            pcloud->push_back(pcl::PointXYZ(pcloud_data[index].x, pcloud_data[index].y, pcloud_data[index].z));
        }
        
        Datatype data = pcloud;
        if(session->send_data(0, data, true) != 0){
            std::cout << "Error in rtpsession send data, exit" << std::endl;    
            exit(0);
        }
        std::cout << "frame: " << i << std::endl;
        std::this_thread::sleep_for(std::chrono::milliseconds(36));
    }

    return 0;
}