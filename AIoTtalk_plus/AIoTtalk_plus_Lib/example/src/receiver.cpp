#include "RTPSession.h"
#include "Codec.h"

std::string local_ip = "140.114.77.83";
std::string remote_ip = "140.114.77.83";

RTPSession *session;
// RTPSession *session = new RTPSession();
// VideoCodec *rgb_codec = new VideoCodec();
// DepthImageCodec *depth_codec = new DepthImageCodec();
// PointCloudCodec *pcloud_codec = new PointCloudCodec();

void recv_rgb_stream(int stream_id){
    
    int ret;
    while(true){
        std::unique_ptr <std::vector<Datatype>> data;
        data = session->get_data(stream_id, true);

        if(data){
            std::cout << "got data!" << std::endl;
        }else{
            std::cout << "no data!" << std::endl;
        }
    }
    
    //std::vector<cv::Mat *> decode_images;

    // while(true){
    //     struct Data *data;
    //     data = session->get_data(stream_id);
    //     if(data){
    //         // /ret = rgb_codec->decode(true);
    //         if (ret == 0){
    //             //std::cout << "size: " << decode_images.size() << std::endl;
    //             std::cout << "Got rgb image frame!" << std::endl;
    //             destroy_data(data);
    //         }
    //         decode_images.clear();
    //     }
    // }
}

// void recv_depth_stream(int stream_id){
    
//     int ret;
//     cv::Mat restore_depth_image;

//     while(true){
//         struct Data *data;
//         data = session->get_data(stream_id);
//         if(data){
//             ret = depth_codec->decode(data, restore_depth_image);
//             if(ret == 0){
//                 std::cout << "Got depth image frame!" << std::endl;
//                 destroy_data(data);
//             }
//         }
//     }
// }

// void recv_pcloud_stream(int stream_id){
//     int ret;
    
//     while(true){
//         pcl::PointCloud<pcl::PointXYZ>::Ptr restore_pcloud(new pcl::PointCloud<pcl::PointXYZ>());
//         struct Data *data;
//         data = session->get_data(stream_id);
//         if(data){
//             ret = pcloud_codec->decode(data, restore_pcloud);
//             std::cout << "Got point cloud frame!" << std::endl;
//             destroy_data(data);
//         }
//     }
// }

int main(int argc, char **argv){
    // rgb_codec->init(
    //     640, 480, AV_CODEC_ID_H264, AVMEDIA_TYPE_VIDEO, AV_PIX_FMT_YUV420P, AV_PIX_FMT_BGR24
    // );

    int ret;
    session = new RTPSession();
    if ((ret = session->create_session(local_ip, remote_ip)) != 0){
        exit(0);
    }
    
    std::map <std::string, int> format_list;
    std::map <std::string, std::string> params;

    format_list.insert(std::pair<std::string, int>("H264", 96));

    if((ret = session->create_stream(
        0, 13000, 12000, 
        "rgb_stream", 
        "recvonly",
        "video", format_list, 
        params)) != 0){
        exit(0);
    }

    std::thread recv_rgb_thread = std::thread(recv_rgb_stream, 0);
    while(1);
    // // create two stream, rgb and depth stream
    
    // if((ret = session->create_stream(
    //     0, 11000, 10000, "rgb_stream", "video", 96, "recvonly")) != 0){
    //     exit(0);
    // }
    
    // if((ret = session->create_stream(
    //     1, 13000, 12000, "depth_stream", "video", 97, "recvonly")) != 0){
    //     exit(0);
    // }
    
    // // create point cloud stream
    // if((ret = session->create_stream(
    //     2, 15000, 14000, "point_cloud", "pointcloud", 98, "recvonly")) != 0){
    //     exit(0);
    // }

    // std::thread recv_rgb_thread = std::thread(recv_rgb_stream, 0);
    // std::thread recv_depth_thread = std::thread(recv_depth_stream, 1);
    // std::thread recv_pcloud_thread = std::thread(recv_pcloud_stream, 2);
    // while(1);

    return 0;
}